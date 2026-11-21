"""The published accounting rules, re-implemented from policy.json (stdlib only).

Deliberately NOT shared with the generator (see package docstring).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

_CTX = Context(prec=60, rounding=ROUND_HALF_UP)
_OFFSET = re.compile(r"^([+-])(\d{2}):(\d{2})$")
RATE_PATTERN = re.compile(r"^\d+\.\d+$")


class Rules:
    """Accessors for one episode's policy."""

    def __init__(self, policy: dict) -> None:
        self.policy = policy
        self.base = policy["base_currency"]
        self.tz = parse_offset(policy["timezone"])
        self.start = date.fromisoformat(policy["reporting_period"]["start"])
        self.end = date.fromisoformat(policy["reporting_period"]["end"])
        self.exponents: dict[str, int] = dict(policy["currency_exponents"])
        self.tolerance = int(policy["tolerance_minor"])
        names = {v: k for k, v in policy["accounts"].items()}
        self.ap = names["Accounts payable"]
        self.bank = names["Bank"]
        self.suspense = names["Suspense - payments awaiting identification"]
        self.fx_account = names["Realised FX gain/loss"]

    def accounting_date(self, timestamp: str) -> date:
        moment = datetime.fromisoformat(timestamp)
        if moment.tzinfo is None:
            raise ValueError(f"timestamp without offset: {timestamp}")
        return moment.astimezone(self.tz).date()

    def in_period(self, day: date) -> bool:
        return self.start <= day <= self.end

    def convert(self, amount_minor: int, currency: str, rate: Decimal) -> int:
        """round_half_up(amount_minor / 10**exp(currency) * rate, exp(base)) in base minor units."""
        with localcontext(_CTX):
            major = Decimal(amount_minor) / (Decimal(10) ** self.exponents[currency])
            base_major = major * rate
            quantum = Decimal(1) / (Decimal(10) ** self.exponents[self.base])
            rounded = base_major.quantize(quantum, rounding=ROUND_HALF_UP)
            return int(rounded * (Decimal(10) ** self.exponents[self.base]))


def parse_offset(text: str) -> timezone:
    m = _OFFSET.match(text)
    if not m:
        raise ValueError(f"bad offset {text!r}")
    sign = 1 if m.group(1) == "+" else -1
    return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))
