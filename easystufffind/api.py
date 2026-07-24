from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings
from .database import SCHEMA_VERSION, Database
from .errors import DomainError, validation_error
from .models import (
    ErrorResponse,
    ItemCreate,
    ItemMove,
    ItemUpdate,
    ItemUpsert,
    LocationCreate,
    LocationResolve,
    LocationUpdate,
)
from .repository import Repository
from .security import TokenManager

logger = logging.getLogger("easystufffind")

SUPPORTED_PHOTO_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_path)
    repository = Repository(database)
    token_manager = TokenManager(settings.token_path, settings.photo_url_ttl_seconds)
    static_dir = Path(__file__).parent / "static"

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        logging.basicConfig(
            level=getattr(logging, settings.log_level),
            format="%(asctime)s level=%(levelname)s logger=%(name)s %(message)s",
        )
        settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        settings.photo_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        database.initialize()
        token_manager.ensure()
        logger.info(
            "event=service_started version=%s data_dir=%s port=%s",
            __version__,
            settings.data_dir,
            settings.port,
        )
        yield
        logger.info("event=service_stopped")

    application = FastAPI(
        title="EasyStuffFind API",
        summary="家庭物品位置记录服务",
        version=__version__,
        lifespan=lifespan,
        responses={
            401: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
    )
    application.state.settings = settings
    application.state.database = database
    application.state.repository = repository
    application.state.token_manager = token_manager

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        supplied_request_id = request.headers.get("x-request-id", "")
        if supplied_request_id and len(supplied_request_id) <= 100:
            request_id = supplied_request_id
        else:
            request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "event=request_unhandled request_id=%s method=%s path=%s",
                request_id,
                request.method,
                request.url.path,
            )
            raise
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "event=request_complete request_id=%s method=%s path=%s status=%s duration_ms=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            int((time.monotonic() - started) * 1000),
        )
        return response

    @application.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code,
            headers=headers,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": getattr(request.state, "request_id", "unknown"),
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        safe_errors = [
            {
                "location": list(error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "request_validation_error",
                    "message": "请求参数无效",
                    "details": {"errors": safe_errors},
                    "request_id": getattr(request.state, "request_id", "unknown"),
                }
            },
        )

    def require_token(
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> None:
        if not token_manager.verify_bearer(authorization):
            raise DomainError(401, "unauthorized", "缺少或无效的 API token")

    def signed_item(request: Request, item: dict[str, Any]) -> dict[str, Any]:
        if item["photo"]:
            expires, signature = token_manager.signed_photo_params(
                item["id"],
                item["photo"]["updated_at"],
            )
            base = str(request.url_for("get_photo", item_id=item["id"]))
            item["photo_url"] = f"{base}?{urlencode({'expires': expires, 'signature': signature})}"
        return item

    def signed_items(request: Request, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [signed_item(request, item) for item in items]

    @application.get("/health", tags=["system"])
    def health() -> JSONResponse:
        try:
            with database.read() as connection:
                connection.execute("SELECT 1").fetchone()
                schema_version = int(
                    connection.execute("PRAGMA user_version").fetchone()[0]
                )
            if schema_version != SCHEMA_VERSION:
                raise RuntimeError("schema version mismatch")
        except Exception:
            logger.exception("event=health_check_failed")
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "version": __version__,
                    "database": "unavailable",
                },
            )
        return JSONResponse(
            content={
                "status": "ok",
                "version": __version__,
                "database": "ok",
                "schema_version": schema_version,
            }
        )

    @application.get(
        "/media/items/{item_id}/photo",
        name="get_photo",
        tags=["photos"],
    )
    def get_photo(
        item_id: int,
        expires: int = Query(...),
        signature: str = Query(..., min_length=64, max_length=64),
    ) -> FileResponse:
        record = repository.photo_record(item_id)
        token_manager.verify_photo_signature(
            item_id,
            record["updated_at"],
            expires,
            signature,
        )
        path = settings.photo_dir / record["filename"]
        if not path.is_file():
            logger.error("event=photo_file_missing item_id=%s", item_id)
            raise DomainError(404, "photo_file_missing", "照片文件不存在")
        return FileResponse(
            path,
            media_type=record["content_type"],
            headers={"Cache-Control": "private, max-age=300"},
        )

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_token)])

    @api.get("/locations/tree", tags=["locations"])
    def location_tree() -> dict[str, Any]:
        return {"tree": repository.location_tree()}

    @api.get("/locations/search", tags=["locations"])
    def search_locations(q: str = Query(min_length=1, max_length=300)) -> dict[str, Any]:
        return repository.search_locations(q)

    @api.post("/locations/resolve", tags=["locations"])
    def resolve_location(payload: LocationResolve) -> dict[str, Any]:
        if payload.create_missing:
            location, created = repository.resolve_location_path(
                payload.path,
                create_missing=True,
            )
            return {"status": "resolved", "created": created, "location": location}
        try:
            location, _ = repository.resolve_location_path(
                payload.path,
                create_missing=False,
            )
        except DomainError as exc:
            if exc.status_code != 404:
                raise
            return repository.search_locations(payload.path)
        return {"status": "unique", "count": 1, "location": location, "candidates": []}

    @api.get("/locations", tags=["locations"])
    def list_locations() -> dict[str, Any]:
        locations = repository.list_locations()
        return {"count": len(locations), "locations": locations}

    @api.post("/locations", status_code=201, tags=["locations"])
    def create_location(payload: LocationCreate) -> dict[str, Any]:
        return {"location": repository.create_location(payload.name, payload.parent_id)}

    @api.get("/locations/{location_id}", tags=["locations"])
    def get_location(location_id: int) -> dict[str, Any]:
        return {"location": repository.get_location(location_id)}

    @api.patch("/locations/{location_id}", tags=["locations"])
    def update_location(
        location_id: int,
        payload: LocationUpdate,
    ) -> dict[str, Any]:
        return {"location": repository.update_location(location_id, payload.name)}

    @api.delete("/locations/{location_id}", tags=["locations"])
    def delete_location(location_id: int) -> JSONResponse:
        repository.delete_location(location_id)
        return JSONResponse(status_code=200, content={"deleted": True, "id": location_id})

    @api.get("/locations/{location_id}/items", tags=["locations", "items"])
    def items_by_location(
        request: Request,
        location_id: int,
        recursive: bool = False,
    ) -> dict[str, Any]:
        items = signed_items(
            request,
            repository.list_items(location_id=location_id, recursive=recursive),
        )
        return {"count": len(items), "items": items}

    @api.get("/items/search", tags=["items"])
    def search_items(
        request: Request,
        q: str = Query(min_length=1, max_length=300),
    ) -> dict[str, Any]:
        result = repository.search_items(q)
        if result["item"]:
            result["item"] = signed_item(request, result["item"])
        result["candidates"] = signed_items(request, result["candidates"])
        return result

    @api.get("/items", tags=["items"])
    def list_items(
        request: Request,
        location_id: int | None = Query(default=None, ge=1),
        recursive: bool = False,
    ) -> dict[str, Any]:
        items = signed_items(
            request,
            repository.list_items(location_id=location_id, recursive=recursive),
        )
        return {"count": len(items), "items": items}

    @api.post("/items", status_code=201, tags=["items"])
    def create_item(request: Request, payload: ItemCreate) -> dict[str, Any]:
        item = repository.create_item(**payload.model_dump())
        return {"item": signed_item(request, item)}

    @api.post("/items/upsert", tags=["items"])
    def upsert_item(request: Request, payload: ItemUpsert) -> dict[str, Any]:
        values = payload.model_dump()
        action, item = repository.upsert_item(
            **values,
            aliases_provided="aliases" in payload.model_fields_set,
            note_provided="note" in payload.model_fields_set,
        )
        return {"action": action, "item": signed_item(request, item)}

    @api.get("/items/{item_id}", tags=["items"])
    def get_item(request: Request, item_id: int) -> dict[str, Any]:
        return {"item": signed_item(request, repository.get_item(item_id))}

    @api.patch("/items/{item_id}", tags=["items"])
    def update_item(
        request: Request,
        item_id: int,
        payload: ItemUpdate,
    ) -> dict[str, Any]:
        values = payload.model_dump(exclude_unset=True)
        if not values:
            raise validation_error("至少提供一个需要修改的字段")
        if values.get("name", "sentinel") is None:
            raise validation_error("物品名称不能为 null", field="name")
        if values.get("aliases", "sentinel") is None:
            raise validation_error("别名不能为 null", field="aliases")
        item = repository.update_item(item_id, values)
        return {"item": signed_item(request, item)}

    @api.post("/items/{item_id}/move", tags=["items"])
    def move_item(
        request: Request,
        item_id: int,
        payload: ItemMove,
    ) -> dict[str, Any]:
        item = repository.move_item(item_id, **payload.model_dump())
        return {"item": signed_item(request, item)}

    @api.delete("/items/{item_id}", tags=["items"])
    def delete_item(item_id: int) -> JSONResponse:
        filename = repository.delete_item(item_id)
        if filename:
            try:
                (settings.photo_dir / filename).unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    "event=photo_cleanup_failed operation=item_delete item_id=%s",
                    item_id,
                )
        return JSONResponse(status_code=200, content={"deleted": True, "id": item_id})

    @api.put("/items/{item_id}/photo", tags=["photos"])
    async def upload_photo(request: Request, item_id: int) -> dict[str, Any]:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        extension = SUPPORTED_PHOTO_TYPES.get(content_type)
        if extension is None:
            raise DomainError(
                415,
                "unsupported_photo_type",
                "仅支持 JPEG、PNG、WebP 或 GIF 图片",
                {"supported_types": sorted(SUPPORTED_PHOTO_TYPES)},
            )
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError as exc:
                raise validation_error("Content-Length 无效") from exc
            if declared_length > settings.max_photo_bytes:
                raise DomainError(
                    413,
                    "photo_too_large",
                    "照片不能超过 15 MiB",
                    {"maximum_bytes": settings.max_photo_bytes},
                )
        body = await request.body()
        if not body:
            raise validation_error("照片内容不能为空")
        if len(body) > settings.max_photo_bytes:
            raise DomainError(
                413,
                "photo_too_large",
                "照片不能超过 15 MiB",
                {"maximum_bytes": settings.max_photo_bytes},
            )

        repository.get_item(item_id)
        filename = f"{uuid.uuid4().hex}.{extension}"
        target = settings.photo_dir / filename
        descriptor, temporary_name = tempfile.mkstemp(
            dir=settings.photo_dir,
            prefix=".upload-",
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as photo_file:
                photo_file.write(body)
                photo_file.flush()
                os.fsync(photo_file.fileno())
            os.replace(temporary, target)
            try:
                old_filename, item = repository.replace_photo_metadata(
                    item_id,
                    filename=filename,
                    content_type=content_type,
                )
            except Exception:
                target.unlink(missing_ok=True)
                raise
            if old_filename and old_filename != filename:
                try:
                    (settings.photo_dir / old_filename).unlink(missing_ok=True)
                except OSError:
                    logger.exception(
                        "event=photo_cleanup_failed operation=replace item_id=%s",
                        item_id,
                    )
        finally:
            temporary.unlink(missing_ok=True)
        return {"item": signed_item(request, item)}

    @api.delete("/items/{item_id}/photo", tags=["photos"])
    def delete_photo(request: Request, item_id: int) -> dict[str, Any]:
        filename, item = repository.remove_photo_metadata(item_id)
        if filename:
            try:
                (settings.photo_dir / filename).unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    "event=photo_cleanup_failed operation=photo_delete item_id=%s",
                    item_id,
                )
        return {"item": signed_item(request, item)}

    @api.get("/items/{item_id}/history", tags=["history"])
    def item_history(item_id: int) -> dict[str, Any]:
        history = repository.item_history(item_id)
        return {"count": len(history), "history": history}

    @api.get("/history", tags=["history"])
    def all_history(limit: int = Query(default=200, ge=1, le=1000)) -> dict[str, Any]:
        history = repository.all_history(limit)
        return {"count": len(history), "history": history}

    application.include_router(api)
    application.mount("/static", StaticFiles(directory=static_dir), name="static")

    @application.get("/", include_in_schema=False)
    def web_app() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return application


app = create_app()
