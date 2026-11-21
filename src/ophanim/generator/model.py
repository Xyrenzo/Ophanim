"""Internal (hidden) model of one company's accounts-payable history.

Keys such as "I0007" or "R00042" are internal. They never leave the evaluator:
the presentation layer maps them to random public ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from ophanim.timeutil import local_date

# Chart of accounts (published in policy.json).
ACCOUNT_BANK = "1000"
ACCOUNT_AP = "2000"
ACCOUNT_SUSPENSE = "2090"
ACCOUNT_FX = "7900"


class GenerationError(RuntimeError):
    """The requested configuration cannot be realised for this seed."""


@dataclass
class Supplier:
    key: str
    currency: str
    doc_offset_minutes: int  # offset used when rendering this supplier's invoice timestamps
    expense_account: str
    category: str
    ref_prefix: str
    next_ref: int
    terms_days: int
    recurring: bool = False


@dataclass
class LineItem:
    description: str
    quantity: int
    unit_price_minor: int
    service_period: str | None = None

    @property
    def amount_minor(self) -> int:
        return self.quantity * self.unit_price_minor


@dataclass
class Invoice:
    key: str
    supplier_key: str
    vendor_ref: str
    issued_at: datetime
    due_at: datetime
    currency: str
    lines: list[LineItem]
    origin: str  # period | prior | next | duplicate_copy | reversed_copy

    @property
    def total_minor(self) -> int:
        return sum(line.amount_minor for line in self.lines)


@dataclass
class Allocation:
    invoice_key: str
    amount_minor: int


@dataclass
class Payment:
    key: str
    supplier_key: str
    timestamp: datetime
    currency: str
    amount_minor: int
    refs: list[Allocation] | None  # None = no remittance information
    origin: str  # period | next | prior


@dataclass
class Row:
    key: str
    timestamp: datetime
    account: str
    debit_minor: int
    credit_minor: int
    entity_key: str | None
    invoice_key: str | None
    payment_key: str | None
    role: str  # expense | ap | ap_clear | bank | suspense | fx | reversal_ap | reversal_expense


@dataclass
class Posting:
    key: str
    kind: str  # invoice | payment | reversal
    source_key: str
    rows: list[Row]

    def debit_total(self) -> int:
        return sum(r.debit_minor for r in self.rows)

    def credit_total(self) -> int:
        return sum(r.credit_minor for r in self.rows)


@dataclass
class World:
    profile_name: str
    base_currency: str
    offset_minutes: int
    period_start: date
    period_end: date
    suppliers: dict[str, Supplier] = field(default_factory=dict)
    invoices: dict[str, Invoice] = field(default_factory=dict)
    payments: dict[str, Payment] = field(default_factory=dict)
    fx: dict[tuple[date, str], Decimal] = field(default_factory=dict)
    fx_currencies: list[str] = field(default_factory=list)
    fx_start: date | None = None
    fx_end: date | None = None
    postings: list[Posting] = field(default_factory=list)
    reversals: dict[str, datetime] = field(default_factory=dict)  # invoice key -> reversal time
    distractors: list[dict] = field(default_factory=list)
    # Correct documents planted before injection so interacting scenarios always have a carrier.
    scenario_carriers: list[dict] = field(default_factory=list)
    _row_counter: int = 0
    _invoice_counter: int = 0
    _payment_counter: int = 0

    # -- key factories (internal keys only)
    def new_row_key(self) -> str:
        self._row_counter += 1
        return f"R{self._row_counter:05d}"

    def new_invoice_key(self) -> str:
        self._invoice_counter += 1
        return f"I{self._invoice_counter:04d}"

    def new_payment_key(self) -> str:
        self._payment_counter += 1
        return f"P{self._payment_counter:04d}"

    # -- accounting helpers
    def accounting_date(self, moment: datetime) -> date:
        return local_date(moment, self.offset_minutes)

    def in_period(self, moment: datetime) -> bool:
        return self.period_start <= self.accounting_date(moment) <= self.period_end

    def rate(self, currency: str, day: date) -> Decimal:
        """Policy rate: 1 unit of ``currency`` in base currency on local date ``day``."""
        if currency == self.base_currency:
            return Decimal(1)
        try:
            return self.fx[(day, currency)]
        except KeyError:
            raise GenerationError(f"no FX rate for {currency} on {day.isoformat()}") from None

    def posting_for(self, source_key: str, kind: str) -> Posting | None:
        for p in self.postings:
            if p.source_key == source_key and p.kind == kind:
                return p
        return None
