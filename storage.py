"""Encrypted local case storage.

SQLite stores only opaque identifiers and timestamps in clear text. Case
payloads are encrypted with AES-GCM; the key is kept in macOS Keychain.
"""
from __future__ import annotations

import base64
import getpass
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEYCHAIN_SERVICE = "PSIRT-CRA-Local-Reporting-UI"
DATABASE_MAGIC = b"PSIRTDB1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_or_create_key() -> bytes:
    """Load a 256-bit key from Keychain; require an explicit key elsewhere."""
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
                "並檢查「安全性與隱私權」設定。"
            )
        return key

    configured = os.environ.get("PSIRT_ENCRYPTION_KEY", "")
    if configured:
        try:
            key = base64.b64decode(configured, validate=True)
        except ValueError as exc:
            raise RuntimeError("PSIRT_ENCRYPTION_KEY 必須是 Base64 格式的 32-byte 金鑰。") from exc
        if len(key) != 32:
            raise RuntimeError("PSIRT_ENCRYPTION_KEY 解碼後必須為 32 bytes。")
        return key
    raise RuntimeError(
        "此平台沒有 macOS Keychain。請先設定 PSIRT_ENCRYPTION_KEY（Base64 編碼的 32-byte 金鑰），"
        "再啟動服務；系統不會以明文保存案件資料。"
    )


class EncryptedCaseStore:
    def __init__(self, database_path: Path, key: bytes | None = None):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.database_path.parent, 0o700)
        except OSError:
            pass
        self._key = key or _load_or_create_key()
        self._cipher = AESGCM(self._key)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=MEMORY")
        self._db.execute("PRAGMA secure_delete=ON")
        self._initialize()

    def _initialize(self) -> None:
        if self.database_path.exists():
            envelope = self.database_path.read_bytes()
            if not envelope.startswith(DATABASE_MAGIC) or len(envelope) < len(DATABASE_MAGIC) + 12 + 16:
                raise RuntimeError("案件資料庫加密檔格式無效；請勿覆寫原始資料。")
            nonce_start = len(DATABASE_MAGIC)
            nonce = envelope[nonce_start:nonce_start + 12]
            ciphertext = envelope[nonce_start + 12:]
            try:
                image = self._cipher.decrypt(nonce, ciphertext, DATABASE_MAGIC)
                self._db.deserialize(image)
            except Exception as exc:
                raise RuntimeError(
                    "案件資料庫無法解密。請確認 Keychain 金鑰未被重設，也不要覆寫原始檔。"
                ) from exc
        self._db.execute(
                """CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    nonce BLOB NOT NULL,
                    encrypted_payload BLOB NOT NULL
                )"""
            )
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS app_meta (
                meta_key TEXT PRIMARY KEY,
                meta_value TEXT NOT NULL
            )"""
        )

        if not self.database_path.exists():
            self._persist()

    def _persist(self) -> None:
        image = self._db.serialize()
        nonce = secrets.token_bytes(12)
        ciphertext = self._cipher.encrypt(nonce, image, DATABASE_MAGIC)
        envelope = DATABASE_MAGIC + nonce + ciphertext
        temporary = self.database_path.with_name(self.database_path.name + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(envelope)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.database_path)
            os.chmod(self.database_path, 0o600)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def save(self, payload: dict[str, Any]) -> None:
        case_id = str(payload["id"])
        now = _now()
        nonce = secrets.token_bytes(12)
        plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ciphertext = self._cipher.encrypt(nonce, plaintext, case_id.encode("utf-8"))
        with self._lock:
            with self._db:
                db = self._db
                previous = db.execute(
                    "SELECT created_at FROM cases WHERE case_id=?", (case_id,)
                ).fetchone()
                created_at = previous["created_at"] if previous else now
                db.execute(
                    """INSERT INTO cases(case_id, created_at, updated_at, nonce, encrypted_payload)
                       VALUES(?, ?, ?, ?, ?)
                       ON CONFLICT(case_id) DO UPDATE SET
                         updated_at=excluded.updated_at,
                         nonce=excluded.nonce,
                         encrypted_payload=excluded.encrypted_payload""",
                    (case_id, created_at, now, nonce, ciphertext),
                )
            self._persist()

    def next_case_number(self, year: int) -> str:
        """Allocate a per-year CRA case number without reusing deleted numbers."""
        year_text = f"{int(year):04d}"
        meta_key = f"case-number-sequence:{year_text}"
        pattern = re.compile(rf"^CRA-{re.escape(year_text)}-(\d{{4}})$")
        with self._lock:
            row = self._db.execute(
                "SELECT meta_value FROM app_meta WHERE meta_key=?", (meta_key,)
            ).fetchone()
            last_number = int(row["meta_value"]) if row is not None else 0
            rows = self._db.execute(
                "SELECT case_id, nonce, encrypted_payload FROM cases"
            ).fetchall()
            for case_row in rows:
                try:
                    plaintext = self._cipher.decrypt(
                        case_row["nonce"], case_row["encrypted_payload"],
                        case_row["case_id"].encode("utf-8"),
                    )
                    payload = json.loads(plaintext.decode("utf-8"))
                except Exception as exc:
                    raise RuntimeError(
                        f"案件 {case_row['case_id']} 無法解密；請檢查 Keychain 金鑰。"
                    ) from exc
                match = pattern.fullmatch(str(payload.get("case_number", "")))
                if match:
                    last_number = max(last_number, int(match.group(1)))

            next_number = last_number + 1
            if next_number > 9999:
                raise ValueError(f"{year_text} 年的 CRA 案件編號已達 9999，無法再自動產生。")
            with self._db:
                self._db.execute(
                    """INSERT INTO app_meta(meta_key, meta_value) VALUES(?, ?)
                       ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value""",
                    (meta_key, str(next_number)),
                )
            self._persist()
            return f"CRA-{year_text}-{next_number:04d}"

    def get(self, case_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT nonce, encrypted_payload FROM cases WHERE case_id=?",
                (case_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            plaintext = self._cipher.decrypt(
                row["nonce"], row["encrypted_payload"], case_id.encode("utf-8")
            )
            payload = json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(
                "案件資料無法解密。請確認 Keychain 金鑰未被重設，也不要覆寫資料庫。"
            ) from exc
        return payload

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT case_id, nonce, encrypted_payload FROM cases ORDER BY updated_at DESC"
            ).fetchall()
        cases: list[dict[str, Any]] = []
        for row in rows:
            case_id = row["case_id"]
            try:
                plaintext = self._cipher.decrypt(
                    row["nonce"], row["encrypted_payload"], case_id.encode("utf-8")
                )
                cases.append(json.loads(plaintext.decode("utf-8")))
            except Exception as exc:
                raise RuntimeError(
                    f"案件 {case_id} 無法解密；請檢查 Keychain 金鑰。"
                ) from exc
        return cases

    def delete_many(self, case_ids: list[str]) -> int:
        """Permanently remove encrypted case records and persist the snapshot."""
        identifiers = list(dict.fromkeys(str(case_id) for case_id in case_ids if case_id))
        if not identifiers:
            return 0
        with self._lock:
            with self._db:
                before = self._db.total_changes
                self._db.executemany(
                    "DELETE FROM cases WHERE case_id=?",
                    ((case_id,) for case_id in identifiers),
                )
                deleted = self._db.total_changes - before
            if deleted:
                self._persist()
            return deleted

    def delete(self, case_id: str) -> bool:
        return self.delete_many([case_id]) > 0
