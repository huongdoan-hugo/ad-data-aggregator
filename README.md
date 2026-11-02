# Ad Performance Aggregator

Streams a large `ad_data.csv` (or the `.zip` that contains it), aggregates it per `campaign_id`
and writes the 10 campaigns with the highest CTR and the 10 with the lowest CPA.

## Requirements

Python 3.9+ and the standard library only. `pytest` is needed only to run the tests. Tested on Python 3.14 (Windows 10).

## Usage

```
python aggregator.py --input data/ad_data.csv --output results
python aggregator.py --input ad_data.csv.zip --output results
```

| Option | Meaning |
|---|---|
| `--input` | `.csv` or `.zip` (detected from the content, not the extension). A zip must hold exactly one `.csv`; it is extracted to a temporary directory and removed afterwards. |
| `--output` | Directory for `top10_ctr.csv` and `top10_cpa.csv` (created if missing, files overwritten). |

Exit code is `0` on success, `1` if the input is missing, empty, a corrupt zip or has a bad header,
`2` for invalid arguments. Bad data rows never stop the run; they are skipped and counted.

### Docker

```
docker build -t ad-aggregator .
docker run --rm -v "$PWD/data:/data" -v "$PWD/results:/results" ad-aggregator
```

### Tests

```
pip install -r requirements-dev.txt
pytest
```

## How it works

1. The header is read once (a UTF-8 BOM is accepted); columns are located by name.
2. The bytes after the header are cut into `WORKERS * 4` = 16 contiguous ranges (fewer for
   files under 1 MB per range, which are read in a single range without starting a pool).
3. A pool of 4 worker processes (fixed) takes the ranges. A range owns every line that
   *starts* inside it: the worker steps back one byte, skips the rest of that line, and keeps
   reading until the next line would start at or after the end of its range. Every line is
   therefore counted exactly once, wherever the cuts fall. Each worker sums per campaign.
4. The parent merges the per-range sums, computes CTR and CPA once from the totals, ranks and
   writes.

Workers stream their range line by line, so memory does not grow with the file size.

## Decisions on points the task leaves open

| Topic | Decision | Reason |
|---|---|---|
| CTR / CPA | `Fraction` computed from totals: `sum(clicks) / sum(impressions)`, `sum(spend) / sum(conversions)` | Averaging per-row ratios is wrong; exact values avoid float ties and drift. |
| Ranking | On exact values, never on rounded ones. Ties broken by `campaign_id` ascending. | Many campaigns here share the same rounded CTR (0.0275), so rounding before ranking would reorder them arbitrarily. |
| Rounding | Only when writing, half up: CTR 4 decimals, CPA and `total_spend` 2 decimals. | Matches the sample tables; half up avoids Python's banker's rounding. |
| Spend | Parsed as an integer number of 1e-6 USD, never as float. Up to 6 decimals accepted. More than 6 decimals, exponent notation or a sign: row rejected and counted. | Exact sums. Rejecting is safer than silently rounding money. The data has at most 2 decimals. |
| Zero impressions or zero conversions | The campaign is kept and the undefined value (CTR with no impressions, CPA with no conversions) is written as an empty cell. It is left out only of the ranking on that undefined metric. | No data is dropped silently, and an undefined ratio is never ranked. |
| Bad rows | Skipped and counted by reason (wrong column count, not a number, negative, empty campaign id, spend over 6 decimals). Blank lines are ignored. | One corrupt line should not discard a 1 GB run. |
| Header | Must contain `campaign_id, impressions, clicks, spend, conversions` (case-insensitive, any order, extra columns allowed, duplicates rejected). `date` is not used or validated. | Fail fast on a file that cannot be interpreted. |
| Quotes | Rows are parsed with the `csv` module, so quoted commas and newlines work. A multi-line quoted field is read by the range where it starts. If a range boundary falls inside such a field, the next range starts mid-field and reads the rest as bad rows. | The real data has no quotes; handling this needs a sequential scan, which would defeat the split. |
| Line endings | `\n` and `\r\n` accepted. | |
| Fewer than 10 campaigns | Write as many rows as exist. | |
| No valid rows | Header-only output files, exit code 0, the summary shows the counts. | |
| Sanity checks | `clicks > impressions` and the `date` format are not validated. | Not required; the task does not define them as errors. |

## Performance

Not measured yet for the current parallel implementation; run `scriptsenchmark.py` on the
1 GB file and record the result here. A zip input is extracted to a temporary directory first
and needs about 1 GB of free space there (set `TEMP` to change it).

`scriptserify_with_duckdb.py` recomputes the totals with DuckDB and compares them with
`results/`; it needs `pip install duckdb` and is not part of the aggregator.

## Benchmark

```
python scripts\benchmark.py --input data\ad_data.csv
```

Runs `aggregator.py` in its own process (output goes to a temporary directory unless
`--output` is given) and appends one entry to `benchmark.log`: timestamp, full command, machine
description, exit code, wall time, peak working set and peak pagefile usage. Extra arguments
are passed through to `aggregator.py`. Windows only; uses the standard library and `ctypes`.

**Limitation:** peak memory is read for the process that was started, nothing else. If the
aggregator runs with several worker processes, their memory is not counted, so the real total
is higher than the logged peak. Wall time covers the whole run, workers included.

## AI usage

The prompts used while building this are in [PROMPTS.md](PROMPTS.md).
