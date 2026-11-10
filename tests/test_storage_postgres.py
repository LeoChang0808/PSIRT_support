"""PostgreSQL integration checks; use a dedicated database ending in ``_test``."""
from __future__ import annotations

import os
import secrets
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

TEST_DATABASE_URL = os.environ.get("PSIRT_TEST_DATABASE_URL", "")


@unittest.skipUnless(TEST_DATABASE_URL, "set PSIRT_TEST_DATABASE_URL to a dedicated *_test database")
class PostgresCaseStoreIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import psycopg
        from psycopg import sql
        from storage import PostgresCaseStore, apply_postgres_schema

        database_name = psycopg.conninfo.conninfo_to_dict(TEST_DATABASE_URL).get("dbname", "")
        if not database_name.endswith("_test"):
            raise RuntimeError("Refusing database integration tests unless the database name ends in _test.")

        cls._schema = f"psirt_test_{uuid.uuid4().hex}"
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls._schema)))
        cls._test_url = psycopg.conninfo.make_conninfo(
            TEST_DATABASE_URL,
            options=f"-c search_path={cls._schema}",
        )
        apply_postgres_schema(cls._test_url)
        cls.store = PostgresCaseStore(
            cls._test_url,
            key=secrets.token_bytes(32),
            pool_size=8,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        if not hasattr(cls, "_schema"):
            return
        import psycopg
        from psycopg import sql

        cls.store.close()
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls._schema)))

    def _new_case(self, case_id: str | None = None) -> dict[str, object]:
        return {
            "id": case_id or f"test-{uuid.uuid4().hex}",
            "case_number": "CRA-2098-0001",
            "title": "confidential marker " + uuid.uuid4().hex,
            "forms": {"D2": {"13": {"entry": "test payload"}}},
        }

    def test_schema_upgrade_is_repeatable_and_health_check_works(self) -> None:
        from storage import apply_postgres_schema

        self.assertEqual(apply_postgres_schema(self._test_url), 1)
        self.assertTrue(self.store.ping())

    def test_save_encrypt_read_and_reject_stale_revision(self) -> None:
        from storage import StoreConflictError

        case = self._new_case()
        self.assertEqual(self.store.save(case), 1)
        case_id = str(case["id"])
        saved = self.store.get(case_id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["title"], case["title"])
        self.assertEqual(saved["_storage_version"], 1)

        with self.store._pool.connection() as conn:
            row = conn.execute(
                "SELECT encrypted_payload FROM cases WHERE case_id = %s", (case_id,)
            ).fetchone()
        self.assertNotIn(str(case["title"]).encode("utf-8"), bytes(row["encrypted_payload"]))

        stale = self.store.get(case_id)
        current = self.store.get(case_id)
        current["title"] = "updated"
        self.assertEqual(self.store.save(current), 2)
        stale["title"] = "stale update"
        with self.assertRaises(StoreConflictError):
            self.store.save(stale)
        self.assertEqual(self.store.get(case_id)["title"], "updated")

    def test_case_numbers_are_unique_under_concurrent_allocation(self) -> None:
        with ThreadPoolExecutor(max_workers=8) as executor:
            numbers = list(executor.map(lambda _: self.store.next_case_number(2097), range(32)))
        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertEqual(set(numbers), {f"CRA-2097-{number:04d}" for number in range(1, 33)})

    def test_list_and_delete_operations(self) -> None:
        first = self._new_case()
        second = self._new_case()
        self.store.save(first)
        self.store.save(second)
        listed_ids = {case["id"] for case in self.store.list()}
        self.assertIn(first["id"], listed_ids)
        self.assertIn(second["id"], listed_ids)
        self.assertEqual(self.store.delete_many([str(first["id"]), str(second["id"]), str(first["id"])]), 2)
        self.assertIsNone(self.store.get(str(first["id"])))
        self.assertFalse(self.store.delete(str(second["id"])))


if __name__ == "__main__":
    unittest.main()
