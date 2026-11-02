"""Stream a large ad_data.csv once and print a data-quality summary.

Usage: python scripts/inspect_data.py [path/to/ad_data.csv] [--head 20]
"""
import argparse
import csv
import math
import sys
import time
from datetime import date

EXPECTED_COLUMNS = ["campaign_id", "date", "impressions", "clicks", "spend", "conversions"]
INT_COLUMNS = ["impressions", "clicks", "conversions"]
FLOAT_COLUMNS = ["spend"]
NUMERIC_COLUMNS = ["impressions", "clicks", "spend", "conversions"]
MAX_EXAMPLES = 5


def parse_args():
    parser = argparse.ArgumentParser(description="Summarize ad_data.csv without loading it into memory.")
    parser.add_argument("path", nargs="?", default="data/ad_data.csv",
                        help="Path to the CSV file (default: data/ad_data.csv)")
    parser.add_argument("--head", type=int, default=20, help="Number of data rows to preview (default: 20)")
    return parser.parse_args()


def parse_row(row, index):
    """Return (campaign_id, {column: number}) or raise ValueError."""
    campaign_id = row[index["campaign_id"]].strip()
    if not campaign_id:
        raise ValueError("empty campaign_id")
    date.fromisoformat(row[index["date"]].strip())
    values = {name: int(row[index[name]]) for name in INT_COLUMNS}
    for name in FLOAT_COLUMNS:
        value = float(row[index[name]])
        if not math.isfinite(value):
            raise ValueError(f"non-finite {name}: {value}")
        values[name] = value
    return campaign_id, values


def main():
    args = parse_args()
    started = time.perf_counter()

    try:
        f = open(args.path, newline="", encoding="utf-8")
    except OSError as exc:
        sys.exit(f"Cannot open {args.path}: {exc}")

    with f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            sys.exit("File is empty.")
        header = [name.strip() for name in header]
        missing = [name for name in EXPECTED_COLUMNS if name not in header]
        if missing:
            sys.exit(f"Header is missing columns {missing}; got {header}")
        index = {name: header.index(name) for name in EXPECTED_COLUMNS}

        head_rows = []
        total_rows = 0
        wrong_column_count = 0
        wrong_type = 0
        bad_examples = []
        campaign_ids = set()
        minimum = {name: None for name in NUMERIC_COLUMNS}
        maximum = {name: None for name in NUMERIC_COLUMNS}
        zero_impressions = 0
        zero_conversions = 0

        for row in reader:
            total_rows += 1
            if len(head_rows) < args.head:
                head_rows.append(row)

            if len(row) != len(header):
                wrong_column_count += 1
                if len(bad_examples) < MAX_EXAMPLES:
                    bad_examples.append((reader.line_num, f"{len(row)} columns", row))
                continue

            try:
                campaign_id, values = parse_row(row, index)
            except ValueError as exc:
                wrong_type += 1
                if len(bad_examples) < MAX_EXAMPLES:
                    bad_examples.append((reader.line_num, str(exc), row))
                continue

            campaign_ids.add(campaign_id)
            for name, value in values.items():
                if minimum[name] is None or value < minimum[name]:
                    minimum[name] = value
                if maximum[name] is None or value > maximum[name]:
                    maximum[name] = value
            if values["impressions"] == 0:
                zero_impressions += 1
            if values["conversions"] == 0:
                zero_conversions += 1

    elapsed = time.perf_counter() - started
    valid_rows = total_rows - wrong_column_count - wrong_type

    print(f"Header: {header}")
    print(f"\nFirst {len(head_rows)} data rows:")
    for row in head_rows:
        print(f"  {row}")

    print(f"\nTotal data rows:           {total_rows:,}")
    print(f"Valid rows:                {valid_rows:,}")
    print(f"Rows with wrong # columns: {wrong_column_count:,}")
    print(f"Rows with bad values:      {wrong_type:,}")
    print(f"Distinct campaign_id:      {len(campaign_ids):,}")
    print(f"Rows with impressions = 0: {zero_impressions:,}")
    print(f"Rows with conversions = 0: {zero_conversions:,}")

    print("\nNumeric ranges (valid rows only):")
    for name in NUMERIC_COLUMNS:
        print(f"  {name:<12} min={minimum[name]}  max={maximum[name]}")

    if bad_examples:
        print(f"\nFirst {len(bad_examples)} bad rows (line, reason, content):")
        for line_no, reason, row in bad_examples:
            print(f"  line {line_no}: {reason} -> {row}")

    print(f"\nElapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
