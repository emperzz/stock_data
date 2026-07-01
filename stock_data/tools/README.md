# `stock_data.tools` — Maintenance CLI

## `build_membership_index`

Builds `stock_board_membership` reverse index by walking all boards per source.

### Usage

```bash
# Bootstrap all sources (~10-15 min on per-source workers, ~30-45 min serial)
python -m stock_data.tools.build_membership_index

# Single source, faster iteration during dev
python -m stock_data.tools.build_membership_index --source=zhitu

# Single board_type within a source
python -m stock_data.tools.build_membership_index --source=eastmoney --type=concept

# Adjust rate limit (default 1.0-2.0s jitter)
python -m stock_data.tools.build_membership_index --inter-call-sleep-min 0.5 --inter-call-sleep-max 1.0

# Verbose logging
python -m stock_data.tools.build_membership_index -v
```

### Exit codes

- `0`: All boards succeeded
- `1`: At least one board failed (errors printed at end)

### Notes

- Idempotent: re-running upserts existing rows. `refreshed_at` is updated.
- Per-source single worker thread (default). `--max-workers-per-source=2` is possible
  but risks upstream rate limits.
- After first bootstrap, membership data is kept fresh by forward-path lazy fill
  (`/boards/{code}/stocks` calls upsert). Long-tail boards never queried require
  `?refresh=true` or this CLI.
