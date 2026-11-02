"""Aggregate ad performance per campaign and write the top 10 campaigns by CTR and by CPA."""

import argparse
import collections
import contextlib
import csv
import heapq
import multiprocessing
import os
import re
import shutil
import sys
import tempfile
import zipfile
import zlib
from fractions import Fraction
from typing import NamedTuple, Optional

WORKERS = 4
RANGES = WORKERS * 4
MIN_RANGE_BYTES = 1 << 20
TOP_N = 10
SPEND_DECIMALS = 6
SPEND_SCALE = 10**SPEND_DECIMALS
REQUIRED_COLUMNS = ("campaign_id", "impressions", "clicks", "spend", "conversions")
OUTPUT_HEADER = [
    "campaign_id",
    "total_impressions",
    "total_clicks",
    "total_spend",
    "total_conversions",
    "CTR",
    "CPA",
]
DIGITS = re.compile(r"[0-9]+")
SPEND = re.compile(r"([0-9]+)(?:\.([0-9]{0,%d}))?" % SPEND_DECIMALS)
SPEND_TOO_PRECISE = re.compile(r"[0-9]+\.[0-9]{%d,}" % (SPEND_DECIMALS + 1))


class InputError(Exception):
    """The input cannot be processed at all (missing, empty, corrupt or wrong header)."""


class BadRow(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class Totals:
    """Running sums for one campaign; spend is kept as an integer number of 1e-6 USD."""

    def __init__(self):
        self.impressions = 0
        self.clicks = 0
        self.micro_spend = 0
        self.conversions = 0

    def add(self, impressions, clicks, micro_spend, conversions):
        self.impressions += impressions
        self.clicks += clicks
        self.micro_spend += micro_spend
        self.conversions += conversions

    def merge(self, other):
        self.add(other.impressions, other.clicks, other.micro_spend, other.conversions)


class Header(NamedTuple):
    data_start: int
    width: int
    columns: tuple


class RangeTask(NamedTuple):
    path: str
    start: int
    end: int
    width: int
    columns: tuple


class RangeResult(NamedTuple):
    totals: dict
    bad_rows: collections.Counter
    rows: int


class Campaign(NamedTuple):
    campaign_id: str
    impressions: int
    clicks: int
    spend: Fraction
    conversions: int
    ctr: Optional[Fraction]
    cpa: Optional[Fraction]


class Summary(NamedTuple):
    rows: int
    bad_rows: collections.Counter
    campaigns: int


class LineReader:
    """Iterate over the decoded lines of a binary file, tracking where the next line starts."""

    def __init__(self, handle, position):
        self.handle = handle
        self.position = position

    def __iter__(self):
        return self

    def __next__(self):
        line = self.handle.readline()
        if not line:
            raise StopIteration
        self.position += len(line)
        return line.decode("utf-8", "replace")


def locate_columns(header):
    """Return (column count, indices of REQUIRED_COLUMNS) for a header row."""
    names = [name.strip().lower() for name in header]
    missing = [column for column in REQUIRED_COLUMNS if column not in names]
    if missing:
        raise InputError(f"header is missing required columns: {', '.join(missing)}")
    duplicated = [column for column in REQUIRED_COLUMNS if names.count(column) > 1]
    if duplicated:
        raise InputError(f"header repeats columns: {', '.join(duplicated)}")
    return len(names), tuple(names.index(column) for column in REQUIRED_COLUMNS)


def read_header(path):
    with open(path, "rb") as handle:
        first_line = handle.readline()
        data_start = handle.tell()
    if not first_line:
        raise InputError("input file is empty")
    names = next(csv.reader([first_line.decode("utf-8-sig", "replace")]))
    return Header(data_start, *locate_columns(names))


def parse_micro_spend(text):
    match = SPEND.fullmatch(text)
    if match is None:
        if SPEND_TOO_PRECISE.fullmatch(text):
            raise BadRow("spend_over_6_decimals")
        raise BadRow("not_a_number")
    whole, fraction = match.groups()
    return int(whole) * SPEND_SCALE + int((fraction or "").ljust(SPEND_DECIMALS, "0"))


def parse_count(text):
    if DIGITS.fullmatch(text) is None:
        raise BadRow("not_a_number")
    return int(text)


def parse_row(fields, width, columns):
    """Return (campaign, impressions, clicks, micro spend, conversions) or raise BadRow."""
    if len(fields) != width:
        raise BadRow("wrong_column_count")
    campaign, impressions, clicks, spend, conversions = (fields[index] for index in columns)
    if not campaign:
        raise BadRow("empty_campaign_id")
    if any(value.startswith("-") for value in (impressions, clicks, spend, conversions)):
        raise BadRow("negative_value")
    return (
        campaign,
        parse_count(impressions),
        parse_count(clicks),
        parse_micro_spend(spend),
        parse_count(conversions),
    )


def split_ranges(data_start, file_size, count):
    """Split the bytes from data_start to file_size into up to `count` contiguous ranges."""
    data_size = file_size - data_start
    bounds = [data_start + data_size * index // count for index in range(count + 1)]
    return [(start, end) for start, end in zip(bounds, bounds[1:]) if start < end]


def plan_ranges(path, count):
    """Validate the header and return one task per non-empty byte range."""
    header = read_header(path)
    ranges = split_ranges(header.data_start, os.path.getsize(path), count)
    return [RangeTask(path, start, end, header.width, header.columns) for start, end in ranges]


def process_range(task):
    """Aggregate every row that starts inside the byte range [task.start, task.end).

    The byte before the range is read first and the rest of that line is skipped, which lands
    on the first line that starts at or after task.start. The last row may extend past task.end.
    """
    totals = collections.defaultdict(Totals)
    bad_rows = collections.Counter()
    rows = 0
    with open(task.path, "rb") as handle:
        handle.seek(task.start - 1)
        handle.readline()
        lines = LineReader(handle, handle.tell())
        reader = csv.reader(lines)
        while lines.position < task.end:
            fields = next(reader, None)
            if fields is None:
                break
            if not fields:
                continue
            rows += 1
            try:
                campaign, *values = parse_row(fields, task.width, task.columns)
            except BadRow as bad_row:
                bad_rows[bad_row.reason] += 1
                continue
            totals[campaign].add(*values)
    return RangeResult(dict(totals), bad_rows, rows)


def merge_results(results):
    """Return (totals per campaign, bad row counts, row count) summed over range results."""
    totals = collections.defaultdict(Totals)
    bad_rows = collections.Counter()
    rows = 0
    for result in results:
        for campaign, total in result.totals.items():
            totals[campaign].merge(total)
        bad_rows.update(result.bad_rows)
        rows += result.rows
    return totals, bad_rows, rows


def range_count(file_size):
    return max(1, min(RANGES, file_size // MIN_RANGE_BYTES))


def run_ranges(tasks):
    if len(tasks) <= 1:
        yield from map(process_range, tasks)
        return
    with multiprocessing.Pool(WORKERS) as pool:
        yield from pool.imap_unordered(process_range, tasks)


def aggregate(path):
    tasks = plan_ranges(path, range_count(os.path.getsize(path)))
    return merge_results(run_ranges(tasks))


def rank(totals):
    """Return (top by CTR, top by CPA).

    A campaign whose CTR (no impressions) or CPA (no conversions) is undefined keeps a blank
    value and is only left out of the ranking on that metric.
    """
    campaigns = []
    for campaign_id, total in totals.items():
        spend = Fraction(total.micro_spend, SPEND_SCALE)
        campaigns.append(
            Campaign(
                campaign_id,
                total.impressions,
                total.clicks,
                spend,
                total.conversions,
                Fraction(total.clicks, total.impressions) if total.impressions else None,
                spend / total.conversions if total.conversions else None,
            )
        )
    with_ctr = [campaign for campaign in campaigns if campaign.ctr is not None]
    with_cpa = [campaign for campaign in campaigns if campaign.cpa is not None]
    top_ctr = heapq.nsmallest(TOP_N, with_ctr, key=lambda c: (-c.ctr, c.campaign_id))
    top_cpa = heapq.nsmallest(TOP_N, with_cpa, key=lambda c: (c.cpa, c.campaign_id))
    return top_ctr, top_cpa


def format_fixed(value, places):
    """Format a non-negative Fraction with `places` decimals, rounding half up."""
    scaled = value * 10**places
    quotient, remainder = divmod(scaled.numerator, scaled.denominator)
    if 2 * remainder >= scaled.denominator:
        quotient += 1
    digits = str(quotient).rjust(places + 1, "0")
    return f"{digits[:-places]}.{digits[-places:]}"


def format_optional(value, places):
    return "" if value is None else format_fixed(value, places)


def write_top(path, campaigns):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(OUTPUT_HEADER)
        for campaign in campaigns:
            writer.writerow(
                [
                    campaign.campaign_id,
                    campaign.impressions,
                    campaign.clicks,
                    format_fixed(campaign.spend, 2),
                    campaign.conversions,
                    format_optional(campaign.ctr, 4),
                    format_optional(campaign.cpa, 2),
                ]
            )


def find_csv_member(archive, zip_path):
    members = [
        member
        for member in archive.infolist()
        if not member.is_dir()
        and member.filename.lower().endswith(".csv")
        and not member.filename.startswith("__MACOSX/")
    ]
    if len(members) != 1:
        raise InputError(f"expected exactly one .csv file in {zip_path}, found {len(members)}")
    return members[0]


def extract_csv(zip_path, target):
    try:
        with zipfile.ZipFile(zip_path) as archive:
            member = find_csv_member(archive, zip_path)
            with archive.open(member) as source, open(target, "wb") as destination:
                shutil.copyfileobj(source, destination, 1024 * 1024)
    except (zipfile.BadZipFile, zlib.error) as error:
        raise InputError(f"corrupt zip file {zip_path}: {error}") from error


@contextlib.contextmanager
def csv_file(input_path):
    """Yield the path of a plain CSV file, extracting it to a temporary directory from a zip."""
    if not os.path.isfile(input_path):
        raise InputError(f"input file not found: {input_path}")
    if not zipfile.is_zipfile(input_path):
        yield input_path
        return
    with tempfile.TemporaryDirectory() as directory:
        target = os.path.join(directory, "input.csv")
        extract_csv(input_path, target)
        yield target


def run(input_path, output_dir):
    with csv_file(input_path) as path:
        totals, bad_rows, rows = aggregate(path)
    top_ctr, top_cpa = rank(totals)
    os.makedirs(output_dir, exist_ok=True)
    write_top(os.path.join(output_dir, "top10_ctr.csv"), top_ctr)
    write_top(os.path.join(output_dir, "top10_cpa.csv"), top_cpa)
    return Summary(rows, bad_rows, len(totals))


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="path to ad_data.csv or ad_data.csv.zip")
    parser.add_argument(
        "--output", required=True, help="directory for top10_ctr.csv and top10_cpa.csv"
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        summary = run(args.input, args.output)
    except (InputError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Read {summary.rows} data rows, {summary.campaigns} campaigns.")
    print(f"Skipped {sum(summary.bad_rows.values())} bad rows {dict(summary.bad_rows)}.")
    print(f"Wrote top10_ctr.csv and top10_cpa.csv to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
