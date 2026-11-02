import csv
import io
import os
import sys
import zipfile
from decimal import Decimal
from fractions import Fraction

import pytest

import aggregator

HEADER = "campaign_id,date,impressions,clicks,spend,conversions\n"
OUTPUT_HEADER = [
    "campaign_id",
    "total_impressions",
    "total_clicks",
    "total_spend",
    "total_conversions",
    "CTR",
    "CPA",
]


@pytest.fixture
def write_input(tmp_path):
    def write(content, name="ad_data.csv"):
        path = tmp_path / name
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return str(path)

    return write


@pytest.fixture
def run_aggregator(tmp_path):
    def run(path, **kwargs):
        output = tmp_path / "out"
        summary = aggregator.run(path, str(output), **kwargs)

        def read(name):
            with open(output / name, newline="", encoding="utf-8") as handle:
                return list(csv.reader(handle))

        return summary, read("top10_ctr.csv"), read("top10_cpa.csv")

    return run


def ids(table):
    return [row[0] for row in table[1:]]


@pytest.mark.parametrize(
    "value, places, expected",
    [
        (Fraction(1, 8), 2, "0.13"),
        (Fraction(3, 8), 2, "0.38"),
        (Fraction(7444, 10), 2, "744.40"),
        (Fraction(1, 20000), 4, "0.0001"),
        (Fraction(0), 4, "0.0000"),
        (Fraction(99995, 10000), 2, "10.00"),
    ],
)
def test_format_fixed_rounds_half_up_and_pads(value, places, expected):
    assert aggregator.format_fixed(value, places) == expected


class TestAggregation:
    def test_totals_ctr_cpa_and_output_format(self, write_input, run_aggregator):
        path = write_input(
            HEADER
            + "A,2025-01-01,1000,50,100.5,5\n"
            + "A,2025-01-02,1000,50,99.5,5\n"
            + "B,2025-01-01,3000,30,60,3\n"
        )
        summary, by_ctr, by_cpa = run_aggregator(path)
        assert by_ctr[0] == OUTPUT_HEADER
        assert by_ctr[1] == ["A", "2000", "100", "200.00", "10", "0.0500", "20.00"]
        assert by_ctr[2] == ["B", "3000", "30", "60.00", "3", "0.0100", "20.00"]
        assert (summary.rows, summary.campaigns) == (3, 2)
        assert ids(by_cpa) == ["A", "B"]

    def test_ctr_is_aggregate_not_mean_of_row_ctrs(self, write_input, run_aggregator):
        path = write_input(HEADER + "A,d,100,50,1,1\nA,d,10000,10,1,1\n")
        _, by_ctr, _ = run_aggregator(path)
        assert by_ctr[1][5] == "0.0059"

    def test_spend_sums_exactly(self, write_input, run_aggregator):
        path = write_input(HEADER + "A,d,10,1,0.1,1\n" * 30)
        _, by_ctr, _ = run_aggregator(path)
        assert by_ctr[1][3] == "3.00"

    def test_ranking_uses_exact_values_not_rounded_ones(self, write_input, run_aggregator):
        path = write_input(HEADER + "LOW,d,1000000,50000,1,1\nHIGH,d,1000000,50001,1,1\n")
        _, by_ctr, _ = run_aggregator(path)
        assert ids(by_ctr) == ["HIGH", "LOW"]
        assert by_ctr[1][5] == by_ctr[2][5]

    def test_ctr_values_that_floats_cannot_tell_apart_are_ranked_exactly(
        self, write_input, run_aggregator
    ):
        lower = Fraction(1, 3)
        higher = Fraction(33333333333333334, 10**17)
        assert float(lower) == float(higher) and lower < higher
        path = write_input(HEADER + "A,d,3,1,1,1\nZ,d,100000000000000000,33333333333333334,1,1\n")
        _, by_ctr, _ = run_aggregator(path)
        assert ids(by_ctr) == ["Z", "A"]

    def test_cpa_values_that_floats_cannot_tell_apart_are_ranked_exactly(
        self, write_input, run_aggregator
    ):
        lower = Fraction(1, 3)
        higher = Fraction(33333333333333334, 10**17)
        assert float(lower) == float(higher) and lower < higher
        path = write_input(HEADER + "A,d,10,1,33333333333.333334,100000000000\nZ,d,10,1,1,3\n")
        _, _, by_cpa = run_aggregator(path)
        assert ids(by_cpa) == ["Z", "A"]

    def test_ties_break_on_campaign_id(self, write_input, run_aggregator):
        path = write_input(HEADER + "C,d,100,10,10,1\nA,d,100,10,10,1\nB,d,100,10,10,1\n")
        _, by_ctr, by_cpa = run_aggregator(path)
        assert ids(by_ctr) == ["A", "B", "C"]
        assert ids(by_cpa) == ["A", "B", "C"]

    def test_keeps_only_ten_and_orders_cpa_ascending(self, write_input, run_aggregator):
        rows = "".join(f"C{i:02d},d,1000,10,{100 + i},1\n" for i in range(15))
        _, by_ctr, by_cpa = run_aggregator(write_input(HEADER + rows))
        assert len(by_ctr) == 11
        assert ids(by_cpa) == [f"C{i:02d}" for i in range(10)]

    def test_zero_conversions_keeps_blank_cpa_and_leaves_cpa_ranking(
        self, write_input, run_aggregator
    ):
        path = write_input(HEADER + "OK,d,100,10,10,1\nNOCONV,d,100,90,10,0\n")
        _, by_ctr, by_cpa = run_aggregator(path)
        assert by_ctr[1] == ["NOCONV", "100", "90", "10.00", "0", "0.9000", ""]
        assert by_ctr[2][0] == "OK"
        assert ids(by_cpa) == ["OK"]

    def test_zero_impressions_keeps_blank_ctr_and_leaves_ctr_ranking(
        self, write_input, run_aggregator
    ):
        path = write_input(HEADER + "OK,d,100,10,10,1\nNOIMPR,d,0,0,10,5\n")
        _, by_ctr, by_cpa = run_aggregator(path)
        assert ids(by_ctr) == ["OK"]
        assert by_cpa[1] == ["NOIMPR", "0", "0", "10.00", "5", "", "2.00"]

    def test_campaign_with_neither_metric_is_in_no_ranking(self, write_input, run_aggregator):
        path = write_input(HEADER + "A,d,0,0,10,0\n")
        summary, by_ctr, by_cpa = run_aggregator(path)
        assert summary.campaigns == 1
        assert by_ctr == [OUTPUT_HEADER]
        assert by_cpa == [OUTPUT_HEADER]


class TestParsing:
    def test_each_kind_of_bad_row_is_counted_and_skipped(self, write_input, run_aggregator):
        path = write_input(
            HEADER
            + "A,d,100,10,10,1\n"
            + "A,d,100,10\n"
            + "A,d,abc,10,10,1\n"
            + "A,d,100,10,1e3,1\n"
            + "A,d,-5,10,10,1\n"
            + "A,d,100,10,-1.5,1\n"
            + ",d,100,10,10,1\n"
            + "A,d,100,10,0.1234567,1\n"
            + "A,d,100,10,10,\n"
        )
        summary, _, _ = run_aggregator(path)
        assert dict(summary.bad_rows) == {
            "wrong_column_count": 1,
            "not_a_number": 3,
            "negative_value": 2,
            "empty_campaign_id": 1,
            "spend_over_6_decimals": 1,
        }
        assert summary.rows == 9

    @pytest.mark.parametrize(
        "row, reason",
        [
            ("A,d,100,10,nan,1", "not_a_number"),
            ("A,d,100,10,NaN,1", "not_a_number"),
            ("A,d,100,10,inf,1", "not_a_number"),
            ("A,d,100,10,Infinity,1", "not_a_number"),
            ("A,d,nan,10,10,1", "not_a_number"),
            ("A,d,100,inf,10,1", "not_a_number"),
            ("A,d,100,10,10,nan", "not_a_number"),
            ("A,d,100,10,-inf,1", "negative_value"),
        ],
    )
    def test_nan_and_infinity_are_rejected_not_aggregated(
        self, write_input, run_aggregator, row, reason
    ):
        path = write_input(HEADER + "OK,d,100,10,10,1\n" + row + "\n")
        summary, by_ctr, _ = run_aggregator(path)
        assert dict(summary.bad_rows) == {reason: 1}
        assert ids(by_ctr) == ["OK"]
        assert by_ctr[1][3] == "10.00"

    @pytest.mark.parametrize(
        "spend, expected_total",
        [("5", "5.00"), ("5.", "5.00"), ("0.125", "0.13"), ("0.001", "0.00"), ("7.654321", "7.65")],
    )
    def test_spend_with_any_decimals_up_to_six_is_accepted(
        self, write_input, run_aggregator, spend, expected_total
    ):
        path = write_input(HEADER + f"A,d,100,10,{spend},1\n")
        summary, by_ctr, _ = run_aggregator(path)
        assert dict(summary.bad_rows) == {}
        assert by_ctr[1][3] == expected_total

    @pytest.mark.parametrize("digits", ["١٢٣", "１２３", "²"])
    def test_non_ascii_digits_are_not_numbers(self, write_input, run_aggregator, digits):
        path = write_input(HEADER + f"A,d,{digits},10,10,1\nB,d,100,10,10,1\n")
        summary, by_ctr, _ = run_aggregator(path)
        assert dict(summary.bad_rows) == {"not_a_number": 1}
        assert ids(by_ctr) == ["B"]

    def test_bom_and_crlf_together(self, write_input, run_aggregator):
        text = (HEADER + "A,d,100,10,10,1\nB,d,100,20,10,1\n").replace("\n", "\r\n")
        summary, by_ctr, _ = run_aggregator(write_input(b"\xef\xbb\xbf" + text.encode()))
        assert dict(summary.bad_rows) == {}
        assert ids(by_ctr) == ["B", "A"]

    def test_date_column_is_optional(self, write_input, run_aggregator):
        path = write_input("campaign_id,impressions,clicks,spend,conversions\nA,100,10,10,1\n")
        _, by_ctr, _ = run_aggregator(path)
        assert by_ctr[1] == ["A", "100", "10", "10.00", "1", "0.1000", "10.00"]

    def test_blank_lines_are_ignored(self, write_input, run_aggregator):
        path = write_input(HEADER + "A,d,100,10,10,1\n\n\nA,d,100,10,10,1\n\n")
        summary, _, _ = run_aggregator(path)
        assert (summary.rows, dict(summary.bad_rows)) == (2, {})

    def test_unterminated_quote_costs_one_row_not_the_rows_after_it(
        self, write_input, run_aggregator
    ):
        rows = sample_rows(300)
        text = HEADER + "\n".join(rows[:100]) + '\nA,d,100,10,"10,1\n' + "\n".join(rows[100:]) + "\n"
        path = write_input(text)
        summary, _, _ = run_aggregator(path)
        totals, _, _ = aggregator.aggregate(path)
        assert dict(summary.bad_rows) == {"wrong_column_count": 1}
        assert summary.rows == 301
        assert totals_as_tuples(totals) == expected_totals(rows)

    def test_two_stray_quotes_that_pair_up_do_not_hide_the_rows_between_them(
        self, write_input, run_aggregator
    ):
        path = write_input(
            HEADER + 'A,d,100,10,"10,1\nB,d,100,20,10,1\nC,d,"5,1\nD,d,100,30,10,1\n'
        )
        summary, _, _ = run_aggregator(path)
        totals, _, _ = aggregator.aggregate(path)
        assert sorted(totals) == ["B", "D"]
        assert sum(summary.bad_rows.values()) == 2

    def test_quoted_field_over_the_csv_field_limit_is_a_bad_row(self, write_input, run_aggregator):
        oversized = 'A,d,100,10,"' + "x" * 50000 + "\n" + "y" * 50000 + "\n" + "z" * 50000 + '",1\n'
        path = write_input(HEADER + oversized + "B,d,100,20,10,1\n")
        summary, by_ctr, _ = run_aggregator(path)
        assert summary.bad_rows["malformed_row"] >= 1
        assert ids(by_ctr) == ["B"]

    def test_line_longer_than_the_limit_is_an_input_error(self, tmp_path, write_input):
        path = write_input(HEADER + "A,d,100,10,10,1\n" + "x" * (aggregator.MAX_LINE_BYTES + 10) + "\n")
        with pytest.raises(aggregator.InputError, match="longer than 65536 bytes"):
            aggregator.run(path, str(tmp_path))

    def test_surrounding_spaces_in_campaign_id_are_ignored_but_numbers_stay_strict(
        self, write_input, run_aggregator
    ):
        path = write_input(HEADER + " A ,d,100,10,10,1\nA,d,100,10,10,1\nA,d, 100,10,10,1\n")
        summary, by_ctr, _ = run_aggregator(path)
        assert ids(by_ctr) == ["A"]
        assert by_ctr[1][1] == "200"
        assert dict(summary.bad_rows) == {"not_a_number": 1}

    def test_campaign_ids_differ_by_letter_case(self, write_input, run_aggregator):
        path = write_input(HEADER + "a,d,100,10,10,1\nA,d,100,10,10,1\n")
        _, by_ctr, _ = run_aggregator(path)
        assert sorted(ids(by_ctr)) == ["A", "a"]

    def test_spend_with_up_to_six_decimals_is_exact(self, write_input, run_aggregator):
        path = write_input(HEADER + "A,d,100,10,0.000001,1\nA,d,100,10,0.999999,1\n")
        _, by_ctr, _ = run_aggregator(path)
        assert by_ctr[1][3] == "1.00"

    def test_utf8_bom_in_header(self, write_input, run_aggregator):
        path = write_input(b"\xef\xbb\xbf" + HEADER.encode() + b"A,d,100,10,10,1\n")
        summary, by_ctr, _ = run_aggregator(path)
        assert dict(summary.bad_rows) == {}
        assert ids(by_ctr) == ["A"]

    def test_crlf_line_endings(self, write_input, run_aggregator):
        text = (HEADER + "A,d,100,10,10,1\nB,d,100,20,10,1\n").replace("\n", "\r\n")
        summary, by_ctr, _ = run_aggregator(write_input(text))
        assert dict(summary.bad_rows) == {}
        assert ids(by_ctr) == ["B", "A"]

    def test_quoted_fields_with_comma_and_embedded_newline(self, write_input, run_aggregator):
        path = write_input(
            HEADER + '"A,1",d,100,10,10,1\n"B\n2",d,100,20,"10.0",1\nC,d,"100",10,10,1\n'
        )
        summary, by_ctr, _ = run_aggregator(path)
        assert dict(summary.bad_rows) == {}
        assert set(ids(by_ctr)) == {"A,1", "B\n2", "C"}

    def test_columns_may_be_reordered_and_extra_columns_ignored(self, write_input, run_aggregator):
        path = write_input(
            "Spend,extra,Conversions,campaign_id,Clicks,impressions\n10,x,1,A,10,100\n"
        )
        _, by_ctr, _ = run_aggregator(path)
        assert by_ctr[1] == ["A", "100", "10", "10.00", "1", "0.1000", "10.00"]


class TestInputHandling:
    def test_missing_input(self, tmp_path):
        with pytest.raises(aggregator.InputError, match="not found"):
            aggregator.run(str(tmp_path / "nope.csv"), str(tmp_path))

    def test_empty_file(self, tmp_path, write_input):
        with pytest.raises(aggregator.InputError, match="empty"):
            aggregator.run(write_input(""), str(tmp_path))

    def test_header_missing_column(self, tmp_path, write_input):
        path = write_input("campaign_id,date,impressions,clicks,spend\nA,d,1,1,1\n")
        with pytest.raises(aggregator.InputError, match="conversions"):
            aggregator.run(path, str(tmp_path))

    def test_blank_first_line_is_a_header_error(self, tmp_path, write_input):
        with pytest.raises(aggregator.InputError, match="missing required columns"):
            aggregator.run(write_input("\nA,d,100,10,10,1\n"), str(tmp_path))

    def test_binary_garbage_header_is_an_input_error(self, tmp_path, write_input):
        path = write_input(b"\x00\r\x01\xff\nabc\n")
        with pytest.raises(aggregator.InputError, match="not valid CSV"):
            aggregator.run(path, str(tmp_path))

    def test_file_without_line_breaks_is_rejected_after_a_bounded_read(
        self, monkeypatch, tmp_path, write_input
    ):
        monkeypatch.setattr(aggregator, "MAX_LINE_BYTES", 64)
        with pytest.raises(aggregator.InputError, match="longer than 64 bytes"):
            aggregator.run(write_input(b"x" * 1000), str(tmp_path))

    def test_header_with_duplicate_column(self, tmp_path, write_input):
        path = write_input("campaign_id,impressions,clicks,spend,conversions,clicks\n")
        with pytest.raises(aggregator.InputError, match="clicks"):
            aggregator.run(path, str(tmp_path))

    def test_header_only_writes_header_only_outputs(self, write_input, run_aggregator):
        summary, by_ctr, by_cpa = run_aggregator(write_input(HEADER))
        assert (summary.rows, summary.campaigns) == (0, 0)
        assert by_ctr == [OUTPUT_HEADER]
        assert by_cpa == [OUTPUT_HEADER]

    def test_zip_input_matches_csv_input(self, tmp_path, write_input, run_aggregator):
        csv_path = write_input(HEADER + "A,d,100,10,10,1\nB,d,100,20,10,1\n")
        zip_path = tmp_path / "ad_data.csv.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(csv_path, "ad_data.csv")
        _, from_csv, _ = run_aggregator(csv_path)
        _, from_zip, _ = run_aggregator(str(zip_path))
        assert from_zip == from_csv

    def test_zip_without_exactly_one_csv(self, tmp_path):
        zip_path = tmp_path / "bad.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("notes.txt", "hello")
        with pytest.raises(aggregator.InputError, match="exactly one"):
            aggregator.run(str(zip_path), str(tmp_path))

    def test_truncated_zip(self, tmp_path, write_input):
        csv_path = write_input(HEADER + "A,d,100,10,10,1\n" * 50)
        zip_path = tmp_path / "ad_data.csv.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(csv_path, "ad_data.csv")
        content = zip_path.read_bytes()
        truncated = write_input(content[: len(content) // 2], name="truncated.zip")
        with pytest.raises(aggregator.InputError):
            aggregator.run(truncated, str(tmp_path))


def sample_rows(count):
    return [
        f"C{i % 9},2025-01-01,{1000 + i},{i % 40 + 1},{i % 17}.{i % 100:02d},{i % 6}"
        for i in range(count)
    ]


def expected_totals(rows):
    totals = {}
    for row in rows:
        campaign, _, impressions, clicks, spend, conversions = row.split(",")
        current = totals.setdefault(campaign, [0, 0, 0, 0])
        current[0] += int(impressions)
        current[1] += int(clicks)
        current[2] += int(Decimal(spend) * 10**6)
        current[3] += int(conversions)
    return {campaign: tuple(values) for campaign, values in totals.items()}


def totals_as_tuples(totals):
    return {
        campaign: (total.impressions, total.clicks, total.micro_spend, total.conversions)
        for campaign, total in totals.items()
    }


def half_up(numerator, denominator, places):
    scaled = (2 * numerator * 10**places + denominator) // (2 * denominator)
    digits = str(scaled).rjust(places + 1, "0")
    return f"{digits[:-places]}.{digits[-places:]}"


def expected_tables(rows):
    entries = []
    for campaign, (impressions, clicks, micro_spend, conversions) in expected_totals(rows).items():
        spend = Fraction(micro_spend, 10**6)
        entries.append(
            (
                campaign,
                impressions,
                clicks,
                spend,
                conversions,
                Fraction(clicks, impressions),
                spend / conversions if conversions else None,
            )
        )

    def line(entry):
        campaign, impressions, clicks, spend, conversions, ctr, cpa = entry
        return [
            campaign,
            str(impressions),
            str(clicks),
            half_up(spend.numerator, spend.denominator, 2),
            str(conversions),
            half_up(ctr.numerator, ctr.denominator, 4),
            "" if cpa is None else half_up(cpa.numerator, cpa.denominator, 2),
        ]

    by_ctr = sorted(entries, key=lambda e: (-e[5], e[0]))[:10]
    by_cpa = sorted((e for e in entries if e[6] is not None), key=lambda e: (e[6], e[0]))[:10]
    return [OUTPUT_HEADER] + [line(e) for e in by_ctr], [OUTPUT_HEADER] + [line(e) for e in by_cpa]


LINE_STYLES = {
    "lf": ("\n", True),
    "crlf": ("\r\n", True),
    "no_final_newline": ("\n", False),
}


class TestRanges:
    @pytest.mark.parametrize("style", LINE_STYLES)
    @pytest.mark.parametrize("count", [1, 2, 3, 4, 7, 16, 64, 1000])
    def test_every_row_is_counted_exactly_once(self, write_input, style, count):
        newline, final_newline = LINE_STYLES[style]
        rows = sample_rows(120)
        text = HEADER.replace("\n", newline) + newline.join(rows) + (newline if final_newline else "")
        tasks = aggregator.plan_ranges(write_input(text), count)
        data_size = len(text.encode()) - len(HEADER.replace("\n", newline).encode())
        results = [aggregator.process_range(task) for task in tasks]
        totals, bad_rows, row_count = aggregator.merge_results(results)
        assert len(tasks) == min(count, data_size)
        assert row_count == 120
        assert dict(bad_rows) == {}
        assert totals_as_tuples(totals) == expected_totals(rows)

    @pytest.mark.parametrize("count", [1, 3, 8, 50, 500])
    def test_bad_and_blank_rows_are_counted_once_across_ranges(self, write_input, count):
        rows = sample_rows(60)
        lines = []
        for index, row in enumerate(rows):
            lines.append(row)
            if index % 10 == 0:
                lines.append("X,d,oops,1,1,1")
            if index % 15 == 0:
                lines.append("")
        path = write_input(HEADER + "\n".join(lines) + "\n")
        results = [aggregator.process_range(task) for task in aggregator.plan_ranges(path, count)]
        totals, bad_rows, row_count = aggregator.merge_results(results)
        assert dict(bad_rows) == {"not_a_number": 6}
        assert row_count == 66
        assert totals_as_tuples(totals) == expected_totals(rows)

    def test_each_range_keeps_only_rows_that_start_in_it(self, write_input):
        first, second, third = "A,d,1,1,1,1\n", "B,d,2,1,1,1\n", "C,d,4,1,1,1\n"
        path = write_input(HEADER + first + second + third)
        header = aggregator.read_header(path)
        size = os.path.getsize(path)
        second_start = header.data_start + len(first)
        third_start = second_start + len(second)

        def campaigns_per_range(bounds):
            tasks = [
                aggregator.RangeTask(path, start, end, header.width, header.columns)
                for start, end in bounds
            ]
            return [sorted(aggregator.process_range(task).totals) for task in tasks]

        on_line_starts = [(header.data_start, second_start), (second_start, third_start), (third_start, size)]
        assert campaigns_per_range(on_line_starts) == [["A"], ["B"], ["C"]]
        inside_second_line = [(header.data_start, second_start + 1), (second_start + 1, size)]
        assert campaigns_per_range(inside_second_line) == [["A", "B"], ["C"]]

    def test_split_ranges_are_contiguous_and_cover_the_data(self):
        assert aggregator.split_ranges(10, 110, 4) == [(10, 35), (35, 60), (60, 85), (85, 110)]
        assert aggregator.split_ranges(10, 13, 8) == [(10, 11), (11, 12), (12, 13)]
        assert aggregator.split_ranges(10, 10, 4) == []

    def test_header_only_file_has_no_ranges(self, write_input):
        path = write_input(HEADER)
        assert aggregator.plan_ranges(path, 16) == []
        assert aggregator.merge_results([])[2] == 0

    def test_range_count_is_capped_and_small_files_stay_in_one_range(self):
        assert aggregator.RANGE_COUNT == aggregator.WORKERS * 4
        assert aggregator.range_count(10) == 1
        assert aggregator.range_count(10**12) == aggregator.RANGE_COUNT


class TestPool:
    def test_four_workers_give_the_expected_tables(
        self, monkeypatch, write_input, run_aggregator
    ):
        monkeypatch.setattr(aggregator, "MIN_RANGE_BYTES", 1)
        pools = []
        real_pool = aggregator.multiprocessing.Pool

        def recording_pool(processes):
            pools.append(processes)
            return real_pool(processes)

        monkeypatch.setattr(aggregator.multiprocessing, "Pool", recording_pool)
        rows = sample_rows(2000)
        path = write_input(HEADER + "\n".join(rows) + "\n")
        summary, by_ctr, by_cpa = run_aggregator(path)
        expected_ctr, expected_cpa = expected_tables(rows)
        assert pools == [4]
        assert len(aggregator.plan_ranges(path, aggregator.range_count(os.path.getsize(path)))) == 16
        assert (summary.rows, summary.campaigns) == (2000, 9)
        assert by_ctr == expected_ctr
        assert by_cpa == expected_cpa


    def test_zip_input_through_the_pool(
        self, monkeypatch, tmp_path, write_input, run_aggregator
    ):
        monkeypatch.setattr(aggregator, "MIN_RANGE_BYTES", 1)
        rows = sample_rows(1500)
        csv_path = write_input(HEADER + "\n".join(rows) + "\n")
        zip_path = tmp_path / "ad_data.csv.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(csv_path, "ad_data.csv")
        summary, by_ctr, by_cpa = run_aggregator(str(zip_path))
        assert (by_ctr, by_cpa) == expected_tables(rows)
        assert summary.rows == 1500


class TestCommandLine:
    def test_exit_codes(self, tmp_path, write_input):
        path = write_input(HEADER + "A,d,100,10,10,1\n")
        output = str(tmp_path / "out")
        assert aggregator.main(["--input", path, "--output", output]) == 0
        missing = str(tmp_path / "x.csv")
        assert aggregator.main(["--input", missing, "--output", output]) == 1
        with pytest.raises(SystemExit):
            aggregator.main(["--input", path])

    def test_non_csv_input_is_a_clean_error_without_traceback(
        self, tmp_path, write_input, capsys
    ):
        path = write_input(b"\x00\r\x01\xff\nabc\n")
        assert aggregator.main(["--input", path, "--output", str(tmp_path / "out")]) == 1
        error_output = capsys.readouterr().err
        assert error_output.startswith("error:")
        assert "Traceback" not in error_output

    def test_output_path_that_stdout_cannot_encode_does_not_crash(
        self, monkeypatch, tmp_path, write_input
    ):
        pipe = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr(sys, "stdout", pipe)
        path = write_input(HEADER + "A,d,100,10,10,1\n")
        output = tmp_path / "kết_quả"
        assert aggregator.main(["--input", path, "--output", str(output)]) == 0
        pipe.flush()
        assert b"k?t_qu?" in pipe.buffer.getvalue()
        assert (output / "top10_ctr.csv").is_file()

    def test_summary_goes_to_stdout_and_errors_to_stderr(self, tmp_path, write_input, capsys):
        path = write_input(HEADER + "A,d,100,10,10,1\nA,d,abc,10,10,1\n")
        output = str(tmp_path / "out")
        assert aggregator.main(["--input", path, "--output", output]) == 0
        printed = capsys.readouterr()
        assert "Read 2 data rows, 1 campaigns." in printed.out
        assert "Skipped 1 bad rows {'not_a_number': 1}." in printed.out
        assert printed.err == ""
        assert aggregator.main(["--input", str(tmp_path / "x.csv"), "--output", output]) == 1
        assert "input file not found" in capsys.readouterr().err

    def test_output_path_that_is_a_file_is_an_error(self, tmp_path, write_input, capsys):
        taken = tmp_path / "taken"
        taken.write_text("not a directory")
        path = write_input(HEADER + "A,d,100,10,10,1\n")
        assert aggregator.main(["--input", path, "--output", str(taken)]) == 1
        assert capsys.readouterr().err.startswith("error:")

    def test_nested_output_directory_is_created_and_old_results_are_replaced(
        self, tmp_path, write_input
    ):
        output = tmp_path / "a" / "b"
        first = write_input(HEADER + "A,d,100,10,10,1\n", name="first.csv")
        second = write_input(HEADER + "B,d,100,10,10,1\n", name="second.csv")
        assert aggregator.main(["--input", first, "--output", str(output)]) == 0
        assert aggregator.main(["--input", second, "--output", str(output)]) == 0
        with open(output / "top10_ctr.csv", newline="", encoding="utf-8") as handle:
            assert ids(list(csv.reader(handle))) == ["B"]
