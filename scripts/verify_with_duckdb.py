"""Recompute top-10 CTR/CPA with DuckDB and diff them against aggregator.py output.

Verification tool only, not part of the product. Requires: pip install duckdb

Usage: python scripts/verify_with_duckdb.py [--input data/ad_data.csv] [--results results/]

Reference rules (same as CLAUDE.md): spend summed exactly, ranking on exact values,
ties broken by campaign_id ascending, ROUND_HALF_UP to 4 dp for CTR and 2 dp for spend/CPA.
"""
import argparse
import csv
import sys
import time
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction
from pathlib import Path

import duckdb

OUTPUT_HEADER = [
    "campaign_id", "total_impressions", "total_clicks",
    "total_spend", "total_conversions", "CTR", "CPA",
]
DECIMAL_PLACES = {"total_spend": 2, "CTR": 4, "CPA": 2}
TOP_N = 10

# Rows are cast as text first so invalid rows are counted instead of aborting the scan.
QUERY = """
WITH raw AS (
    SELECT * FROM read_csv({path}, header = true, all_varchar = true)
),
typed AS (
    SELECT
        trim(campaign_id) AS campaign_id,
        TRY_CAST(trim(date) AS DATE) AS day,
        TRY_CAST(trim(impressions) AS BIGINT) AS impressions,
        TRY_CAST(trim(clicks) AS BIGINT) AS clicks,
        CASE WHEN regexp_full_match(trim(spend), '[0-9]+(\\.[0-9]{{1,2}})?')
             THEN CAST(trim(spend) AS DECIMAL(38, 2)) END AS spend,
        TRY_CAST(trim(conversions) AS BIGINT) AS conversions
    FROM raw
),
flagged AS (
    SELECT *,
        campaign_id IS NOT NULL AND campaign_id <> ''
        AND day IS NOT NULL AND spend IS NOT NULL
        AND impressions >= 0 AND clicks >= 0 AND conversions >= 0 AS is_valid
    FROM typed
)
SELECT
    campaign_id,
    SUM(impressions) AS impressions,
    SUM(clicks) AS clicks,
    SUM(spend) AS spend,
    SUM(conversions) AS conversions,
    COUNT(*) AS row_count
FROM flagged
WHERE is_valid
GROUP BY campaign_id
UNION ALL
SELECT NULL, NULL, NULL, NULL, NULL, COUNT(*) FROM flagged WHERE NOT is_valid
"""


def parse_args():
    parser = argparse.ArgumentParser(description="Cross-check aggregator.py results with DuckDB.")
    parser.add_argument("--input", type=Path, default=Path("data/ad_data.csv"), help="Source CSV")
    parser.add_argument("--results", type=Path, default=Path("results"),
                        help="Directory holding top10_ctr.csv and top10_cpa.csv from aggregator.py")
    return parser.parse_args()


def sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def load_totals(path):
    """Return ({campaign_id: (impressions, clicks, spend_cents, conversions)}, valid_rows, invalid_rows)."""
    rows = duckdb.sql(QUERY.format(path=sql_string(path.as_posix()))).fetchall()
    totals = {}
    valid_rows = 0
    invalid_rows = 0
    for campaign_id, impressions, clicks, spend, conversions, row_count in rows:
        if campaign_id is None:
            invalid_rows += row_count
            continue
        totals[campaign_id] = (impressions, clicks, int(spend * 100), conversions)
        valid_rows += row_count
    return totals, valid_rows, invalid_rows


def round_half_up(value, places):
    with localcontext() as context:
        context.prec = 50
        exact = Decimal(value.numerator) / Decimal(value.denominator)
        return str(exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def to_output_row(campaign_id, impressions, clicks, spend_cents, conversions):
    ctr = Fraction(clicks, impressions) if impressions else None
    cpa = Fraction(spend_cents, conversions * 100) if conversions else None
    return {
        "campaign_id": campaign_id,
        "total_impressions": str(impressions),
        "total_clicks": str(clicks),
        "total_spend": round_half_up(Fraction(spend_cents, 100), 2),
        "total_conversions": str(conversions),
        "CTR": "" if ctr is None else round_half_up(ctr, 4),
        "CPA": "" if cpa is None else round_half_up(cpa, 2),
    }, ctr, cpa


def expected_tops(totals):
    scored = [to_output_row(campaign_id, *values) for campaign_id, values in totals.items()]
    by_ctr = sorted((s for s in scored if s[1] is not None), key=lambda s: (-s[1], s[0]["campaign_id"]))
    by_cpa = sorted((s for s in scored if s[2] is not None), key=lambda s: (s[2], s[0]["campaign_id"]))
    return [s[0] for s in by_ctr[:TOP_N]], [s[0] for s in by_cpa[:TOP_N]]


def read_actual(path):
    with path.open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        header = [name.strip() for name in reader.fieldnames or []]
        rows = [{key.strip(): (value or "").strip() for key, value in row.items() if key} for row in reader]
    return header, rows


def classify_cell(column, expected, actual):
    """Describe how a mismatching cell differs: 'format only' when rounding actual gives expected."""
    places = DECIMAL_PLACES.get(column)
    if places is None or not expected or not actual:
        return "value"
    try:
        actual_number = Decimal(actual)
    except ArithmeticError:
        return "not a number"
    rounded = actual_number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    if str(rounded) == expected:
        return "format only (rounds to expected)"
    return f"value (diff {actual_number - Decimal(expected):+})"


def compare(name, expected_rows, actual_header, actual_rows):
    problems = []
    if actual_header != OUTPUT_HEADER:
        problems.append(f"header differs: expected {OUTPUT_HEADER}, got {actual_header}")
    if len(actual_rows) != len(expected_rows):
        problems.append(f"row count differs: expected {len(expected_rows)}, got {len(actual_rows)}")

    expected_ids = [row["campaign_id"] for row in expected_rows]
    actual_ids = [row.get("campaign_id", "") for row in actual_rows]
    if expected_ids != actual_ids:
        problems.append(f"campaign order differs:\n      expected {expected_ids}\n      actual   {actual_ids}")
        missing = [cid for cid in expected_ids if cid not in actual_ids]
        extra = [cid for cid in actual_ids if cid not in expected_ids]
        if missing:
            problems.append(f"missing campaigns: {missing}")
        if extra:
            problems.append(f"unexpected campaigns: {extra}")

    actual_by_id = {row.get("campaign_id"): row for row in actual_rows}
    for expected in expected_rows:
        actual = actual_by_id.get(expected["campaign_id"])
        if actual is None:
            continue
        for column in OUTPUT_HEADER[1:]:
            actual_value = actual.get(column, "")
            if actual_value != expected[column]:
                problems.append(
                    f"{expected['campaign_id']}.{column}: expected {expected[column]!r}, "
                    f"got {actual_value!r} -> {classify_cell(column, expected[column], actual_value)}"
                )

    print(f"\n== {name} ==")
    if not problems:
        print("  identical")
    for problem in problems:
        print(f"  - {problem}")
    return not problems


def main():
    args = parse_args()
    if not args.input.is_file():
        sys.exit(f"Input file not found: {args.input}")
    result_files = {name: args.results / name for name in ("top10_ctr.csv", "top10_cpa.csv")}
    missing = [str(path) for path in result_files.values() if not path.is_file()]
    if missing:
        sys.exit(f"Aggregator output not found: {missing}. Run aggregator.py first.")

    started = time.perf_counter()
    totals, valid_rows, invalid_rows = load_totals(args.input)
    print(f"DuckDB scan: {time.perf_counter() - started:.1f}s, "
          f"{valid_rows:,} valid rows, {invalid_rows:,} invalid rows, {len(totals)} campaigns")

    expected_ctr, expected_cpa = expected_tops(totals)
    ctr_ok = compare("top10_ctr.csv", expected_ctr, *read_actual(result_files["top10_ctr.csv"]))
    cpa_ok = compare("top10_cpa.csv", expected_cpa, *read_actual(result_files["top10_cpa.csv"]))

    print("\nResult:", "MATCH" if ctr_ok and cpa_ok else "DIFFERENCES FOUND")
    return 0 if ctr_ok and cpa_ok else 1


if __name__ == "__main__":
    sys.exit(main())
