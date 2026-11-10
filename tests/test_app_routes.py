"""Offline Flask route checks using a version-aware in-memory store."""
from __future__ import annotations

import copy
import os
import re
import threading
import unittest
from urllib.parse import urlparse
from unittest.mock import patch

os.environ["PSIRT_DATABASE_URL"] = "postgresql://route-test.invalid/psirt_test"
os.environ["PSIRT_SESSION_SECRET"] = "route-test-session-secret-at-least-32-bytes"

import storage


class MemoryCaseStore:
    """Small adapter for exercising HTTP behavior without a running PostgreSQL."""

    def __init__(self, *_args, **_kwargs):
        self._cases: dict[str, dict] = {}
        self._numbers: dict[int, int] = {}
        self._lock = threading.RLock()
        self.available = True

    def reset(self) -> None:
        with self._lock:
            self._cases.clear()
            self._numbers.clear()
            self.available = True

    def next_case_number(self, year: int) -> str:
        with self._lock:
            self._numbers[year] = self._numbers.get(year, 0) + 1
            return f"CRA-{year:04d}-{self._numbers[year]:04d}"

    def save(self, payload: dict) -> int:
        case_id = str(payload["id"])
        expected = payload.get("_storage_version")
        with self._lock:
            current = self._cases.get(case_id)
            if expected is None:
                if current is not None:
                    raise storage.StoreConflictError("case already exists")
                version = 1
            else:
                if current is None or int(expected) != current["_storage_version"]:
                    raise storage.StoreConflictError("stale case version")
                version = current["_storage_version"] + 1
            stored = copy.deepcopy(payload)
            stored["_storage_version"] = version
            self._cases[case_id] = stored
            payload["_storage_version"] = version
            return version

    def get(self, case_id: str) -> dict | None:
        with self._lock:
            case = self._cases.get(case_id)
            return copy.deepcopy(case) if case is not None else None

    def list(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(list(self._cases.values()))

    def delete_many(self, case_ids: list[str]) -> int:
        with self._lock:
            deleted = 0
            for case_id in set(case_ids):
                if self._cases.pop(case_id, None) is not None:
                    deleted += 1
            return deleted

    def delete(self, case_id: str) -> bool:
        return self.delete_many([case_id]) > 0

    def ping(self) -> bool:
        if not self.available:
            raise RuntimeError("database unavailable")
        return True


with patch.object(storage, "PostgresCaseStore", MemoryCaseStore):
    import app as app_module


class AppRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app_module.app.config.update(TESTING=True)

    def setUp(self) -> None:
        app_module.STORE.reset()
        self.client = app_module.app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.csrf = session["csrf_token"]

    def _create_case(self) -> tuple[str, int]:
        response = self.client.post("/cases", data={"csrf_token": self.csrf})
        self.assertEqual(response.status_code, 302)
        match = re.search(r"/cases/([^/?]+)", urlparse(response.location).path)
        self.assertIsNotNone(match)
        case_id = match.group(1)
        self.assertEqual(app_module.STORE.get(case_id)["_storage_version"], 1)
        return case_id, 1

    def test_health_and_database_unavailable_status(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok", "database": "ok"})
        app_module.STORE.available = False
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["database"], "unavailable")

    def test_create_render_autosave_conflict_awareness_and_evidence(self) -> None:
        case_id, version = self._create_case()
        page = self.client.get(f"/cases/{case_id}?step=7.1")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'name="storage_version" value="1"', page.data)

        save = self.client.post(
            f"/api/cases/{case_id}/auto-save",
            headers={"X-CSRF-Token": self.csrf},
            json={
                "step": "7.1",
                "storage_version": version,
                "values": {"field__D2__13__entry": "Route test case title"},
            },
        )
        self.assertEqual(save.status_code, 200, save.json)
        version = save.json["storage_version"]
        stored = app_module.STORE.get(case_id)
        self.assertEqual(stored["forms"]["D2"]["13"]["entry"], "Route test case title")

        stale = self.client.post(
            f"/api/cases/{case_id}/auto-save",
            headers={"X-CSRF-Token": self.csrf},
            json={"step": "7.1", "storage_version": 1, "values": {}},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertTrue(stale.json["reload_required"])

        awareness = self.client.post(
            f"/api/cases/{case_id}/awareness",
            headers={"X-CSRF-Token": self.csrf},
            json={
                "storage_version": version,
                "awareness_local": "2026-11-10T09:30",
                "awareness_timezone": "Asia/Taipei",
            },
        )
        self.assertEqual(awareness.status_code, 200, awareness.json)
        self.assertEqual(awareness.json["deadlines"]["24"], "2026-11-11T09:30:00+08:00")
        version = awareness.json["storage_version"]

        evidence = self.client.post(
            f"/api/cases/{case_id}/evidence",
            headers={"X-CSRF-Token": self.csrf},
            json={
                "storage_version": version,
                "step": "7.1",
                "field_name": "field__D2__13__evidence_id",
                "evidence_id": "EV-ROUTE-001",
                "kind": "log",
                "description": "route test evidence",
            },
        )
        self.assertEqual(evidence.status_code, 200, evidence.json)
        self.assertEqual(evidence.json["evidence"]["evidence_id"], "EV-ROUTE-001")
        duplicate = self.client.post(
            f"/api/cases/{case_id}/evidence",
            headers={"X-CSRF-Token": self.csrf},
            json={
                "storage_version": evidence.json["storage_version"],
                "step": "7.1",
                "field_name": "field__D2__13__evidence_id",
                "evidence_id": "EV-ROUTE-001",
            },
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_form_submission_trash_and_permanent_delete(self) -> None:
        case_id, version = self._create_case()
        saved = self.client.post(
            f"/cases/{case_id}/step/7.1",
            data={
                "csrf_token": self.csrf,
                "storage_version": version,
                "intent": "complete",
                "field__D2__13__entry": "Form submit title",
            },
        )
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(app_module.STORE.get(case_id)["steps"]["7.1"], "completed")

        trashed = self.client.post(
            f"/cases/{case_id}/trash", data={"csrf_token": self.csrf}
        )
        self.assertEqual(trashed.status_code, 302)
        self.assertIsNotNone(app_module.STORE.get(case_id).get("trashed_at"))
        deleted = self.client.post(
            f"/trash/{case_id}/delete", data={"csrf_token": self.csrf}
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertIsNone(app_module.STORE.get(case_id))

    def test_each_workbook_pdf_and_bundle_exports(self) -> None:
        case_id, _version = self._create_case()
        for code in ("D1", "D2", "D3", "D4", "D5", "D6", "D7"):
            with self.subTest(code=code):
                response = self.client.get(f"/cases/{case_id}/export/{code}.xlsx")
                self.assertEqual(response.status_code, 200, response.data[:200])
                self.assertEqual(
                    response.mimetype,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
        report = self.client.get(f"/cases/{case_id}/report.pdf")
        self.assertEqual(report.status_code, 200, report.data[:200])
        self.assertEqual(report.mimetype, "application/pdf")
        bundle = self.client.get(f"/cases/{case_id}/export/all.zip")
        self.assertEqual(bundle.status_code, 200, bundle.data[:200])
        self.assertEqual(bundle.mimetype, "application/zip")


if __name__ == "__main__":
    unittest.main()
