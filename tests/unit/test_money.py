from decimal import Decimal

import pytest

from ophanim.money import CURRENCY_EXPONENTS, convert_minor, normalize_rate, to_decimal, to_minor


def test_exponents_cover_zero_two_and_three_decimal_currencies():
    assert CURRENCY_EXPONENTS["JPY"] == 0
    assert CURRENCY_EXPONENTS["USD"] == 2
    assert CURRENCY_EXPONENTS["KWD"] == 3


def test_conversion_between_different_exponents():
    # 12,345 JPY at 0.006712 USD/JPY = 82.85964 USD -> 82.86 -> 8286 cents
    assert convert_minor(12345, "JPY", "USD", Decimal("0.006712")) == 8286
    # 1,000.00 USD at 0.307692 KWD/USD = 307.692 KWD -> 307692 fils
    assert convert_minor(100000, "USD", "KWD", Decimal("0.307692")) == 307692
    # 1.234 KWD at 3.25 USD/KWD = 4.0105 USD -> rounded to cents -> 4.01
    assert convert_minor(1234, "KWD", "USD", Decimal("3.25")) == 401


def test_half_up_rounding_at_exact_midpoint():
    # 0.05 USD at 0.5 = 0.025 -> 0.03 (half-up), not 0.02 (half-even)
    assert convert_minor(5, "USD", "EUR", Decimal("0.5")) == 3


def test_same_currency_requires_rate_one():
    assert convert_minor(999, "USD", "USD", Decimal(1)) == 999
    with pytest.raises(ValueError):
        convert_minor(999, "USD", "USD", Decimal("1.1"))


def test_no_binary_floats_accepted():
    with pytest.raises(TypeError):
        convert_minor(100, "USD", "EUR", 1.1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        to_decimal(1.5, "USD")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        to_minor(1.5, "USD")  # type: ignore[arg-type]


def test_normalized_rates_keep_significant_digits():
    assert str(normalize_rate(Decimal("1.0832151234"))) == "1.083215"
    assert str(normalize_rate(Decimal("0.00206153846"))) == "0.002061538"
    assert str(normalize_rate(Decimal("512.3456789"))) == "512.345679"
