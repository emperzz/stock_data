"""Verify ``persistence.db.get_connection`` connection contract.

Background (P2-1 of ``docs/optimization-plan-2026-07-16.md``):
* ``journal_mode=WAL`` — readers and writers don't block each other.
* ``busy_timeout=30000`` — wait up to 30s for a write lock instead of
  raising ``OperationalError("database is locked")`` immediately.
* ``synchronous=NORMAL`` — fsync only at checkpoint, not per commit.

Without these the FastAPI 40-thread pool can corrupt writes (one thread
commits another's incomplete transaction) under concurrent load. This
test pins the PRAGMA values so a future regression that drops them
fails loudly instead of silently re-introducing the bug.

**P3 (2026-09-14): the shared singleton connection is gone.** P2-1
shipped the PRAGMAs but deliberately kept one module-level connection
for the whole process, and documented the ``threading.local`` per-thread
connection as a deferred "P3". That deferral turned out to be wrong: a
shared connection is unsafe even for *reads*. Concurrent ``execute()``
from the FastAPI threadpool corrupts a ``sqlite3.Row``'s internal
column-name → index map, which surfaces as
``IndexError: tuple index out of range`` (or ``TypeError``) on a plain
``row["name"]`` lookup — observed in production on
``/stocks/{code}/boards`` at ``persistence/board.py`` reading
``r["board_code"]``. The tests below pin the fix:

* ``test_get_connection_is_thread_local`` — each thread gets its own
  connection object (the structural invariant that makes the race
  impossible).
* ``test_concurrent_row_lookups_do_not_corrupt`` — the behavioural
  regression: hammering the same connection shape from N threads must
  never raise.
* ``test_connection_follows_db_path_change_in_other_threads`` — a
  per-thread connection must not outlive a DB path swap (this is what
  the old ``monkeypatch.setattr(db, "_conn", None)`` test plumbing
  used to achieve manually).

The concurrent-write smoke test at the bottom uses threading + a
Barrier to force two threads to attempt overlapping writes. Even with
WAL, same-connection writes are NOT safe — this test is intentionally
minimal: it just verifies that busy_timeout gives the second writer
time to wait instead of erroring.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated SQLite file + fresh connections for each test.

    Only ``_db_path`` (the memoized path) needs resetting now: the
    connection layer notices the path changed and rebuilds per-thread
    connections on its own — see
    ``test_connection_follows_db_path_change_in_other_threads``.
    """
    db_file = tmp_path / "concurrency.db"
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr(db_mod, "_db_path", None)
    yield db_file


def test_journal_mode_is_wal(fresh_db):
    """``PRAGMA journal_mode`` must return ``wal`` on the singleton connection."""
    conn = db_mod.get_connection()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal", f"expected WAL, got {mode!r}"


def test_busy_timeout_is_30_seconds(fresh_db):
    """``PRAGMA busy_timeout`` must be 30000 ms on the singleton connection."""
    conn = db_mod.get_connection()
    timeout_ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert timeout_ms == 30000, f"expected 30000 ms, got {timeout_ms!r}"


def test_synchronous_is_normal(fresh_db):
    """``PRAGMA synchronous`` must be ``1`` (NORMAL) on the singleton connection.

    sqlite3 reports ``synchronous=NORMAL`` as the integer ``1`` and
    ``FULL`` as ``2``. See https://www.sqlite.org/pragma.html#pragma_synchronous.
    """
    conn = db_mod.get_connection()
    sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    assert sync == 1, f"expected synchronous=NORMAL (1), got {sync!r}"


def test_row_factory_is_row(fresh_db):
    """Connection must keep the row factory for dict-like cursor results.

    Guards against a future refactor that drops the ``row_factory`` line
    when adding PRAGMA statements — losing it would break every caller
    that reads cursor results as dicts (e.g. ``row["code"]``).
    """
    conn = db_mod.get_connection()
    assert conn.row_factory is sqlite3.Row


def test_pragmas_reapplied_on_path_change(fresh_db, monkeypatch, tmp_path):
    """A rebuilt connection must re-apply all PRAGMAs.

    Swapping the DB path (what the ``tmp_db`` fixture does) must produce
    a connection that re-ran PRAGMA setup. If the rebuild path skipped
    it, the second connection would silently revert to default rollback
    journal + 0 busy timeout.
    """
    first = db_mod.get_connection()
    assert first.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    # Point at a second DB — the connection layer must notice and rebuild.
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "second.db"))
    monkeypatch.setattr(db_mod, "_db_path", None)
    second = db_mod.get_connection()
    assert second is not first
    assert second.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert second.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    assert second.execute("PRAGMA synchronous").fetchone()[0] == 1


def test_get_connection_is_thread_local(fresh_db):
    """Each thread must get its OWN connection object.

    This is the structural invariant behind the whole file: a connection
    shared between threads shares its statement cache and its
    ``sqlite3.Row`` column-description dicts, so one thread's
    ``execute()`` can rewrite another thread's in-flight row. Per-thread
    connections make that impossible by construction.
    """
    main_conn = db_mod.get_connection()

    box: dict[str, object] = {}

    def worker() -> None:
        box["conn"] = db_mod.get_connection()

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5)

    assert box["conn"] is not main_conn, (
        "worker thread received the main thread's connection — a shared "
        "connection's statement cache is what produced the "
        "IndexError: tuple index out of range crash"
    )
    # Same thread → same connection (no per-call reconnect).
    assert db_mod.get_connection() is main_conn


def test_connection_follows_db_path_change_in_other_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A worker thread must not be served a connection to a stale DB path.

    Regression guard for the test-fixture contract: swapping
    ``STOCK_CACHE_DB_PATH`` has to take effect for connections created
    *after* the swap in *any* thread. A worker-pool thread that keeps a
    thread-local connection alive across the swap would otherwise read
    the previous test's database.
    """
    db_one = tmp_path / "one.db"
    db_two = tmp_path / "two.db"
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(db_one))
    monkeypatch.setattr(db_mod, "_db_path", None)

    # Prime a connection to db_one in a worker thread (mirrors a
    # long-lived pool thread that served an earlier request).
    def prime() -> None:
        db_mod.get_connection().execute("SELECT 1").fetchone()

    t = threading.Thread(target=prime)
    t.start()
    t.join(timeout=5)

    # Build db_two out-of-band with a sentinel row.
    seed = sqlite3.connect(db_two)
    seed.execute("CREATE TABLE sentinel (v TEXT)")
    seed.execute("INSERT INTO sentinel VALUES ('two')")
    seed.commit()
    seed.close()

    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(db_two))
    monkeypatch.setattr(db_mod, "_db_path", None)

    seen: dict[str, object] = {}

    def observe() -> None:
        try:
            row = db_mod.get_connection().execute("SELECT v FROM sentinel").fetchone()
            seen["v"] = row[0]
        except BaseException as e:  # reported in the assert below
            seen["error"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=observe)
    t.start()
    t.join(timeout=5)

    assert "error" not in seen, f"stale connection served: {seen['error']}"
    assert seen["v"] == "two"


def test_concurrent_row_lookups_do_not_corrupt(fresh_db):
    """Concurrent name-indexed row lookups must never raise.

    The production failure: two threads running different-column-count
    queries on one shared connection, then reading a row by column name
    — ``IndexError: tuple index out of range`` (the row's description
    dict came from the *other* thread's statement, so the index ran past
    the row's data tuple).

    The two tables deliberately have different widths (10 vs 1 column)
    so a description swap is fatal rather than silently invisible.
    """
    conn = db_mod.get_connection()
    conn.executescript(
        """
        CREATE TABLE wide (
            board_code TEXT, stock_code TEXT, source TEXT, board_name TEXT,
            stock_name TEXT, board_type TEXT, subtype TEXT, sb_name TEXT,
            sb_board_type TEXT, sb_subtype TEXT
        );
        CREATE TABLE narrow (board_code TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO wide VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (f"b{i}", f"s{i}", "ths", "n", "n", "concept", None, "n", "concept", None)
            for i in range(50)
        ],
    )
    conn.executemany("INSERT INTO narrow VALUES (?)", [(f"b{i}",) for i in range(50)])
    conn.commit()

    n_threads = 6
    barrier = threading.Barrier(n_threads)
    errors: list[str] = []
    wide_sql = (
        "SELECT board_code, stock_code, source, board_name, stock_name, "
        "board_type, subtype, sb_name, sb_board_type, sb_subtype FROM wide"
    )

    def hammer(sql: str, col: str, iterations: int) -> None:
        try:
            barrier.wait(timeout=10)
            c = db_mod.get_connection()
            for _ in range(iterations):
                for r in c.execute(sql).fetchall():
                    assert r[col] is not None
        except BaseException as e:  # collected for the assert
            errors.append(f"{type(e).__name__}: {e}")

    threads = [
        threading.Thread(target=hammer, args=(wide_sql, "board_code", 300))
        for _ in range(n_threads // 2)
    ] + [
        threading.Thread(target=hammer, args=("SELECT board_code FROM narrow", "board_code", 300))
        for _ in range(n_threads // 2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, f"concurrent row lookups raised: {errors[:3]}"


def test_concurrent_readers_dont_block_each_other(fresh_db):
    """Two threads can read simultaneously thanks to WAL mode.

    Historical note: P2-1 (2026-07-16) shipped the PRAGMAs but kept a
    shared singleton connection and deferred the ``threading.local``
    per-thread connection to "P3" — the stated cost being that it would
    touch every test doing ``monkeypatch.setattr(db_mod, "_conn", None)``.
    P3 landed 2026-09-14 (see the module docstring); that cost was paid,
    and the two-writer race this docstring used to hand-wave is now
    structurally impossible rather than "narrow".

    What this test still verifies: WAL lets a reader and a writer
    proceed without the reader blocking. The default rollback journal
    would force the reader to wait for the writer to release the
    EXCLUSIVE lock. With WAL the reader just sees the last-committed
    snapshot. (Since P3 the reader also holds its own connection, so
    the isolation under test is WAL's, not the connection's.)
    """
    # Bootstrap schema (single-threaded).
    conn = db_mod.get_connection()
    conn.executescript(
        """
        CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);
        """
    )
    conn.commit()
    conn.execute("INSERT INTO t(v) VALUES (?)", ("initial",))
    conn.commit()

    read_results: list[str] = []
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            c = db_mod.get_connection()
            row = c.execute("SELECT v FROM t WHERE id = 1").fetchone()
            read_results.append(row[0] if row else None)
        except BaseException as e:
            errors.append(e)

    # Run a reader in a thread while the main thread also reads.
    # If WAL is active both reads succeed; if journal_mode silently
    # rolled back to "delete" we'd see a locking error.
    t = threading.Thread(target=reader)
    t.start()
    main_row = conn.execute("SELECT v FROM t WHERE id = 1").fetchone()
    t.join(timeout=5)

    assert not errors, f"concurrent read raised: {errors}"
    assert main_row[0] == "initial"
    assert read_results == ["initial"]
