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


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody
