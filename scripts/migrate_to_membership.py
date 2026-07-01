"""Drop legacy `stock_board_stock` table after verifying no data divergence.

The migration `init_schema()` (Task 1) already copied legacy rows into
`stock_board_membership`. This script verifies that copy was complete,
then drops the legacy table.

Usage:
    python scripts/migrate_to_membership.py --dry-run   # Default. Print diff, no changes.
    python scripts/migrate_to_membership.py --execute   # Drop if diff is empty.
    python scripts/migrate_to_membership.py --execute --force  # Drop regardless.

Exit codes:
    0  -- Dry-run OK, OR execute succeeded (table dropped).
    1  -- Internal error (DB not found, etc.)
    2  -- Execute refused due to non-empty diff (use --force to override).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path


def get_db_path() -> Path:
    env_path = os.getenv("STOCK_CACHE_DB_PATH")
    if env_path:
        return Path(env_path)
    # Default matches persistence/db.py
    return Path(__file__).resolve().parent.parent / "stock_data" / "stock_cache.db"


def compute_diff(conn: sqlite3.Connection) -> dict:
    """Compute row counts and key diff between legacy and new tables.

    Returns dict with:
        legacy_count: int — rows in stock_board_stock
        new_count: int — rows in stock_board_membership
        only_in_legacy: int — rows in legacy whose (board_code, source, stock_code)
                              does not appear in membership
    """
    legacy_count = conn.execute(
        "SELECT COUNT(*) FROM stock_board_stock"
    ).fetchone()[0]
    new_count = conn.execute(
        "SELECT COUNT(*) FROM stock_board_membership"
    ).fetchone()[0]

    only_in_legacy = conn.execute("""
        SELECT COUNT(*) FROM stock_board_stock bs
        WHERE NOT EXISTS (
            SELECT 1 FROM stock_board_membership m
            WHERE m.board_code = bs.board_code
              AND m.source = bs.source
              AND m.stock_code = bs.stock_code
        )
    """).fetchone()[0]

    return {
        "legacy_count": legacy_count,
        "new_count": new_count,
        "only_in_legacy": only_in_legacy,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Print diff; do not drop. (default)")
    parser.add_argument("--execute", action="store_true",
                        help="Drop legacy table if diff is empty.")
    parser.add_argument("--force", action="store_true",
                        help="With --execute, drop even if diff is non-empty.")
    args = parser.parse_args(argv)

    # --execute without --dry-run makes the script "live"; otherwise default to dry-run.
    if args.execute:
        args.dry_run = False

    db_path = get_db_path()
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Sanity: legacy table exists?
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_board_stock'"
        ).fetchone()
        if not exists:
            print(f"Legacy table stock_board_stock does not exist; nothing to do.")
            return 0

        diff = compute_diff(conn)
        print(f"stock_board_stock (legacy): {diff['legacy_count']} rows")
        print(f"stock_board_membership (new): {diff['new_count']} rows")
        print(f"Diff (rows in legacy but not in new): {diff['only_in_legacy']}")

        if args.dry_run:
            print("\nDry-run; no changes made. Re-run with --execute to drop legacy table.")
            return 0

        # --execute path
        if diff["only_in_legacy"] > 0 and not args.force:
            print(
                f"\nRefusing to drop: diff is non-empty "
                f"({diff['only_in_legacy']} rows in legacy table have no counterpart "
                f"in new table). Investigate first, or use --force to drop anyway."
            )
            return 2

        print("\nDropping stock_board_stock ...")
        conn.execute("DROP TABLE stock_board_stock")
        conn.commit()
        print("Done.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
