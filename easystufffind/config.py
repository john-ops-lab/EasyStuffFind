from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    host: str = "0.0.0.0"
    port: int = 8733
    log_level: str = "INFO"
    photo_url_ttl_seconds: int = 3600
    max_photo_bytes: int = 15 * 1024 * 1024

    @property
    def database_path(self) -> Path:
        return self.data_dir / "easystufffind.sqlite3"

    @property
    def photo_dir(self) -> Path:
        return self.data_dir / "photos"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "api-token"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def backup_config_path(self) -> Path:
        return self.data_dir / "backup-config.json"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("EASYSTUFFFIND_DATA_DIR", "data")).expanduser().resolve()
        port_text = os.getenv("EASYSTUFFFIND_PORT", "8733")
        try:
            port = int(port_text)
        except ValueError as exc:
            raise RuntimeError("EASYSTUFFFIND_PORT 必须是整数") from exc
        if not 1 <= port <= 65535:
            raise RuntimeError("EASYSTUFFFIND_PORT 必须在 1 到 65535 之间")

        log_level = os.getenv("EASYSTUFFFIND_LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise RuntimeError("EASYSTUFFFIND_LOG_LEVEL 值无效")

        return cls(
            data_dir=data_dir,
            host=os.getenv("EASYSTUFFFIND_HOST", "0.0.0.0"),
            port=port,
            log_level=log_level,
        )
