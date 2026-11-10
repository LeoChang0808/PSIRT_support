"""Apply PostgreSQL schema migrations for the PSIRT reporting assistant."""
from __future__ import annotations

import os
import sys

from storage import apply_postgres_schema


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "upgrade":
        print("用法：python manage_db.py upgrade", file=sys.stderr)
        return 2
    database_url = os.environ.get("PSIRT_DATABASE_URL", "")
    try:
        version = apply_postgres_schema(database_url)
    except Exception as exc:
        print(f"資料庫升級失敗：{exc}", file=sys.stderr)
        return 1
    print(f"PostgreSQL schema 已升級至版本 {version}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
