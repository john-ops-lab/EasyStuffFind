from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from pathlib import Path

from .errors import DomainError

logger = logging.getLogger("easystufffind.security")


class TokenManager:
    def __init__(self, token_path: Path, photo_url_ttl_seconds: int = 3600) -> None:
        self.token_path = token_path
        self.photo_url_ttl_seconds = photo_url_ttl_seconds
        self._token: str | None = None

    def ensure(self) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(
                self.token_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            pass
        else:
            token = secrets.token_urlsafe(48)
            with os.fdopen(descriptor, "w", encoding="utf-8") as token_file:
                token_file.write(token)
                token_file.write("\n")

        os.chmod(self.token_path, 0o600)
        token = self.token_path.read_text(encoding="utf-8").strip()
        if len(token) < 32:
            raise RuntimeError(f"API token 文件无效：{self.token_path}")
        self._token = token
        fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()
        logger.info(
            "event=token_ready path=%s sha256=%s",
            self.token_path,
            fingerprint,
        )

    def verify_bearer(self, authorization: str | None) -> bool:
        if not self._token or not authorization:
            return False
        scheme, separator, supplied = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not supplied:
            return False
        return hmac.compare_digest(self._token, supplied)

    def _require_token(self) -> str:
        if not self._token:
            raise RuntimeError("API token 尚未初始化")
        return self._token

    def make_photo_signature(self, item_id: int, version: str, expires: int) -> str:
        payload = f"{item_id}:{version}:{expires}".encode("utf-8")
        return hmac.new(
            self._require_token().encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

    def signed_photo_params(self, item_id: int, version: str) -> tuple[int, str]:
        expires = int(time.time()) + self.photo_url_ttl_seconds
        return expires, self.make_photo_signature(item_id, version, expires)

    def verify_photo_signature(
        self,
        item_id: int,
        version: str,
        expires: int,
        signature: str,
    ) -> None:
        now = int(time.time())
        if expires < now:
            raise DomainError(403, "photo_url_expired", "照片链接已过期")
        if expires > now + self.photo_url_ttl_seconds + 30:
            raise DomainError(403, "photo_url_invalid", "照片链接有效期无效")
        expected = self.make_photo_signature(item_id, version, expires)
        if not hmac.compare_digest(expected, signature):
            raise DomainError(403, "photo_url_invalid", "照片链接签名无效")
