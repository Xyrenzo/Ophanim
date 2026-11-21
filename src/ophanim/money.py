"""Money arithmetic used by the generator.

Rules (published in policy.json and docs/data_model.md):

* Amounts are integers in the currency's minor unit (cents, fils, yen...).
  The exponent of each currency is listed in ``CURRENCY_EXPONENTS``
  (USD 2, JPY 0, KWD 3, ...).
* FX rates are decimal strings: ``1 source unit = rate target units``.
* A document amount is converted once, as a whole:
  ``round_half_up(amount_minor / 10**src_exp * rate, dst_exp)``.
* Binary floating point is never used. A private ``decimal.Context`` with
  50 digits of precision is used so results never depend on the global context.

The independent auditor in ``ophanim.audit`` deliberately re-implements the
conversion from the published rule instead of importing this module, so a bug
here would show up as a verifier mismatch instead of being silently shared.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Context, Decimal, DivisionByZero, InvalidOperation, Overflow, localcontext

ROUNDING_MODE_NAME = "ROUND_HALF_UP"

# ISO 4217 minor-unit exponents for every currency the generator may use.
CURRENCY_EXPONENTS: dict[str, int] = {
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "CHF": 2,
    "KZT": 2,
    "CNY": 2,
    "AED": 2,
    "SGD": 2,
    "JPY": 0,
    "KWD": 3,
}

# Approximate USD value of one major unit. Used only to give generated amounts
# and rates realistic magnitudes; it is not part of any accounting rule.
USD_VALUE: dict[str, Decimal] = {
    "USD": Decimal("1"),
    "EUR": Decimal("1.08"),
    "GBP": Decimal("1.27"),
    "CHF": Decimal("1.12"),
    "KZT": Decimal("0.0020"),
    "CNY": Decimal("0.14"),
    "AED": Decimal("0.2723"),
    "SGD": Decimal("0.74"),
    "JPY": Decimal("0.0067"),
    "KWD": Decimal("3.25"),
}

_CONTEXT = Context(prec=50, rounding=ROUND_HALF_UP, traps=[InvalidOperation, DivisionByZero, Overflow])


def exponent(currency: str) -> int:
    try:
        return CURRENCY_EXPONENTS[currency]
    except KeyError:
        raise ValueError(f"unsupported currency: {currency!r}") from None


def to_decimal(amount_minor: int, currency: str) -> Decimal:
    """Exact major-unit value of a minor-unit integer."""
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise TypeError("amount_minor must be an int")
    with localcontext(_CONTEXT):
        return Decimal(amount_minor).scaleb(-exponent(currency))


def to_minor(value: Decimal, currency: str) -> int:
    """Round a major-unit Decimal to the currency's minor unit (half-up)."""
    if not isinstance(value, Decimal):
        raise TypeError("value must be a Decimal")
    exp = exponent(currency)
    with localcontext(_CONTEXT):
        quantum = Decimal(1).scaleb(-exp)
        rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
        return int(rounded.scaleb(exp))


def convert_minor(amount_minor: int, source: str, target: str, rate: Decimal) -> int:
    """Convert a whole document amount with the published rounding rule."""
    if not isinstance(rate, Decimal):
        raise TypeError("rate must be a Decimal")
    if source == target:
        if rate != 1:
            raise ValueError("same-currency conversion must use rate 1")
        return amount_minor
    with localcontext(_CONTEXT):
        return to_minor(to_decimal(amount_minor, source) * rate, target)


def normalize_rate(rate: Decimal) -> Decimal:
    """Quantize a rate to at least 6 decimals and ~7 significant digits."""
    with localcontext(_CONTEXT):
        places = max(6, 6 - rate.adjusted())
        return rate.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def rate_to_str(rate: Decimal) -> str:
    """Decimal string without exponent notation (e.g. '0.002061538')."""
    return format(rate, "f")


def format_minor(amount_minor: int, currency: str) -> str:
    """Human-readable amount, e.g. 123456 USD -> '1234.56'. Used only in prose."""
    return format(to_decimal(amount_minor, currency), "f")
