from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from .database import Database
from .errors import DomainError

logger = logging.getLogger("easystufffind.security")

DEFAULT_WEB_USERNAME = "admin"
DEFAULT_WEB_PASSWORD = "admin"
WEB_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
PASSWORD_SCRYPT_N = 2**14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=32,
    )
    return "$".join(
        [
            "scrypt",
            str(PASSWORD_SCRYPT_N),
            str(PASSWORD_SCRYPT_R),
            str(PASSWORD_SCRYPT_P),
            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(derived).decode("ascii").rstrip("="),
        ]
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n_value, r_value, p_value, salt_value, digest_value = encoded.split("$")
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_value + "=" * (-len(salt_value) % 4))
        expected = base64.urlsafe_b64decode(
            digest_value + "=" * (-len(digest_value) % 4)
        )
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_value),
            r=int(r_value),
            p=int(p_value),
            dklen=len(expected),
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


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

    @staticmethod
    def _encode_session_payload(payload: dict[str, object]) -> str:
        serialized = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return base64.urlsafe_b64encode(serialized).decode("ascii").rstrip("=")

    def create_web_session(
        self,
        username: str,
        auth_version: int,
        ttl_seconds: int = WEB_SESSION_TTL_SECONDS,
    ) -> str:
        now = int(time.time())
        encoded = self._encode_session_payload(
            {
                "username": username,
                "auth_version": auth_version,
                "issued_at": now,
                "expires_at": now + ttl_seconds,
            }
        )
        signature = hmac.new(
            self._require_token().encode("utf-8"),
            f"web-session:{encoded}".encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return f"{encoded}.{signature}"

    def verify_web_session(self, session: str | None) -> dict[str, object] | None:
        if not session:
            return None
        encoded, separator, supplied_signature = session.partition(".")
        if separator != "." or not encoded or len(supplied_signature) != 64:
            return None
        expected_signature = hmac.new(
            self._require_token().encode("utf-8"),
            f"web-session:{encoded}".encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, supplied_signature):
            return None
        try:
            raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            payload = json.loads(raw.decode("utf-8"))
            username = payload["username"]
            auth_version = payload["auth_version"]
            issued_at = payload["issued_at"]
            expires_at = payload["expires_at"]
            if (
                not isinstance(username, str)
                or not isinstance(auth_version, int)
                or not isinstance(issued_at, int)
                or not isinstance(expires_at, int)
            ):
                return None
            now = int(time.time())
            if issued_at > now + 30 or expires_at < now:
                return None
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return payload

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


class WebAuthManager:
    def __init__(self, database: Database, token_manager: TokenManager) -> None:
        self.database = database
        self.token_manager = token_manager

    @staticmethod
    def _public_account(row) -> dict[str, object]:
        return {
            "username": row["username"],
            "auth_version": int(row["auth_version"]),
            "password_changed": row["password_changed_at"] is not None,
        }

    def ensure_default_account(self) -> None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT id FROM web_accounts WHERE id = 1"
            ).fetchone()
            if row is not None:
                return
            now = utc_now()
            connection.execute(
                """
                INSERT INTO web_accounts (
                    id, username, password_hash, auth_version,
                    password_changed_at, created_at, updated_at
                ) VALUES (1, ?, ?, 1, NULL, ?, ?)
                """,
                (
                    DEFAULT_WEB_USERNAME,
                    hash_password(DEFAULT_WEB_PASSWORD),
                    now,
                    now,
                ),
            )
        logger.info("event=web_account_ready username=%s", DEFAULT_WEB_USERNAME)

    def authenticate(self, username: str, password: str) -> dict[str, object] | None:
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT username, password_hash, auth_version, password_changed_at
                FROM web_accounts WHERE username = ?
                """,
                (username,),
            ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        return self._public_account(row)

    def account_from_session(self, session: str | None) -> dict[str, object] | None:
        payload = self.token_manager.verify_web_session(session)
        if payload is None:
            return None
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT username, auth_version, password_changed_at
                FROM web_accounts WHERE username = ?
                """,
                (payload["username"],),
            ).fetchone()
        if row is None or int(row["auth_version"]) != payload["auth_version"]:
            return None
        return self._public_account(row)

    def create_session(self, account: dict[str, object]) -> str:
        return self.token_manager.create_web_session(
            str(account["username"]),
            int(account["auth_version"]),
        )

    def change_password(
        self,
        username: str,
        current_password: str,
        new_password: str,
    ) -> dict[str, object] | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT username, password_hash, auth_version, password_changed_at
                FROM web_accounts WHERE username = ?
                """,
                (username,),
            ).fetchone()
            if row is None or not verify_password(
                current_password,
                row["password_hash"],
            ):
                return None
            now = utc_now()
            connection.execute(
                """
                UPDATE web_accounts
                SET password_hash = ?,
                    auth_version = auth_version + 1,
                    password_changed_at = ?,
                    updated_at = ?
                WHERE username = ?
                """,
                (hash_password(new_password), now, now, username),
            )
            updated = connection.execute(
                """
                SELECT username, auth_version, password_changed_at
                FROM web_accounts WHERE username = ?
                """,
                (username,),
            ).fetchone()
        return self._public_account(updated)

    def verify_current_password(self, username: str, password: str) -> bool:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT password_hash FROM web_accounts WHERE username = ?",
                (username,),
            ).fetchone()
        return row is not None and verify_password(password, row["password_hash"])
