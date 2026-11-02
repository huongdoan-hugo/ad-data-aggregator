import csv
from fractions import Fraction

import pytest

import aggregator
from aggregator import Campaign

HEADER = "campaign_id,date,impressions,clicks,spend,conversions"


def write_input(tmp_path, lines, header=HEADER):
    path = tmp_path / "input.csv"
    path.write_text("\n".join([header, *lines]) + "\n", encoding="utf-8")
    return path


def read_output(path):
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def make_campaign(campaign_id, ctr=None, cpa=None):
    return Campaign(campaign_id, 100, 10, 1000, 5, ctr, cpa)


class TestParseCents:
    @pytest.mark.parametrize("text, expected", [
        ("0", 0),
        ("0.29", 29),
        ("12500.5", 1250050),
        ("12500.50", 1250050),
        ("100", 10000),
        ("0.1", 10),
        ("4976.81", 497681),
    ])
    def test_converts_exactly(self, text, expected):
        assert aggregator.parse_cents(text) == expected

    @pytest.mark.parametrize("text", [
        "1.234", "0.001", "nan", "inf", "abc", "", "-5.0",
        "1e2", "1e999990", "1_000", " 5", "5.", ".5",
    ])
    def test_rejects_values_that_are_not_whole_cents(self, text):
        with pytest.raises((ValueError, ArithmeticError)):
            aggregator.parse_cents(text)


class TestAggregate:
    def test_sums_rows_of_the_same_campaign(self, tmp_path):
        path = write_input(tmp_path, [
            "A,2025-01-01,1000,50,100.5,5",
            "A,2025-01-02,500,20,50.25,3",
            "B,2025-01-01,200,10,20.0,1",
        ])

        totals, bad_rows = aggregator.aggregate(path)

        assert totals["A"] == [1500, 70, 15075, 8]
        assert totals["B"] == [200, 10, 2000, 1]
        assert bad_rows == 0

    def test_spend_is_summed_without_floating_point_error(self, tmp_path):
        path = write_input(tmp_path, ["A,2025-01-01,1,1,0.1,1"] * 3 + ["A,2025-01-02,1,1,0.29,1"])

        totals, _ = aggregator.aggregate(path)

        assert totals["A"][2] == 59

    @pytest.mark.parametrize("bad_line", [
        "A,2025-01-01,abc,10,5.0,1",
        "A,2025-01-01,100,10,not-a-number,1",
        "A,2025-01-01,100,10,1.234,1",
        "A,2025-01-01,100,10,nan,1",
        "A,2025-01-01,100,10,inf,1",
        "A,2025-01-01,100,10",
        "A,2025-01-01,100,10,5.0,1,extra",
        "A,2025-01-01,-100,10,5.0,1",
        "A,2025-01-01,100,10,-5.0,1",
    ])
    def test_skips_and_counts_malformed_rows(self, tmp_path, bad_line):
        path = write_input(tmp_path, ["A,2025-01-01,100,10,5.0,1", bad_line, "B,2025-01-01,100,10,5.0,1"])

        totals, bad_rows = aggregator.aggregate(path)

        assert totals == {"A": [100, 10, 500, 1], "B": [100, 10, 500, 1]}
        assert bad_rows == 1

    def test_ignores_blank_lines(self, tmp_path):
        path = write_input(tmp_path, ["", "A,2025-01-01,100,10,5.0,1", ""])

        totals, bad_rows = aggregator.aggregate(path)

        assert list(totals) == ["A"]
        assert bad_rows == 0

    def test_rejects_unexpected_header(self, tmp_path):
        path = write_input(tmp_path, ["A,2025-01-01,100,10,5.0,1"], header="a,b,c")

        with pytest.raises(ValueError):
            aggregator.aggregate(path)

    def test_rejects_empty_file(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("", encoding="utf-8")

        with pytest.raises(ValueError):
            aggregator.aggregate(path)

    def test_header_only_file_gives_no_campaigns(self, tmp_path):
        path = write_input(tmp_path, [])

        totals, bad_rows = aggregator.aggregate(path)

        assert totals == {}
        assert bad_rows == 0


class TestBuildCampaigns:
    def test_computes_exact_ctr_and_cpa(self):
        campaigns = aggregator.build_campaigns({"A": [1000, 50, 10000, 5]})

        assert campaigns[0].ctr == Fraction(1, 20)
        assert campaigns[0].cpa == Fraction(20)

    def test_zero_impressions_has_no_ctr(self):
        campaigns = aggregator.build_campaigns({"A": [0, 0, 500, 1]})

        assert campaigns[0].ctr is None

    def test_zero_conversions_has_no_cpa(self):
        campaigns = aggregator.build_campaigns({"A": [100, 10, 500, 0]})

        assert campaigns[0].cpa is None


class TestRanking:
    def test_top_ctr_is_sorted_descending(self):
        campaigns = [
            make_campaign("A", ctr=Fraction(1, 10)),
            make_campaign("B", ctr=Fraction(3, 10)),
            make_campaign("C", ctr=Fraction(2, 10)),
        ]

        result = aggregator.top_by_ctr(campaigns)

        assert [c.campaign_id for c in result] == ["B", "C", "A"]

    def test_top_ctr_excludes_campaigns_without_ctr(self):
        campaigns = [make_campaign("A", ctr=None), make_campaign("B", ctr=Fraction(1, 10))]

        result = aggregator.top_by_ctr(campaigns)

        assert [c.campaign_id for c in result] == ["B"]

    def test_top_cpa_is_sorted_ascending(self):
        campaigns = [
            make_campaign("A", cpa=Fraction(5)),
            make_campaign("B", cpa=Fraction(1)),
            make_campaign("C", cpa=Fraction(3)),
        ]

        result = aggregator.top_by_cpa(campaigns)

        assert [c.campaign_id for c in result] == ["B", "C", "A"]

    def test_top_cpa_excludes_campaigns_without_cpa(self):
        campaigns = [make_campaign("A", cpa=None), make_campaign("B", cpa=Fraction(2))]

        result = aggregator.top_by_cpa(campaigns)

        assert [c.campaign_id for c in result] == ["B"]

    def test_returns_the_best_ten_campaigns(self):
        campaigns = [
            make_campaign(f"C{i:02d}", ctr=Fraction(i, 100), cpa=Fraction(i + 1))
            for i in range(15)
        ]

        assert [c.campaign_id for c in aggregator.top_by_ctr(campaigns)] == [f"C{i:02d}" for i in range(14, 4, -1)]
        assert [c.campaign_id for c in aggregator.top_by_cpa(campaigns)] == [f"C{i:02d}" for i in range(10)]

    def test_tie_at_the_tenth_place_is_broken_by_campaign_id(self):
        campaigns = [
            make_campaign(f"C{i:02d}", ctr=Fraction(50 - i, 100), cpa=Fraction(i + 1))
            for i in range(9)
        ]
        campaigns += [
            make_campaign("Z", ctr=Fraction(1, 100), cpa=Fraction(100)),
            make_campaign("Y", ctr=Fraction(1, 100), cpa=Fraction(100)),
        ]

        assert [c.campaign_id for c in aggregator.top_by_ctr(campaigns)][-1] == "Y"
        assert [c.campaign_id for c in aggregator.top_by_cpa(campaigns)][-1] == "Y"

    def test_exact_ties_are_broken_by_campaign_id(self):
        campaigns = [
            make_campaign("B", ctr=Fraction(1, 2), cpa=Fraction(2)),
            make_campaign("A", ctr=Fraction(1, 2), cpa=Fraction(2)),
        ]

        assert [c.campaign_id for c in aggregator.top_by_ctr(campaigns)] == ["A", "B"]
        assert [c.campaign_id for c in aggregator.top_by_cpa(campaigns)] == ["A", "B"]

    def test_ranking_uses_exact_values_that_floats_cannot_separate(self):
        slightly_higher = Fraction(10 ** 17 + 1, 3 * 10 ** 17)
        exactly_third = Fraction(1, 3)
        assert float(slightly_higher) == float(exactly_third)
        campaigns = [
            make_campaign("A", ctr=exactly_third),
            make_campaign("Z", ctr=slightly_higher),
        ]

        result = aggregator.top_by_ctr(campaigns)

        assert [c.campaign_id for c in result] == ["Z", "A"]


class TestFormatting:
    @pytest.mark.parametrize("value, places, expected", [
        (Fraction(1, 3), 4, "0.3333"),
        (Fraction(2, 3), 4, "0.6667"),
        (Fraction(0), 4, "0.0000"),
        (Fraction(551, 20000), 4, "0.0276"),
        (Fraction(1, 20), 4, "0.0500"),
        (Fraction(125005, 10), 2, "12500.50"),
        (Fraction(1, 200), 2, "0.01"),
    ])
    def test_format_fraction_rounds_half_up(self, value, places, expected):
        assert aggregator.format_fraction(value, places) == expected

    @pytest.mark.parametrize("cents, expected", [
        (0, "0.00"),
        (5, "0.05"),
        (1250050, "12500.50"),
    ])
    def test_format_cents(self, cents, expected):
        assert aggregator.format_cents(cents) == expected


class TestWriteCsv:
    def test_writes_header_and_fixed_decimal_values(self, tmp_path):
        path = tmp_path / "out.csv"
        campaign = Campaign("A", 1000, 50, 10050, 5, Fraction(1, 20), Fraction(10050, 500))

        aggregator.write_csv(path, [campaign])

        rows = read_output(path)
        assert list(rows[0]) == aggregator.OUTPUT_HEADER
        assert rows[0]["campaign_id"] == "A"
        assert rows[0]["total_spend"] == "100.50"
        assert rows[0]["CTR"] == "0.0500"
        assert rows[0]["CPA"] == "20.10"

    def test_missing_metrics_are_written_as_empty(self, tmp_path):
        path = tmp_path / "out.csv"

        aggregator.write_csv(path, [Campaign("A", 0, 0, 500, 0, None, None)])

        rows = read_output(path)
        assert rows[0]["CTR"] == ""
        assert rows[0]["CPA"] == ""


class TestMain:
    def test_end_to_end_creates_both_result_files(self, tmp_path):
        input_path = write_input(tmp_path, [
            "A,2025-01-01,1000,50,100.5,5",
            "A,2025-01-02,1000,30,50.25,0",
            "B,2025-01-01,500,40,20.0,4",
            "C,2025-01-01,0,0,5.0,0",
            "D,2025-01-01,abc,1,1.0,1",
            "E,2025-01-01,100,10,10.0,10",
        ])
        output_dir = tmp_path / "results"

        exit_code = aggregator.main(["--input", str(input_path), "--output", str(output_dir)])

        assert exit_code == 0
        by_ctr = read_output(output_dir / "top10_ctr.csv")
        by_cpa = read_output(output_dir / "top10_cpa.csv")
        assert [row["campaign_id"] for row in by_ctr] == ["E", "B", "A"]
        assert [row["campaign_id"] for row in by_cpa] == ["E", "B", "A"]
        assert by_ctr[0] == {
            "campaign_id": "E", "total_impressions": "100", "total_clicks": "10",
            "total_spend": "10.00", "total_conversions": "10", "CTR": "0.1000", "CPA": "1.00",
        }
        assert by_ctr[2]["total_impressions"] == "2000"
        assert by_ctr[2]["total_spend"] == "150.75"
        assert by_ctr[2]["CPA"] == "30.15"

    def test_missing_input_file_returns_error_code(self, tmp_path, capsys):
        exit_code = aggregator.main(["--input", str(tmp_path / "missing.csv"), "--output", str(tmp_path)])

        assert exit_code == 1
        assert "Error" in capsys.readouterr().err

    def test_unparseable_csv_returns_error_code(self, tmp_path, capsys):
        oversized_field = '"' + "1" * 200_000 + '"'
        input_path = write_input(tmp_path, [f"A,2025-01-01,{oversized_field},10,5.0,1"])

        exit_code = aggregator.main(["--input", str(input_path), "--output", str(tmp_path / "results")])

        assert exit_code == 1
        assert "Error" in capsys.readouterr().err

    def test_unwritable_output_returns_error_code(self, tmp_path, capsys):
        input_path = write_input(tmp_path, ["A,2025-01-01,100,10,5.0,1"])
        output_is_a_file = tmp_path / "results"
        output_is_a_file.write_text("", encoding="utf-8")

        exit_code = aggregator.main(["--input", str(input_path), "--output", str(output_is_a_file)])

        assert exit_code == 1
        assert "Error" in capsys.readouterr().err