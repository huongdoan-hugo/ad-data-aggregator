# Ad Performance Aggregator

Solution to the Flinters Vietnam challenge **FV-SEC001**. A command-line tool reads a ~1GB CSV of advertising records (`ad_data.csv`, 26,843,544 rows, 50 campaigns) in a single streaming pass. It aggregates the records by `campaign_id` and writes two rankings:

- `top10_ctr.csv`: the 10 campaigns with the highest CTR (`total_clicks / total_impressions`)
- `top10_cpa.csv`: the 10 campaigns with the lowest CPA (`total_spend / total_conversions`), excluding campaigns with zero conversions

Both files have the columns `campaign_id,total_impressions,total_clicks,total_spend,total_conversions,CTR,CPA`. The submitted results are in [`results/`](results/).

## Setup

- Python 3.14 (developed and tested on 3.14.10, Windows 10).
- `aggregator.py` uses the standard library only, so nothing needs to be installed to run it.
- Development only: `pytest` for the tests, `duckdb` for the cross-check script.

```bash
pip install pytest duckdb
```

- Data: unzip `ad_data.csv.zip` into `data/` so that the input is `data/ad_data.csv`. `data/` is git-ignored.

## How to run

```bash
python aggregator.py --input data/ad_data.csv --output results/
```

- `--input`: path to the source CSV.
- `--output`: directory for `top10_ctr.csv` and `top10_cpa.csv`. It is created if it does not exist, and existing files are overwritten.
- stdout: `Campaigns: <n>, skipped rows: <n>`.
- stderr: `Error: ...` on failure.
- Exit codes:
  - `0` on success;
  - `1` when the input is missing, unreadable, empty, has an unexpected header or cannot be parsed as CSV, or when the results cannot be written;
  - `2` for invalid command-line arguments (argparse).

## How to run the tests

```bash
python -m pytest
```

62 tests, all passing. They cover:

- spend parsing into cents, including the forms that must be rejected (`1e2`, `1_000`, `nan`, `-5.0`, more than two decimals, ...);
- aggregation, malformed rows (checking that a bad row adds nothing to a campaign that already has totals), blank lines, empty and header-only files, wrong headers;
- exact CTR/CPA, including zero impressions and zero conversions;
- ranking order, which ten campaigns survive the top-10 cut, a tie at tenth place, `campaign_id` tie-breaks, and a tie that floats cannot separate;
- half-up formatting;
- CSV writing with empty metrics;
- end-to-end runs through `main()`: normal output, missing input, unparseable CSV, and an output path that cannot be written.

### Cross-check on the full dataset

```bash
python scripts/verify_with_duckdb.py --input data/ad_data.csv --results results/
```

This script recomputes both rankings independently with DuckDB (exact `DECIMAL` sums) and compares them cell by cell with the files in `results/`. Result on 2026-11-02, with the current code: both files are **identical**.

`scripts/inspect_data.py` is a one-pass data survey. It reported 26,843,544 rows, 0 malformed rows, 50 campaigns, no rows with `impressions = 0`, and 326,361 rows with `conversions = 0`.

## Libraries used

| Library | Where | Purpose |
|---|---|---|
| Standard library (`csv`, `argparse`, `re`, `fractions`, `heapq`, `pathlib`, `collections`, `sys`) | `aggregator.py` | Parsing, exact arithmetic, ranking, output |
| Standard library (`subprocess`, `ctypes`, `statistics`, ...) | `benchmark.py` | Timing and peak memory (Windows), not part of the product |
| `pytest` | `tests/` | Tests |
| `duckdb` | `scripts/verify_with_duckdb.py` | Independent verification only, not part of the product |

## Performance on the 1GB file

```bash
python benchmark.py --runs 3 --log benchmark.log -- --input data/ad_data.csv --output results
```

Three consecutive runs from [`benchmark.log`](benchmark.log) (session `2026-11-02 18:10:25`):

| Run | Elapsed | Peak memory |
|---|---|---|
| 1 | 56.90 s | 16.7 MiB |
| 2 | 56.13 s | 16.7 MiB |
| 3 | 55.43 s | 16.5 MiB |
| **Median** | **56.13 s** | **max 16.7 MiB** |

Each run processed 50 campaigns and skipped 0 rows.

**Machine:** Intel Core i5-10400F (6 cores / 12 threads, 2.90 GHz), 15.9 GB RAM, Windows 10 Pro 10.0.19043, Python 3.14.10. Input file on a SATA HDD (Seagate ST500DM002), NTFS. Single-threaded.

**How it was measured:** `benchmark.py` starts each run as a separate `aggregator.py` process.

- Elapsed time is wall-clock time from process start to exit, including interpreter start-up.
- Peak memory is the child process's peak working set, read with the Win32 `GetProcessMemoryInfo` call after the child exits.
- The runs were back to back, and the OS file cache was not cleared between runs.

`benchmark.log` also contains:
- an earlier session with the same code (median 55.86 s, max 16.7 MiB);
- three runs of a previous version (median 64.75 s, about 19.6 MiB). That version parsed `spend` with `Decimal` and measured itself inside the process with `psutil`.

**Where the time goes:** this profile was taken on that previous `Decimal` version, using the first 2 million rows and scaling linearly, so treat it as an estimate.

| Step | Share of total time |
|---|---|
| `Decimal` parsing of `spend` | ~45% |
| `csv.reader` | ~23% |
| `int()` conversions | ~10% |
| per-row checks and dictionary updates | ~17% |
| file reading | ~5% |

Replacing `Decimal` with the regex parser described below took about 9 s off the median run: 64.75 s → 56.13 s. The current version has not been re-profiled.

Possible further speed-ups, not done:
- a hand-written string parser for `spend`. In isolation it measured about 2× faster than the regex (0.70 s vs 1.53 s for 2 million values), but that prototype did not yet include the validation this parser needs;
- splitting the file into byte ranges and processing them in parallel. Merging is cheap because there are only 50 campaigns.

Memory stays flat at about 17 MiB because only one row is held at a time, plus one entry per campaign.

## Design decisions

**Streaming, one pass.** The file is read row by row with `csv.reader`. Only the running totals per campaign are kept (`[impressions, clicks, spend_cents, conversions]`), so memory grows with the number of campaigns (50), not with the file size. `csv.reader` was kept instead of a faster `str.split(",")` because it handles quoted fields correctly.

**Spend is summed as integer cents.** Each `spend` value must match `\d+(\.\d{1,2})?` (ASCII digits only). It is converted to an `int` number of cents.

- Everything else is a malformed row: signs, exponents (`1e2`), underscores (`1_000`), surrounding spaces, `5.`, `.5`, `nan`, `inf`, and more than two decimals.
- Summing about 537,000 rows per campaign as floats drifts: a float run produced `394780333.96000457` instead of `394780333.96`. Integer cents are exact.
- An earlier version parsed `spend` with `Decimal`. It was slower and accepted exponents, and a single `1e999990` value stalled it for about a minute.

**Rank on exact fractions, round only when writing.** CTR is `Fraction(clicks, impressions)` and CPA is `Fraction(spend_cents, 100 * conversions)`. Rankings compare these exact values. Rounding happens only in `format_fraction`, using integer arithmetic (round half up, no floats). This matters for this dataset:

- All 10 campaigns in `top10_ctr.csv` display `0.0275`, and four campaigns in `top10_cpa.csv` display `19.33`. Their order comes from digits that are hidden by rounding, so equal-looking rows are **not** in `campaign_id` order.
- Ranking on rounded values would make the order arbitrary. Ranking on floats can mis-order true ties: `0.10 + 0.20` versus `0.30` (covered by a test).

**Output format.** CTR has 4 decimals; `total_spend` and CPA have 2 decimals. Values are rounded half up: `10.125` becomes `10.13` and `0.03125` becomes `0.0313`. Python's `round()` would give `10.12` / `0.0312`. Integers are written as is. Files are UTF-8 with CRLF line endings (the `csv` module default).

**Tie-break: `campaign_id` ascending.** This only applies when two campaigns have exactly the same CTR (or CPA). It is deterministic, easy to explain, and works as a string sort because the IDs are zero-padded (`CMP001`).

**`impressions = 0` and `conversions = 0`.**

- At row level, zeros are valid values and are summed normally (326,361 rows have `conversions = 0`).
- At campaign level:
  - `total_impressions = 0`: CTR is undefined, so the CTR cell is empty and the campaign is excluded from `top10_ctr.csv`.
  - `total_conversions = 0`: CPA is undefined, so the CPA cell is empty and the campaign is excluded from `top10_cpa.csv`.
- In the real data every campaign has non-zero totals, so no cell is empty.

**Rows are not deduplicated.** The challenge defines each metric as a total over all records. Every valid row is summed, even when another row has the same `(campaign_id, date)`.

**Measurement is kept out of the product.** `aggregator.py` does not time itself. `benchmark.py` measures it from the outside, so the product stays standard-library only and the numbers include everything a user would wait for.

**Malformed rows are skipped and counted; file-level problems stop the program.**

| Kind of problem | Behaviour |
|---|---|
| Wrong column count; non-integer `impressions`/`clicks`/`conversions`; `spend` not in the format above; any negative value | The row is skipped and counted, and the total is printed as `skipped rows`. A row is checked in full before anything is added, so a bad row never contributes partial totals. |
| Blank lines | Ignored, not counted. |
| Missing file, unreadable file, empty file, or a header that is not exactly `campaign_id,date,impressions,clicks,spend,conversions` (whitespace around names is trimmed) | `Error: ...` on stderr, exit code 1. |
| Input that the `csv` module cannot parse (for example a field over 131,072 characters) | `Error: ...` on stderr, exit code 1. |
| Output directory or files cannot be written | `Error: cannot write results: ...` on stderr, exit code 1. The two files are written one after the other, so if only the second write fails, the first file is already updated. |
| Header-only file | Exit code 0 with header-only output files. |
| `date` | Not used in the calculation and currently not validated. |
| `campaign_id` | Used as is: it is not trimmed, and an empty ID is not rejected. |

> TODO (planned, not implemented yet):
> - count skipped rows by reason and report the first few line numbers on stderr;
> - add a `--strict` flag;
> - validate `date` and empty `campaign_id`;
> - locate columns by name and accept a UTF-8 BOM;
> - treat "no valid rows" as an error;
> - write both result files atomically;
> - move the `Campaigns: ...` summary to stderr.

## Project layout

```
aggregator.py                  # the CLI (product)
benchmark.py                   # timing / peak memory, one process per run (Windows)
tests/test_aggregator.py       # pytest suite
scripts/inspect_data.py        # one-pass data survey
scripts/verify_with_duckdb.py  # independent cross-check (DuckDB)
results/                       # submitted top10_ctr.csv and top10_cpa.csv
benchmark.log                  # raw timing / memory runs
PROMPTS.md                     # AI assistant prompts, verbatim
```

## AI assistance

This solution was built with an AI coding assistant (Claude Code). The prompts are recorded verbatim in [`PROMPTS.md`](PROMPTS.md), as the challenge asks.
