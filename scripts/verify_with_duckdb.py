"""Recompute the top 10 tables with DuckDB and compare them with the files in results/.

Independent of aggregator.py. Totals come from DuckDB (exact DECIMAL sums); ranking uses
exact Fractions with ties broken by campaign_id. Prints MATCH and exits 0 when the result
files agree, otherwise prints every difference and exits 1.
"""

import argparse
import csv
import os
import sys
from fractions import Fraction

import duckdb

TOP_N = 10
EXPECTED_HEADER = [
    "campaign_id",
    "total_impressions",
    "total_clicks",
    "total_spend",
    "total_conversions",
    "CTR",
    "CPA",
]
SPEND_PLACES = 2
CTR_PLACES = 4
CPA_PLACES = 2
TOTALS_QUERY = """
    SELECT campaign_id,
           sum(impressions)::HUGEINT,
           sum(clicks)::HUGEINT,
           sum(spend)::DECIMAL(38, 6),
           sum(conversions)::HUGEINT
    FROM read_csv(
        ?,
        header = true,
        types = {
            'campaign_id': 'VARCHAR',
            'date': 'VARCHAR',
            'impressions': 'BIGINT',
            'clicks': 'BIGINT',
            'spend': 'DECIMAL(18, 6)',
            'conversions': 'BIGINT'
        }
    )
    GROUP BY campaign_id
"""


def load_expected_campaigns(input_path):
    """Return one dict per campaign with exact totals and, when defined, exact CTR and CPA."""
    campaigns = []
    for campaign_id, impressions, clicks, spend, conversions in (
        duckdb.connect().execute(TOTALS_QUERY, [input_path]).fetchall()
    ):
        spend = Fraction(str(spend))
        campaigns.append(
            {
                "campaign_id": campaign_id,
                "impressions": int(impressions),
                "clicks": int(clicks),
                "spend": spend,
                "conversions": int(conversions),
                "ctr": Fraction(int(clicks), int(impressions)) if impressions else None,
                "cpa": spend / int(conversions) if conversions else None,
            }
        )
    return campaigns


def expected_rankings(campaigns):
    with_ctr = [campaign for campaign in campaigns if campaign["ctr"] is not None]
    with_cpa = [campaign for campaign in campaigns if campaign["cpa"] is not None]
    top_ctr = sorted(with_ctr, key=lambda c: (-c["ctr"], c["campaign_id"]))[:TOP_N]
    top_cpa = sorted(with_cpa, key=lambda c: (c["cpa"], c["campaign_id"]))[:TOP_N]
    return top_ctr, top_cpa


def read_result_file(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


def differences_in_value(label, actual_text, expected, places):
    """Compare a written decimal with the exact value; allow half a unit of the last place."""
    if expected is None:
        return [] if actual_text == "" else [f"{label}: expected blank, found {actual_text!r}"]
    try:
        actual = Fraction(actual_text)
    except (ValueError, ZeroDivisionError):
        return [f"{label}: expected about {float(expected):.{places + 2}f}, found {actual_text!r}"]
    if abs(actual - expected) > Fraction(1, 2 * 10**places):
        return [
            f"{label}: expected {float(expected):.{places + 2}f} "
            f"(rounded to {places} places), found {actual_text}"
        ]
    return []


def differences_in_row(position, row, campaign):
    prefix = f"row {position} ({campaign['campaign_id']})"
    if len(row) != len(EXPECTED_HEADER):
        return [f"{prefix}: expected {len(EXPECTED_HEADER)} columns, found {len(row)}"]
    found = dict(zip(EXPECTED_HEADER, row))
    differences = []
    if found["campaign_id"] != campaign["campaign_id"]:
        differences.append(
            f"row {position}: expected campaign {campaign['campaign_id']}, "
            f"found {found['campaign_id']}"
        )
    for column, key in (
        ("total_impressions", "impressions"),
        ("total_clicks", "clicks"),
        ("total_conversions", "conversions"),
    ):
        if found[column] != str(campaign[key]):
            differences.append(
                f"{prefix} {column}: expected {campaign[key]}, found {found[column]}"
            )
    differences += differences_in_value(
        f"{prefix} total_spend", found["total_spend"], campaign["spend"], SPEND_PLACES
    )
    differences += differences_in_value(f"{prefix} CTR", found["CTR"], campaign["ctr"], CTR_PLACES)
    differences += differences_in_value(f"{prefix} CPA", found["CPA"], campaign["cpa"], CPA_PLACES)
    return differences


def differences_in_file(name, table, expected_campaigns):
    if not table or table[0] != EXPECTED_HEADER:
        found = table[0] if table else "no header"
        return [f"{name}: header is {found}, expected {EXPECTED_HEADER}"]
    rows = table[1:]
    differences = []
    if len(rows) != len(expected_campaigns):
        differences.append(
            f"{name}: expected {len(expected_campaigns)} rows, found {len(rows)}"
        )
    for position, (row, campaign) in enumerate(zip(rows, expected_campaigns), start=1):
        differences += [f"{name} {text}" for text in differences_in_row(position, row, campaign)]
    return differences


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=os.path.join("data", "ad_data.csv"))
    parser.add_argument("--results", default="results")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    paths = {
        "top10_ctr.csv": os.path.join(args.results, "top10_ctr.csv"),
        "top10_cpa.csv": os.path.join(args.results, "top10_cpa.csv"),
    }
    for path in [args.input, *paths.values()]:
        if not os.path.isfile(path):
            print(f"error: file not found: {path}", file=sys.stderr)
            return 1
    top_ctr, top_cpa = expected_rankings(load_expected_campaigns(args.input))
    differences = differences_in_file(
        "top10_ctr.csv", read_result_file(paths["top10_ctr.csv"]), top_ctr
    ) + differences_in_file("top10_cpa.csv", read_result_file(paths["top10_cpa.csv"]), top_cpa)
    if differences:
        print("\n".join(differences))
        return 1
    print("MATCH")
    return 0


if __name__ == "__main__":
    sys.exit(main())
