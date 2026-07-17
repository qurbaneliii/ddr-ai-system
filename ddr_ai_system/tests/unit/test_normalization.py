from __future__ import annotations

from ddr_ai.common.numbers import normalize_number
from ddr_ai.pdf.filename import parse_ddr_filename
from ddr_ai.pdf.parser import operation_duration_hours, reconstruct_wrapped_cell


def test_source_sentinels_become_null_and_preserve_raw() -> None:
    for raw in ("-999.99", "-999.9"):
        value = normalize_number(raw)
        assert value.value is None
        assert value.raw_value == raw
        assert value.missing_reason == "source_sentinel"


def test_decimal_comma_numeric_context() -> None:
    value = normalize_number("8,8")
    assert value.value == 8.8
    assert value.raw_value == "8,8"


def test_wrapped_cell_reconstruction_is_cell_local() -> None:
    assert reconstruct_wrapped_cell("surv\ney", compact=True) == "survey"
    assert reconstruct_wrapped_cell("circulatin\ng conditioning", compact=True) == "circulating conditioning"


def test_midnight_operation_duration() -> None:
    assert operation_duration_hours("23:00", "00:00") == 1.0
    assert operation_duration_hours("00:00", "01:30") == 1.5


def test_filename_identity_variants_and_utf8() -> None:
    parsed = parse_ddr_filename("15_9_F_11_A_2008_01_02.pdf")
    assert parsed is not None
    assert parsed.wellbore == "15/9-F-11 A"
    assert "MÆRSK".casefold() == "mærsk"

