"""Aggregate advertising performance by campaign and export top-10 rankings.

Spend is accumulated as integer cents and ratios are ranked as exact fractions,
so floating point error can never change a ranking. Values are rounded only
when written to the output files.
"""

import argparse
import csv
import heapq
import re
import sys
from collections import namedtuple
from fractions import Fraction
from pathlib import Path

EXPECTED_HEADER = ["campaign_id", "date", "impressions", "clicks", "spend", "conversions"]
OUTPUT_HEADER = [
    "campaign_id", "total_impressions", "total_clicks",
    "total_spend", "total_conversions", "CTR", "CPA",
]
TOP_N = 10
CENTS_PER_UNIT = 100
RATIO_PLACES = 4
MONEY_PLACES = 2
SPEND_PATTERN = re.compile(r"(\d+)(?:\.(\d{1,2}))?", re.ASCII)

Campaign = namedtuple(
    "Campaign",
    ["campaign_id", "impressions", "clicks", "spend_cents", "conversions", "ctr", "cpa"],
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Aggregate ad data by campaign.")
    parser.add_argument("--input", required=True, type=Path, help="Path to the input CSV file")
    parser.add_argument("--output", required=True, type=Path, help="Directory for result files")
    return parser.parse_args(argv)


def parse_cents(text):
    """Convert a plain decimal string with at most two decimals (e.g. "12.5") to integer cents."""
    match = SPEND_PATTERN.fullmatch(text)
    if match is None:
        raise ValueError(f"Spend is not a whole number of cents: {text!r}")
    whole, fraction = match.groups()
    return int(whole) * CENTS_PER_UNIT + int((fraction or "").ljust(MONEY_PLACES, "0"))


def aggregate(path):
    """Stream the CSV once and return ({campaign_id: [imp, clicks, cents, conv]}, bad_row_count)."""
    totals = {}
    bad_rows = 0
    with path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.reader(csv_file)
        header = next(reader, None)
        if header is None or [name.strip() for name in header] != EXPECTED_HEADER:
            raise ValueError(f"Unexpected header, expected {EXPECTED_HEADER}")
        for row in reader:
            if not row:
                continue
            try:
                campaign_id, _date, impressions, clicks, spend, conversions = row
                impressions, clicks, conversions = int(impressions), int(clicks), int(conversions)
                spend_cents = parse_cents(spend)
            except ValueError:
                bad_rows += 1
                continue
            if min(impressions, clicks, conversions, spend_cents) < 0:
                bad_rows += 1
                continue
            entry = totals.get(campaign_id)
            if entry is None:
                totals[campaign_id] = [impressions, clicks, spend_cents, conversions]
            else:
                entry[0] += impressions
                entry[1] += clicks
                entry[2] += spend_cents
                entry[3] += conversions
    return totals, bad_rows


def build_campaigns(totals):
    campaigns = []
    for campaign_id, (impressions, clicks, spend_cents, conversions) in totals.items():
        ctr = Fraction(clicks, impressions) if impressions > 0 else None
        cpa = Fraction(spend_cents, CENTS_PER_UNIT * conversions) if conversions > 0 else None
        campaigns.append(Campaign(campaign_id, impressions, clicks, spend_cents, conversions, ctr, cpa))
    return campaigns


def top_by_ctr(campaigns):
    candidates = [c for c in campaigns if c.ctr is not None]
    return heapq.nsmallest(TOP_N, candidates, key=lambda c: (-c.ctr, c.campaign_id))


def top_by_cpa(campaigns):
    candidates = [c for c in campaigns if c.cpa is not None]
    return heapq.nsmallest(TOP_N, candidates, key=lambda c: (c.cpa, c.campaign_id))


def format_fraction(value, places):
    """Format a non-negative Fraction with fixed decimals, rounding half up, without floats."""
    scaled = value * 10 ** places
    rounded = (2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)
    digits = str(rounded).rjust(places + 1, "0")
    return f"{digits[:-places]}.{digits[-places:]}"


def format_cents(cents):
    return format_fraction(Fraction(cents, CENTS_PER_UNIT), MONEY_PLACES)


def format_optional(value, places):
    return "" if value is None else format_fraction(value, places)


def write_csv(path, campaigns):
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(OUTPUT_HEADER)
        for c in campaigns:
            writer.writerow([
                c.campaign_id,
                c.impressions,
                c.clicks,
                format_cents(c.spend_cents),
                c.conversions,
                format_optional(c.ctr, RATIO_PLACES),
                format_optional(c.cpa, MONEY_PLACES),
            ])


def main(argv=None):
    args = parse_args(argv)
    try:
        totals, bad_rows = aggregate(args.input)
    except (OSError, ValueError, csv.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    campaigns = build_campaigns(totals)
    try:
        args.output.mkdir(parents=True, exist_ok=True)
        write_csv(args.output / "top10_ctr.csv", top_by_ctr(campaigns))
        write_csv(args.output / "top10_cpa.csv", top_by_cpa(campaigns))
    except OSError as error:
        print(f"Error: cannot write results: {error}", file=sys.stderr)
        return 1
    print(f"Campaigns: {len(campaigns)}, skipped rows: {bad_rows}")
    return 0


if __name__ == "__main__":
    sys.exit(main())