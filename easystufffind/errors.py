from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DomainError(Exception):
    status_code: int
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def validation_error(message: str, **details: Any) -> DomainError:
    return DomainError(422, "validation_error", message, details)


def not_found(resource: str, identifier: Any) -> DomainError:
    return DomainError(
        404,
        f"{resource}_not_found",
        f"未找到{resource}",
        {"identifier": identifier},
    )
