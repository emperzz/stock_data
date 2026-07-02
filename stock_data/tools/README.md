# `stock_data.tools` — Maintenance CLI

## `build_membership_index`

Builds `stock_board_membership` reverse index by walking all boards per source.

### Usage

```bash
# Bootstrap all sources (cross-source parallel; serial within each source; ~15-25 min)
python -m stock_data.tools.build_membership_index

# Single source, faster iteration during dev
python -m stock_data.tools.build_membership_index --source=zhitu

# Single board_type within a source
python -m stock_data.tools.build_membership_index --source=eastmoney --type=concept

# Adjust rate limit (default 1.0-3.0s jitter)
python -m stock_data.tools.build_membership_index --inter-call-sleep-min 0.5 --inter-call-sleep-max 1.0

# Verbose logging
python -m stock_data.tools.build_membership_index -v
```

### Exit codes

- `0`: All boards succeeded across all sources
- `1`: At least one board failed (per-source breakdown printed)

### Notes

- **Returns `list[BuildReport]`** — one report per source walked.
- **Idempotent**: re-running upserts existing rows. `refreshed_at` is updated.
- **Threading**: cross-source parallel — each source runs on its own worker thread (3 sources → 3 threads). Intra-source fetching is serial (one board at a time per source) because opening concurrent threads against the same upstream just hits its rate limit harder.
- **SQLite**: each worker thread opens its own SQLite connection (WAL mode allows concurrent writers across sources; the connection's own mutex serializes within a thread).
- After first bootstrap, membership data is kept fresh by forward-path lazy fill (`/boards/{code}/stocks` calls upsert). Long-tail boards never queried require `?refresh=true` or this CLI.
