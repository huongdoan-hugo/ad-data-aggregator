# Ad Performance Aggregator

Solution to the FV-SEC001 *Ad Performance Aggregator* challenge: read a ~1 GB `ad_data.csv`
(26,843,544 rows, 50 campaigns), aggregate it per `campaign_id`, and write

- `top10_ctr.csv`: the 10 campaigns with the highest CTR (clicks / impressions);
- `top10_cpa.csv`: the 10 campaigns with the lowest CPA (spend / conversions).

Both files have the columns
`campaign_id,total_impressions,total_clicks,total_spend,total_conversions,CTR,CPA`,
with `total_spend` and `CPA` to 2 decimals and `CTR` to 4 decimals, as in the task's sample tables.

## Requirements and installation

- Python 3.14 on Windows 10 (the version used for development and every measurement below).
- Running `aggregator.py` needs **nothing to install**: it uses the standard library only.
- Tests and the independent check need `pip install -r requirements-dev.txt` (`pytest`, `duckdb`).

## Usage

```
python aggregator.py --input data\ad_data.csv --output results
python aggregator.py --input ad_data.csv.zip --output results
```

| Option | Meaning |
|---|---|
| `--input` | A `.csv` or a `.zip` holding exactly one `.csv`. The kind is detected from the content, not the extension. A zip is extracted to a temporary directory (about the size of the CSV in free space) and removed afterwards. |
| `--output` | Directory for the two result files. Created if missing (including parents); existing result files are overwritten. |

The number of workers is fixed at 4 (see the design decisions). On success the program prints

```
Read 26843544 data rows, 50 campaigns.
Skipped 0 bad rows {}.
Wrote top10_ctr.csv and top10_cpa.csv to results
```

Exit codes: `0` success, `1` the input cannot be processed (missing, empty, corrupt zip, bad header,
line longer than 64 KiB) or the output cannot be written, `2` invalid arguments.
Errors go to stderr as one `error: ...` line, never as a traceback.

### Docker

```
docker build -t ad-aggregator .
docker run --rm -v "${PWD}\data:/data" -v "${PWD}\results:/results" ad-aggregator
```

`.dockerignore` keeps the build context to `aggregator.py`, so the 1 GB `data/` folder is not sent
to the daemon. The image has **not been built or run** here (Docker is not installed on the
development machine).

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```

100 tests, about 1.5 s. They cover parsing and every bad-row reason, exact spend sums, CTR/CPA and
undefined values, ranking (descending/ascending, top 10, tie-break, values that `float` cannot
tell apart), half-up rounding, output format, header and BOM/CRLF handling, quoted fields,
zip input, input errors, and parallelism: byte ranges that cover every line exactly once for many
range counts (LF, CRLF, no final newline, header only, bad and blank rows), plus a run through a
real 4-worker `Pool` compared with expected tables computed independently in the test.

## Other scripts

| Script | Purpose |
|---|---|
| `scripts\verify_with_duckdb.py` | Recomputes the totals from `data\ad_data.csv` with DuckDB (exact DECIMAL sums) and ranks them with exact `Fraction`s, then compares order, integer columns, `total_spend`, `CTR` and `CPA` (value rounded half up) with `results\`. Prints `MATCH` (exit 0) or every difference (exit 1). Independent of `aggregator.py`. |
| `scripts\benchmark.py` | Runs `aggregator.py` in its own process and appends wall time, peak memory, machine description and the aggregator's output to `benchmark.log`. Windows only, standard library + `ctypes`. |
| `scripts\inspect_data.py` | Streams a CSV once and prints a short quality summary (first rows, row and campaign counts, bad rows, ranges, quotes). Used to survey the data before designing the parser. |

## Libraries

- `aggregator.py` (standard library): `argparse`, `collections`, `contextlib`, `csv`, `fractions`,
  `heapq`, `multiprocessing`, `os`, `re`, `shutil`, `sys`, `tempfile`, `typing`, `zipfile`, `zlib`.
- Scripts: standard library only, except `verify_with_duckdb.py` (`duckdb`).
- Tests: `pytest`.

## Performance on the 1 GB file

Measured with `python scripts\benchmark.py --input data\ad_data.csv`; the raw entries are in
`benchmark.log`. Machine: Windows 10, Intel 6 cores / 12 threads, 15.9 GB RAM, Python 3.14.10,
file already in the OS cache, 4 workers, 16 byte ranges, no other load.

| Run | Wall time | Peak commit, whole process tree | Peak working set, main process |
|---|---|---|---|
| 1 | 40.49 s | 75.4 MB | 21.4 MB |
| 2 | 40.21 s | 74.9 MB | 21.1 MB |
| 3 | 38.22 s | 74.7 MB | 21.1 MB |
| **Median / max** | **40.21 s** | **75.4 MB** | 21.4 MB |

- Memory is the peak *commit* (private memory) of the main process and all four workers, read from a
  Windows job object. It is not the same as working set, and the main-process column does not
  include the workers, so use the commit column as the figure for the whole run.
- The first three entries in `benchmark.log` (about 37 s) were taken before the last robustness
  changes (bounded line length, stray-quote recovery); the last three are for the submitted code.
- Memory stays flat because workers stream their range line by line and only keep one small sum
  per campaign. It grows with the number of *distinct* campaigns, not with the file size.
- Correctness: both result files match the independent DuckDB computation (`MATCH`). On this data
  all ten CTR values in `top10_ctr.csv` print as `0.0275`, so their order comes from the exact
  fractions and the `campaign_id` tie-break, not from the rounded values.

## Design decisions

The task leaves several points open. Each row states the choice and why.

| Topic | Decision | Why |
|---|---|---|
| Parallelism | Fixed 4 worker processes. The bytes after the header are cut into `WORKERS * 4` = 16 contiguous ranges. A range owns every line that *starts* in it: the worker steps back one byte, skips the rest of that line and reads until the next line would start at or after the range end. | Each line is counted exactly once wherever the cuts fall; 16 ranges for 4 workers balance the load. `process_range` is a module-level function so it works with Windows' `spawn`. |
| Small files | Ranges are at least 1 MiB, so a file under 1 MiB is read in one range without starting a pool. | Avoids process start-up cost, and keeps tiny files free of range-boundary effects. |
| CTR and CPA | Computed once per campaign from the totals as `Fraction`s: `sum(clicks)/sum(impressions)` and `sum(spend)/sum(conversions)`. | Averaging per-row ratios is wrong; exact values avoid float drift and false ties. |
| Ranking | On the exact values, never on rounded ones. Ties are broken by `campaign_id` ascending. | The result is deterministic and independent of how rows are split across workers. |
| Rounding | Only when writing, half up: CTR 4 decimals, CPA and `total_spend` 2 decimals. | Matches the sample tables; avoids Python's round-half-even surprises. |
| Spend | Parsed as an integer number of 1e-6 USD, never as a float. Up to 6 decimals are accepted; a sign, an exponent or more than 6 decimals makes the row bad. | Exact sums. Rejecting is safer than silently rounding money. The data has at most 2 decimals. |
| Undefined CTR or CPA | A campaign with no impressions (CTR) or no conversions (CPA) is kept; the undefined cell is written empty and the campaign is left out only of the ranking on that metric. | No data is dropped silently, and an undefined ratio is never ranked. |
| Bad rows | Skipped and counted by reason: `wrong_column_count`, `empty_campaign_id`, `negative_value`, `not_a_number`, `spend_over_6_decimals`, `malformed_row`. Counts must be plain ASCII digits, so `nan`, `inf`, `1e5`, signs, spaces and non-ASCII digits are rejected. Blank lines are ignored. | One corrupt line must not discard a 1 GB run. |
| Campaign ids | Surrounding whitespace is stripped; the id is otherwise case-sensitive (`a` and `A` differ). Numbers are not stripped. | A stray space would silently split a campaign; a stray space in a number is a visible bad row instead. |
| Header | Must contain `campaign_id, impressions, clicks, spend, conversions` (case-insensitive, any order, extra columns allowed, duplicates rejected). `date` is not required, used or validated. A UTF-8 BOM is accepted. A header that is not valid CSV is an input error. | Fail fast on a file that cannot be interpreted. |
| Quotes | Lines containing `"` are parsed with the `csv` module: quoted commas and newlines work (a field may span up to 100 lines). A multi-line row that turns out invalid costs one row: it is counted once and reading resumes at its second line, so a stray quote cannot swallow the rows after it. A quoted field over the `csv` limit (128 KB) is a `malformed_row`. | The real data has no quotes, but a stray `"` must not lose data silently or crash the run. |
| Limit of the quote handling | If a range boundary falls inside a multi-line quoted field, the next range starts mid-field and reads the rest as bad rows. | Detecting this needs a sequential scan, which would defeat the split. |
| Line length | A line longer than 64 KiB is an input error. | Bounds memory per worker; a real ad row is about 40 bytes, so such a line means the file is not row-oriented CSV (for example CR-only line endings). |
| Line endings | `\n` and `\r\n` are accepted. | |
| Zip input | Extracted to a temporary directory, then split like a CSV. The zip must hold exactly one `.csv`. | Compressed data cannot be read at arbitrary byte offsets. |
| Fewer than 10 campaigns | As many rows as exist are written. No valid rows: header-only files, exit code 0. | |
| Not validated | `clicks > impressions` and the `date` format. | The task does not define them as errors. |
| Console output | Characters that stdout cannot encode (for example in the output path on a Windows pipe) are replaced by `?` instead of crashing. | The files are already written when the summary is printed. |

## Repository layout

```
aggregator.py                 the program (standard library only)
tests/test_aggregator.py      pytest suite
scripts/                      inspect_data.py, verify_with_duckdb.py, benchmark.py
results/                      top10_ctr.csv, top10_cpa.csv produced from data\ad_data.csv
benchmark.log                 benchmark entries (appended by scripts\benchmark.py)
Dockerfile, .dockerignore     container image
requirements-dev.txt          pytest, duckdb (tests and verification only)
CLAUDE.md                     working rules for the AI assistant used on this project
PROMPTS.md                    the prompts used, as sent
```

## AI usage

An AI coding assistant was used throughout; every prompt is in [PROMPTS.md](PROMPTS.md).
