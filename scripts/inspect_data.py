"""Stream a large ad_data.csv once and print only a summary of its shape and quality."""

import argparse
import sys

EXPECTED_HEADER = ["campaign_id", "date", "impressions", "clicks", "spend", "conversions"]
NUMERIC_COLUMNS = {2: "impressions", 3: "clicks", 4: "spend", 5: "conversions"}
PREVIEW_LINES = 5


def parse_number(raw, column):
    """Return the parsed value, or None when `raw` is not a number for that column."""
    try:
        return float(raw) if column == 4 else int(raw)
    except ValueError:
        return None


def decimals_of(raw):
    _, _, fraction = raw.partition(".")
    return len(fraction)


def inspect(path):
    stats = {
        "lines": 0,
        "bytes": 0,
        "bad_column_count": 0,
        "bad_not_number": 0,
        "bad_negative": 0,
        "zero_impressions": 0,
        "max_spend_decimals": 0,
        "lines_with_quote": 0,
        "lines_with_unbalanced_quote": 0,
    }
    ranges = {name: [None, None] for name in NUMERIC_COLUMNS.values()}
    conversions_by_campaign = {}

    with open(path, "rb") as handle:
        header_line = handle.readline()
        header = header_line.decode("utf-8-sig").rstrip("\r\n").split(",")
        preview = [header_line.rstrip(b"\r\n").decode("utf-8", "replace")]

        for line in handle:
            stats["lines"] += 1
            stats["bytes"] += len(line)
            if stats["lines"] <= PREVIEW_LINES:
                preview.append(line.rstrip(b"\r\n").decode("utf-8", "replace"))

            if b'"' in line:
                stats["lines_with_quote"] += 1
                if line.count(b'"') % 2:
                    stats["lines_with_unbalanced_quote"] += 1

            fields = line.rstrip(b"\r\n").decode("utf-8", "replace").split(",")
            if len(fields) != len(EXPECTED_HEADER):
                stats["bad_column_count"] += 1
                continue

            values = {}
            row_ok = True
            for column, name in NUMERIC_COLUMNS.items():
                value = parse_number(fields[column], column)
                if value is None:
                    stats["bad_not_number"] += 1
                    row_ok = False
                    break
                values[name] = value
            if not row_ok:
                continue
            if any(value < 0 for value in values.values()):
                stats["bad_negative"] += 1
                continue

            for name, value in values.items():
                low, high = ranges[name]
                ranges[name][0] = value if low is None or value < low else low
                ranges[name][1] = value if high is None or value > high else high
            stats["max_spend_decimals"] = max(
                stats["max_spend_decimals"], decimals_of(fields[4])
            )
            if values["impressions"] == 0:
                stats["zero_impressions"] += 1
            campaign = fields[0]
            conversions_by_campaign[campaign] = (
                conversions_by_campaign.get(campaign, 0) + values["conversions"]
            )

    return header, preview, stats, ranges, conversions_by_campaign


def report(header, preview, stats, ranges, conversions_by_campaign):
    lines = stats["lines"]
    bad_total = (
        stats["bad_column_count"] + stats["bad_not_number"] + stats["bad_negative"]
    )
    zero_conversion_campaigns = sum(
        1 for total in conversions_by_campaign.values() if total == 0
    )

    print("First lines (header + data):")
    for line in preview:
        print(f"  {line}")
    print(f"Header: {header}")
    print(f"Header has exactly 6 columns: {len(header) == 6}")
    print(f"Header matches expected names: {header == EXPECTED_HEADER}")
    print(f"Data lines (excluding header): {lines}")
    print(f"Distinct campaign_id (valid rows): {len(conversions_by_campaign)}")
    print(
        f"Bad rows: {bad_total} "
        f"(wrong column count: {stats['bad_column_count']}, "
        f"not a number: {stats['bad_not_number']}, "
        f"negative: {stats['bad_negative']})"
    )
    print(f"Max decimal places in spend: {stats['max_spend_decimals']}")
    print(
        f"Lines containing a quote: {stats['lines_with_quote']} "
        f"(odd quote count, i.e. possible multi-line field: "
        f"{stats['lines_with_unbalanced_quote']})"
    )
    print(f"Average bytes per line: {stats['bytes'] / lines:.2f}" if lines else "No data lines")
    for name, (low, high) in ranges.items():
        print(f"{name}: min={low} max={high}")
    print(f"Rows with impressions = 0: {stats['zero_impressions']}")
    print(f"Campaigns with total conversions = 0: {zero_conversion_campaigns}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="data/ad_data.csv")
    args = parser.parse_args()
    try:
        report(*inspect(args.path))
    except OSError as error:
        sys.exit(f"Cannot read {args.path}: {error}")


if __name__ == "__main__":
    main()
