import datetime as dt
from decimal import Decimal

import pytest

from finagent.ingest.bank_csv import parse_bank_csv
from finagent.ingest.common import infer_dayfirst, parse_amount, parse_date


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("12.50", Decimal("12.50")),
        ("-12.50", Decimal("-12.50")),
        ("£1,234.56", Decimal("1234.56")),
        ("$ -9.99", Decimal("-9.99")),
        ("(45.00)", Decimal("-45.00")),
        ("12.00-", Decimal("-12.00")),
        ("100.00 DR", Decimal("-100.00")),
        ("100.00CR", Decimal("100.00")),
        ("1.234,56", Decimal("1234.56")),
        ("-7,5", Decimal("-7.50")),
        ("", None),
        ("abc", None),
        (None, None),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_infer_dayfirst():
    assert infer_dayfirst(["01/02/2026", "25/02/2026"]) is True
    assert infer_dayfirst(["01/02/2026", "02/25/2026"]) is False
    assert infer_dayfirst(["01/02/2026"], default=False) is False


def test_parse_date_iso_not_affected_by_dayfirst():
    assert parse_date("2026-03-04", dayfirst=True) == dt.date(2026, 3, 4)


def test_single_amount_column():
    csv = "Date,Description,Amount\n31/01/2026,Coffee beans,-20.00\n01/02/2026,Card sales,150\n"
    st = parse_bank_csv(csv)
    assert [r.amount for r in st.rows] == [Decimal("-20.00"), Decimal("150.00")]
    assert st.rows[0].date == dt.date(2026, 1, 31)


def test_debit_credit_columns_us_dates():
    csv = (
        "Posting Date,Payee,Money Out,Money In\n"
        "02/25/2026,STAPLES,45.10,\n"
        "02/26/2026,STRIPE PAYOUT,,300.00\n"
    )
    st = parse_bank_csv(csv)
    assert st.rows[0].date == dt.date(2026, 2, 25)
    assert st.rows[0].amount == Decimal("-45.10")
    assert st.rows[1].amount == Decimal("300.00")


def test_preamble_semicolon_and_decimal_comma():
    csv = (
        "Account;12345678\n"
        "Period;Jan 2026\n"
        "\n"
        "Booking Date;Narrative;Amount (EUR)\n"
        "15.01.2026;Miete Januar;-1.200,00\n"
        "16.01.2026;Kartenzahlung;35,90\n"
    )
    st = parse_bank_csv(csv)
    assert len(st.rows) == 2
    assert st.rows[0].amount == Decimal("-1200.00")
    assert st.rows[0].date == dt.date(2026, 1, 15)


def test_type_column_sets_sign():
    csv = "Date,Description,Amount,Type\n2026-01-05,Supplier,50.00,DEBIT\n2026-01-06,Client,80,CR\n"
    st = parse_bank_csv(csv)
    assert [r.amount for r in st.rows] == [Decimal("-50.00"), Decimal("80.00")]


def test_bad_rows_are_skipped_not_fatal():
    csv = "Date,Description,Amount\nnot-a-date,x,1.00\n2026-01-01,ok,2.00\n2026-01-02,zero,0\n"
    st = parse_bank_csv(csv)
    assert len(st.rows) == 1
    assert st.skipped == 2


def test_missing_header_raises():
    with pytest.raises(ValueError):
        parse_bank_csv("foo,bar\n1,2\n")


def test_sample_file_parses(sample_csv):
    st = parse_bank_csv(sample_csv)
    assert len(st.rows) > 300
    assert st.skipped == 0
