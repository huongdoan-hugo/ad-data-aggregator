# Ad Performance Aggregator

Recruitment challenge FV-SEC001 (Flinters Vietnam). CLI that streams `data/ad_data.csv` (~1GB, 26.8M rows, 50 campaigns) and writes `top10_ctr.csv` and `top10_cpa.csv`. Graded on exact results, clean code, error handling, memory efficiency, tests and documented decisions.

## Stack
- Python 3.14. `aggregator.py` (the product) uses the standard library only.
- Measurement and verification live outside the product:
  - `benchmark.py`: elapsed time and peak memory, standard library + `ctypes` (Windows), each run in a separate process.
  - `scripts/verify_with_duckdb.py`: recomputes the results independently; needs `duckdb` (dev only).
- `pytest` for tests.

## Commands
- Run: `python aggregator.py --input data/ad_data.csv --output results/`
- Test: `python -m pytest`
- Benchmark (Windows, appends to `benchmark.log`): `python benchmark.py --runs 3 --log benchmark.log -- --input data\ad_data.csv --output results`
- Verify against DuckDB: `python scripts/verify_with_duckdb.py --input data/ad_data.csv --results results/`
- Survey the dataset: `python scripts/inspect_data.py [path] [--head N]`

## Design decisions (do not change without asking)
- Stream rows; never load the whole file. Aggregate per campaign into `[impressions, clicks, spend_cents, conversions]`.
- Money: parse each `spend` into integer cents (reject anything that is not a whole number of cents) and sum integers. Never accumulate floats.
- Ranking: CTR = `Fraction(clicks, impressions)`, CPA = `Fraction(spend_cents, 100 * conversions)`. Rank on these exact values, never on floats or rounded values. Tie-break: `campaign_id` ascending.
- Rounding happens only when writing the CSV: round half up, CTR 4 decimals, spend and CPA 2 decimals. Never use built-in `round()` or floats for output.
- Do not dedupe by `(campaign_id, date)`: each row is an individual record and must be summed.
- `total_conversions = 0` means CPA is empty and the campaign is excluded from `top10_cpa`. `total_impressions = 0` means CTR is empty and the campaign is excluded from `top10_ctr`.
- Output columns: `campaign_id,total_impressions,total_clicks,total_spend,total_conversions,CTR,CPA`.
- Header columns are located by name; open input as `utf-8-sig`.
- Bad rows (wrong column count, empty id, non-numeric, negative, non-finite, bad date) are validated as a whole, skipped, counted by reason and reported on stderr. `--strict` stops at the first bad row.
- Fatal errors (missing file, missing header columns, no valid rows) exit non-zero with a clear message.

## Code conventions
- Meaningful names; small functions with one job.
- No dead code, no commented-out code, no debug prints.
- Comments only for non-obvious reasons (why, not what).
- Logs and diagnostics go to stderr; stdout and output CSVs stay clean.
- Every behaviour change comes with a test. Run `python -m pytest` before saying a task is done.
- Non-obvious decisions go in the README "Decisions" section.

## Ask before doing any of these
- Adding a dependency, or any non-standard-library import to `aggregator.py`.
- Putting timing or memory measurement code back into `aggregator.py`.
- Changing a design decision above, the output format, rounding or tie-break rules.
- Committing, pushing, creating branches or rewriting git history.
- Deleting, moving or modifying anything in `data/`, or committing it.
- Editing `PROMPTS.md` (a hook appends prompts verbatim; the challenge requires them unedited) or anything under `.claude/`.
- Overwriting the submitted `top10_ctr.csv` / `top10_cpa.csv` results.
