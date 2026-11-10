"""PostgreSQL-backed encrypted case storage."""
from __future__ import annotations

import base64
import getpass
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

KEYCHAIN_SERVICE = "PSIRT-CRA-Local-Reporting-UI"
SCHEMA_VERSION = 1
SCHEMA_LOCK_ID = 731904261
_STORAGE_VERSION_KEY = "_storage_version"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_or_create_key() -> bytes:
    """Load the shared 256-bit payload key from Keychain or the environment."""
    configured = os.environ.get("PSIRT_ENCRYPTION_KEY", "")
    if sys.platform == "darwin" and Path("/usr/bin/security").exists():
        account = getpass.getuser()
        find = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", account, "-w"],
            capture_output=True, text=True, check=False,
        )
        if find.returncode == 0 and find.stdout.strip():
            try:
                key = base64.b64decode(find.stdout.strip(), validate=True)
            except ValueError as exc:
                raise RuntimeError("macOS Keychain 中的案件加密金鑰格式錯誤。") from exc
            if len(key) != 32:
                raise RuntimeError("macOS Keychain 中的案件加密金鑰長度錯誤。")
            return key

        if configured:
            try:
                key = base64.b64decode(configured, validate=True)
            except ValueError as exc:
                raise RuntimeError("PSIRT_ENCRYPTION_KEY 必須是 Base64 格式的 32-byte 金鑰。") from exc
            if len(key) != 32:
                raise RuntimeError("PSIRT_ENCRYPTION_KEY 解碼後必須為 32 bytes。")
            return key

        key = secrets.token_bytes(32)
        encoded = base64.b64encode(key).decode("ascii")
        add = subprocess.run(
            ["/usr/bin/security", "add-generic-password", "-U", "-s",
             KEYCHAIN_SERVICE, "-a", account, "-w", encoded],
            capture_output=True, text=True, check=False,
        )
        if add.returncode != 0:
            raise RuntimeError(
                "無法在 macOS Keychain 建立案件加密金鑰。請確認登入 Keychain 已解鎖，"
                "或設定由秘密管理服務保管的 PSIRT_ENCRYPTION_KEY。"
            )
        return key

    if configured:
        try:
            key = base64.b64decode(configured, validate=True)
        except ValueError as exc:
            raise RuntimeError("PSIRT_ENCRYPTION_KEY 必須是 Base64 格式的 32-byte 金鑰。") from exc
        if len(key) != 32:
            raise RuntimeError("PSIRT_ENCRYPTION_KEY 解碼後必須為 32 bytes。")
        return key
    raise RuntimeError(
        "請設定 PSIRT_ENCRYPTION_KEY（Base64 編碼的 32-byte 金鑰），"
        "並由作業系統或公司核准的秘密管理服務保管。"
    )


class StoreConflictError(RuntimeError):
    """Raised when a browser submits a case revision that is no longer current."""


def apply_postgres_schema(conninfo: str) -> int:
    """Apply the initial schema migration under an advisory transaction lock."""
    if not conninfo.strip():
        raise RuntimeError("請設定 PSIRT_DATABASE_URL。")
    pool = ConnectionPool(
        conninfo=conninfo,
        min_size=1,
        max_size=1,
        timeout=10,
        kwargs={"row_factory": dict_row},
        open=True,
    )
    try:
        with pool.connection() as conn:
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK_ID,))
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )"""
                )
                row = conn.execute(
                    "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
                ).fetchone()
                current_version = int(row["version"]) if row else 0
                if current_version > SCHEMA_VERSION:
                    raise RuntimeError(
                        f"資料庫版本 {current_version} 比此程式新；請使用相容版本。"
                    )
                if current_version == 0:
                    conn.execute(
                        """CREATE TABLE cases (
                            case_id TEXT PRIMARY KEY,
                            created_at TIMESTAMPTZ NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL,
                            nonce BYTEA NOT NULL CHECK (octet_length(nonce) = 12),
                            encrypted_payload BYTEA NOT NULL,
                            version BIGINT NOT NULL DEFAULT 1 CHECK (version >= 1)
                        )"""
                    )
                    conn.execute(
                        "CREATE INDEX cases_updated_at_idx ON cases (updated_at DESC)"
                    )
                    conn.execute(
                        """CREATE TABLE case_number_sequences (
                            year INTEGER PRIMARY KEY CHECK (year BETWEEN 1000 AND 9999),
                            last_number INTEGER NOT NULL CHECK (last_number BETWEEN 0 AND 9999)
                        )"""
                    )
                    conn.execute(
                        "INSERT INTO schema_migrations(version) VALUES (%s)",
                        (SCHEMA_VERSION,),
                    )
                    current_version = SCHEMA_VERSION
                if current_version != SCHEMA_VERSION:
                    raise RuntimeError(
                        f"資料庫版本為 {current_version}，程式需要版本 {SCHEMA_VERSION}；"
                        "請先執行資料庫升級程序。"
                    )
        return current_version
    finally:
        pool.close()


class PostgresCaseStore:
    """Store encrypted case payloads in PostgreSQL with optimistic locking."""

    def __init__(
        self,
        conninfo: str,
        key: bytes | None = None,
        pool_size: int = 5,
    ):
        if not conninfo.strip():
            raise RuntimeError("請設定 PSIRT_DATABASE_URL。")
        if pool_size < 1:
            raise ValueError("資料庫連線池大小必須至少為 1。")
        self._key = key if key is not None else _load_or_create_key()
        if len(self._key) != 32:
            raise ValueError("案件加密金鑰必須是 32 bytes。")
        self._cipher = AESGCM(self._key)
        self._pool = ConnectionPool(
            conninfo=conninfo,
            min_size=1,
            max_size=pool_size,
            timeout=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
                ).fetchone()
            if row is None or int(row["version"]) != SCHEMA_VERSION:
                raise RuntimeError(
                    f"PostgreSQL schema 尚未升級至版本 {SCHEMA_VERSION}；"
                    "請先執行 python manage_db.py upgrade。"
                )
        except RuntimeError:
            self._pool.close()
            raise
        except Exception as exc:
            self._pool.close()
            raise RuntimeError(
                "無法驗證 PostgreSQL schema；請確認資料庫已執行 python manage_db.py upgrade，"
                "且應用程式帳號具有必要讀取權限。"
            ) from exc

    def ping(self) -> bool:
        with self._pool.connection() as conn:
            return conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1

    def close(self) -> None:
        self._pool.close()

    def save(self, payload: dict[str, Any]) -> int:
        case_id = str(payload["id"])
        expected_version = payload.get(_STORAGE_VERSION_KEY)
        nonce = secrets.token_bytes(12)
        stored_payload = {
            key: value for key, value in payload.items() if key != _STORAGE_VERSION_KEY
        }
        plaintext = json.dumps(
            stored_payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        ciphertext = self._cipher.encrypt(nonce, plaintext, case_id.encode("utf-8"))
        now = _now()

        with self._pool.connection() as conn:
            if expected_version is None:
                row = conn.execute(
                    """INSERT INTO cases(
                           case_id, created_at, updated_at, nonce, encrypted_payload, version
                       ) VALUES (%s, %s, %s, %s, %s, 1)
                       ON CONFLICT (case_id) DO NOTHING
                       RETURNING version""",
                    (case_id, now, now, nonce, ciphertext),
                ).fetchone()
            else:
                try:
                    expected_version = int(expected_version)
                except (TypeError, ValueError) as exc:
                    raise StoreConflictError("案件版本資訊無效，請重新載入案件。") from exc
                row = conn.execute(
                    """UPDATE cases
                       SET updated_at = %s, nonce = %s, encrypted_payload = %s,
                           version = version + 1
                       WHERE case_id = %s AND version = %s
                       RETURNING version""",
                    (now, nonce, ciphertext, case_id, expected_version),
                ).fetchone()
            if row is None:
                raise StoreConflictError(
                    "此案件在您開啟後已被其他工作階段更新或刪除。"
                    "請先複製尚未保存的內容，再重新載入最新案件。"
                )
            new_version = int(row["version"])

        payload[_STORAGE_VERSION_KEY] = new_version
        return new_version

    def next_case_number(self, year: int) -> str:
        year_number = int(year)
        if not 1000 <= year_number <= 9999:
            raise ValueError("案件編號年份必須介於 1000 至 9999。")
        with self._pool.connection() as conn:
            row = conn.execute(
                """INSERT INTO case_number_sequences(year, last_number)
                   VALUES (%s, 1)
                   ON CONFLICT (year) DO UPDATE
                   SET last_number = case_number_sequences.last_number + 1
                   WHERE case_number_sequences.last_number < 9999
                   RETURNING last_number""",
                (year_number,),
            ).fetchone()
        if row is None:
            raise ValueError(f"{year_number} 年的 CRA 案件編號已達 9999，無法再自動產生。")
        return f"CRA-{year_number:04d}-{int(row['last_number']):04d}"

    def _decode_row(self, row: dict[str, Any]) -> dict[str, Any]:
        case_id = str(row["case_id"])
        try:
            plaintext = self._cipher.decrypt(
                bytes(row["nonce"]), bytes(row["encrypted_payload"]), case_id.encode("utf-8")
            )
            payload = json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(
                f"案件 {case_id} 無法解密；請確認 PSIRT_ENCRYPTION_KEY 未被變更。"
            ) from exc
        if not isinstance(payload, dict) or str(payload.get("id", "")) != case_id:
            raise RuntimeError(f"案件 {case_id} 的資料格式或識別碼無效。")
        payload[_STORAGE_VERSION_KEY] = int(row["version"])
        return payload

    def get(self, case_id: str) -> dict[str, Any] | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """SELECT case_id, nonce, encrypted_payload, version
                   FROM cases WHERE case_id = %s""",
                (case_id,),
            ).fetchone()
        return self._decode_row(row) if row is not None else None

    def list(self) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """SELECT case_id, nonce, encrypted_payload, version
                   FROM cases ORDER BY updated_at DESC"""
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def delete_many(self, case_ids: list[str]) -> int:
        identifiers = list(dict.fromkeys(str(case_id) for case_id in case_ids if case_id))
        if not identifiers:
            return 0
        with self._pool.connection() as conn:
            cursor = conn.execute("DELETE FROM cases WHERE case_id = ANY(%s)", (identifiers,))
            return cursor.rowcount

    def delete(self, case_id: str) -> bool:
        return self.delete_many([case_id]) > 0
