# `stock_data.tools` — Maintenance CLI

## `build_membership_index`

Builds `stock_board_membership` reverse index by walking all boards per source.

### Usage

```bash
# Bootstrap all sources (serial within each source; ~30-45 min)
python -m stock_data.tools.build_membership_index

# Single source, faster iteration during dev
python -m stock_data.tools.build_membership_index --source=zhitu

# Single board_type within a source
python -m stock_data.tools.build_membership_index --source=eastmoney --type=concept

# Parallel within each source (4 workers per source; ~10-15 min for all sources)
python -m stock_data.tools.build_membership_index --max-workers-per-source=4

# Adjust rate limit (default 1.0-2.0s jitter)
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
- **Threading**: per-source `ThreadPoolExecutor(max_workers=N)`. Each worker thread opens its own SQLite connection (WAL mode allows concurrent writers). Default 1 (serial within source); 2-4 is acceptable; >4 risks upstream rate limits.
- **Cross-source is serial**: the CLI walks `eastmoney → zhitu → zzshare` sequentially. True cross-source parallelism would risk per-source rate-limit interference.
- After first bootstrap, membership data is kept fresh by forward-path lazy fill (`/boards/{code}/stocks` calls upsert). Long-tail boards never queried require `?refresh=true` or this CLI.
