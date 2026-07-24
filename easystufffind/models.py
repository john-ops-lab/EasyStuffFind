from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocationCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: int | None = Field(default=None, ge=1)


class LocationUpdate(StrictModel):
    name: str = Field(min_length=1, max_length=100)


class LocationResolve(StrictModel):
    path: str = Field(min_length=1, max_length=2000)
    create_missing: bool = False


class ItemCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    location_id: int | None = Field(default=None, ge=1)
    location_path: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)


class ItemUpsert(ItemCreate):
    item_id: int | None = Field(default=None, ge=1)


class ItemUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    aliases: list[str] | None = Field(default=None, max_length=50)
    location_id: int | None = Field(default=None, ge=1)
    location_path: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)


class ItemMove(StrictModel):
    location_id: int | None = Field(default=None, ge=1)
    location_path: str | None = Field(default=None, max_length=2000)


class WebLogin(StrictModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=128)


class WebPasswordChange(StrictModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class BackupConfigUpdate(StrictModel):
    cloud_enabled: bool
    provider: str = Field(pattern="^(aliyun|tencent|s3)$")
    endpoint_url: str = Field(default="", max_length=500)
    region: str = Field(default="", max_length=100)
    bucket: str = Field(default="", max_length=255)
    prefix: str = Field(default="easystufffind", max_length=500)
    access_key_id: str = Field(default="", max_length=300)
    secret_access_key: str | None = Field(default=None, max_length=500)
    clear_secret: bool = False
    frequency: str = Field(pattern="^(off|daily|weekly|monthly)$")
    time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    weekday: int = Field(default=1, ge=1, le=7)
    monthday: int = Field(default=1, ge=1, le=28)
    retention_days: int = 30


class BackupCreate(StrictModel):
    upload_cloud: bool = False


class RestoreAuthorize(StrictModel):
    backup_id: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=128)


class RestoreExecute(StrictModel):
    ticket: str = Field(min_length=20, max_length=200)
    confirmation: str = Field(pattern="^RESTORE$")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody
