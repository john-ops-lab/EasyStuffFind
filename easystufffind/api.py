from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .backup_service import BackupService, MAX_BACKUP_BYTES
from .config import Settings
from .database import SCHEMA_VERSION, Database
from .errors import DomainError, validation_error
from .models import (
    ErrorResponse,
    BackupConfigUpdate,
    BackupCreate,
    ItemCreate,
    ItemMove,
    ItemUpdate,
    ItemUpsert,
    LocationCreate,
    LocationResolve,
    LocationUpdate,
    RestoreAuthorize,
    RestoreExecute,
    WebLogin,
    WebPasswordChange,
)
from .repository import Repository
from .security import WEB_SESSION_TTL_SECONDS, TokenManager, WebAuthManager

logger = logging.getLogger("easystufffind")

SUPPORTED_PHOTO_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
WEB_SESSION_COOKIE = "easystufffind_web_session"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_path)
    repository = Repository(database)
    token_manager = TokenManager(settings.token_path, settings.photo_url_ttl_seconds)
    web_auth_manager = WebAuthManager(database, token_manager)
    backup_service = BackupService(
        settings.data_dir,
        settings.backup_dir,
        settings.backup_config_path,
    )
    scheduler_stop = threading.Event()
    scheduler_thread: threading.Thread | None = None
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
        web_auth_manager.ensure_default_account()
        backup_service.initialize()

        def scheduler_loop() -> None:
            while not scheduler_stop.wait(30):
                try:
                    backup_service.run_scheduled_if_due()
                except Exception:
                    logger.exception("event=scheduled_backup_failed")

        scheduler_stop.clear()
        scheduler_thread = threading.Thread(
            target=scheduler_loop,
            name="easystufffind-backup-scheduler",
            daemon=True,
        )
        scheduler_thread.start()
        logger.info(
            "event=service_started version=%s data_dir=%s port=%s",
            __version__,
            settings.data_dir,
            settings.port,
        )
        yield
        scheduler_stop.set()
        scheduler_thread.join(timeout=5)
        logger.info("event=service_stopped")

    application = FastAPI(
        title="EasyStuffFind API",
        summary="家庭物品位置记录服务",
        version=__version__,
        lifespan=lifespan,
        responses={
            401: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {
                "model": ErrorResponse,
                "description": "Unprocessable Content",
            },
        },
    )
    application.state.settings = settings
    application.state.database = database
    application.state.repository = repository
    application.state.token_manager = token_manager
    application.state.web_auth_manager = web_auth_manager
    application.state.backup_service = backup_service

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
        if request.url.path == "/":
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
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
        headers = (
            {"WWW-Authenticate": "Bearer"}
            if exc.status_code == 401 and exc.code == "unauthorized"
            else None
        )
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

    def web_account(request: Request) -> dict[str, object] | None:
        return web_auth_manager.account_from_session(
            request.cookies.get(WEB_SESSION_COOKIE)
        )

    def require_web_account(request: Request) -> dict[str, object]:
        account = web_account(request)
        if account is None:
            raise DomainError(401, "web_session_required", "请先登录 Web 管理端")
        return account

    def require_api_auth(
        request: Request,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> None:
        if token_manager.verify_bearer(authorization) or web_account(request):
            return
        raise DomainError(401, "unauthorized", "缺少或无效的认证凭据")

    def set_session_cookie(
        request: Request,
        response: Response,
        session: str,
    ) -> None:
        response.set_cookie(
            key=WEB_SESSION_COOKIE,
            value=session,
            max_age=WEB_SESSION_TTL_SECONDS,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            path="/",
        )

    def public_web_user(account: dict[str, object]) -> dict[str, object]:
        return {
            "username": account["username"],
            "password_changed": account["password_changed"],
        }

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

    web_auth_api = APIRouter(prefix="/api/v1/web-auth", tags=["web-auth"])

    @web_auth_api.post("/login")
    def web_login(
        request: Request,
        response: Response,
        payload: WebLogin,
    ) -> dict[str, Any]:
        account = web_auth_manager.authenticate(payload.username, payload.password)
        if account is None:
            raise DomainError(401, "invalid_credentials", "账号或密码错误")
        set_session_cookie(
            request,
            response,
            web_auth_manager.create_session(account),
        )
        return {
            "authenticated": True,
            "expires_in_seconds": WEB_SESSION_TTL_SECONDS,
            "user": public_web_user(account),
        }

    @web_auth_api.get("/me")
    def web_me(
        account: dict[str, object] = Depends(require_web_account),
    ) -> dict[str, Any]:
        return {"authenticated": True, "user": public_web_user(account)}

    @web_auth_api.post("/logout")
    def web_logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(
            key=WEB_SESSION_COOKIE,
            path="/",
            httponly=True,
            samesite="strict",
        )
        return {"authenticated": False}

    @web_auth_api.post("/password")
    def change_web_password(
        request: Request,
        response: Response,
        payload: WebPasswordChange,
        account: dict[str, object] = Depends(require_web_account),
    ) -> dict[str, Any]:
        updated = web_auth_manager.change_password(
            str(account["username"]),
            payload.current_password,
            payload.new_password,
        )
        if updated is None:
            raise DomainError(400, "current_password_invalid", "当前密码错误")
        set_session_cookie(
            request,
            response,
            web_auth_manager.create_session(updated),
        )
        return {"changed": True, "user": public_web_user(updated)}

    backup_api = APIRouter(
        prefix="/api/v1/backups",
        tags=["backups"],
        dependencies=[Depends(require_web_account)],
    )

    @backup_api.get("/config")
    def get_backup_config() -> dict[str, Any]:
        return {"config": backup_service.public_config(backup_service.load_config())}

    @backup_api.put("/config")
    def update_backup_config(payload: BackupConfigUpdate) -> dict[str, Any]:
        values = payload.model_dump()
        clear_secret = values.pop("clear_secret")
        secret = values.pop("secret_access_key")
        if not values["access_key_id"]:
            values.pop("access_key_id")
        if values["cloud_enabled"]:
            required = ("endpoint_url", "region", "bucket")
            if any(not str(values[key]).strip() for key in required):
                raise validation_error("启用云备份时，地址、地域和 Bucket 必填")
            if not values["endpoint_url"].startswith("https://"):
                raise validation_error("对象存储地址必须使用 HTTPS")
        if values["retention_days"] not in {0, 7, 30, 90}:
            raise validation_error("本地保留天数仅支持 7、30、90 或永久")
        if clear_secret:
            values["secret_access_key"] = ""
        elif secret:
            values["secret_access_key"] = secret
        saved = backup_service.save_config(values)
        return {"saved": True, "config": backup_service.public_config(saved)}

    @backup_api.post("/test-cloud")
    def test_backup_cloud() -> dict[str, bool]:
        try:
            backup_service.test_cloud()
        except Exception as exc:
            logger.warning("event=cloud_backup_test_failed type=%s", type(exc).__name__)
            raise DomainError(400, "cloud_connection_failed", "云对象存储连接失败，请检查配置") from exc
        return {"connected": True}

    @backup_api.get("")
    def list_backups() -> dict[str, Any]:
        backups = backup_service.list_local()
        warning = None
        if backup_service.load_config().get("cloud_enabled"):
            try:
                local_ids = {record["id"] for record in backups}
                backups.extend(
                    record
                    for record in backup_service.list_cloud()
                    if record["id"] not in local_ids
                )
                backups.sort(key=lambda record: record["created_at"], reverse=True)
            except Exception:
                warning = "云端备份列表暂时不可用"
                logger.warning("event=cloud_backup_list_failed")
        return {"count": len(backups), "backups": backups, "warning": warning}

    @backup_api.post("", status_code=201)
    def create_backup(payload: BackupCreate) -> dict[str, Any]:
        try:
            record = backup_service.create_backup(upload_cloud=payload.upload_cloud)
        except Exception as exc:
            logger.exception("event=manual_backup_failed")
            raise DomainError(500, "backup_failed", "备份失败，请查看服务日志") from exc
        return {"backup": record}

    @backup_api.get("/{backup_id}/download")
    def download_backup(backup_id: str) -> FileResponse:
        try:
            path = backup_service.ensure_archive(backup_id)
        except FileNotFoundError as exc:
            raise DomainError(404, "backup_not_found", "备份不存在") from exc
        return FileResponse(
            path,
            media_type="application/zip",
            filename=path.name,
            headers={"Cache-Control": "no-store"},
        )

    @backup_api.post("/upload", status_code=201)
    async def upload_backup(request: Request) -> dict[str, Any]:
        content_length = request.headers.get("content-length")
        try:
            if content_length and int(content_length) > MAX_BACKUP_BYTES:
                raise DomainError(413, "backup_too_large", "备份文件不能超过 2 GiB")
        except ValueError as exc:
            raise validation_error("Content-Length 无效") from exc
        descriptor, temporary_name = tempfile.mkstemp(
            dir=settings.backup_dir,
            prefix=".backup-upload-",
            suffix=".zip",
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            total = 0
            with os.fdopen(descriptor, "wb") as output:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > MAX_BACKUP_BYTES:
                        raise DomainError(413, "backup_too_large", "备份文件不能超过 2 GiB")
                    output.write(chunk)
            if total == 0:
                raise validation_error("备份文件不能为空")
            record = backup_service.import_archive_file(temporary)
        except ValueError as exc:
            raise DomainError(422, "backup_invalid", str(exc)) from exc
        finally:
            temporary.unlink(missing_ok=True)
        return {"backup": record}

    @backup_api.post("/restore/authorize")
    def authorize_restore(
        payload: RestoreAuthorize,
        account: dict[str, object] = Depends(require_web_account),
    ) -> dict[str, Any]:
        username = str(account["username"])
        if not web_auth_manager.verify_current_password(username, payload.password):
            raise DomainError(400, "current_password_invalid", "当前密码错误")
        try:
            ticket, summary = backup_service.issue_restore_ticket(payload.backup_id, username)
        except (FileNotFoundError, ValueError) as exc:
            raise DomainError(422, "backup_invalid", str(exc)) from exc
        return {"authorized": True, "ticket": ticket, "expires_in_seconds": 300, "summary": summary}

    @backup_api.post("/restore/execute")
    def execute_restore(
        payload: RestoreExecute,
        account: dict[str, object] = Depends(require_web_account),
    ) -> dict[str, Any]:
        try:
            result = backup_service.restore_with_ticket(
                payload.ticket,
                str(account["username"]),
                payload.confirmation,
            )
        except PermissionError as exc:
            raise DomainError(409, "restore_confirmation_invalid", str(exc)) from exc
        except Exception as exc:
            logger.exception("event=restore_failed")
            raise DomainError(500, "restore_failed", "恢复失败，原数据已保留，请查看服务日志") from exc
        return result

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_auth)])

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

    application.include_router(web_auth_api)
    application.include_router(backup_api)
    application.include_router(api)
    application.mount("/static", StaticFiles(directory=static_dir), name="static")

    @application.get("/", include_in_schema=False)
    def web_app() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return application


app = create_app()
