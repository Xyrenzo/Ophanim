"""Presentation layer: public identifiers, names, record order and rendering.

This is the only place where internal keys become public ids. Ids are random
tokens drawn from a presentation stream that is independent of the economic
content, so:

* ids carry no information about creation order, injection or errors;
* changing ``presentation.id_salt`` / ``name_salt`` / ``order`` produces an
  equivalent episode (same accounting, different ids/names/order) - the basis
  of the metamorphic tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ophanim.generator import names as namegen
from ophanim.generator.model import ACCOUNT_AP, ACCOUNT_BANK, ACCOUNT_FX, ACCOUNT_SUSPENSE, World
from ophanim.generator.profiles import PROFILES
from ophanim.money import CURRENCY_EXPONENTS, ROUNDING_MODE_NAME, rate_to_str
from ophanim.rng import DeterministicRng
from ophanim.timeutil import format_ts, offset_minutes_to_str, parse_ts
from ophanim.version import ENV_VERSION, SCHEMA_VERSION

TOLERANCE_MINOR = 1

LEDGER_COLUMNS = ("row_id", "timestamp", "account", "debit_minor", "credit_minor", "currency", "entity_id", "invoice_id", "payment_id")
FX_COLUMNS = ("date", "source_currency", "target_currency", "rate")


@dataclass
class IdMap:
    supplier: dict[str, str] = field(default_factory=dict)
    invoice: dict[str, str] = field(default_factory=dict)
    payment: dict[str, str] = field(default_factory=dict)
    doc: dict[str, str] = field(default_factory=dict)
    row: dict[str, str] = field(default_factory=dict)

    def flat(self) -> dict[str, str]:
        out: dict[str, str] = {}
        out.update(self.supplier)
        out.update(self.invoice)
        out.update(self.payment)
        out.update(self.row)
        out.update({f"doc:{k}": v for k, v in self.doc.items()})
        return out


def build_id_map(worlds: list[World], rng: DeterministicRng) -> IdMap:
    """Assign random public ids to every key in the union of the given worlds."""
    taken: set[str] = set()

    def fresh(prefix: str, length: int) -> str:
        while True:
            candidate = prefix + rng.token(length)
            if candidate not in taken:
                taken.add(candidate)
                return candidate

    suppliers = sorted({k for w in worlds for k in w.suppliers})
    invoices = sorted({k for w in worlds for k in w.invoices})
    payments = sorted({k for w in worlds for k in w.payments})
    rows = sorted({r.key for w in worlds for p in w.postings for r in p.rows})
    m = IdMap()
    for k in suppliers:
        m.supplier[k] = fresh("SUP-", 6)
    for k in invoices:
        m.invoice[k] = fresh("INV-", 8)
    for k in payments:
        m.payment[k] = fresh("PAY-", 8)
    for k in invoices + payments:
        m.doc[k] = fresh("DOC-", 10)
    for k in rows:
        m.row[k] = fresh("GL-", 9)
    return m


@dataclass
class Names:
    company: str
    suppliers: dict[str, str]


def build_names(world: World, rng: DeterministicRng) -> Names:
    used: set[str] = set()
    company = namegen.company_name(rng)
    suppliers: dict[str, str] = {}
    for k in sorted(world.suppliers):
        while True:
            n = namegen.supplier_name(rng)
            if n not in used:
                used.add(n)
                suppliers[k] = n
                break
    return Names(company=company, suppliers=suppliers)


# --------------------------------------------------------------------------- policy
def build_policy(world: World) -> dict:
    profile = PROFILES[world.profile_name]
    currencies = sorted({world.base_currency, *world.fx_currencies})
    accounts = {
        ACCOUNT_BANK: "Bank",
        ACCOUNT_AP: "Accounts payable",
        ACCOUNT_SUSPENSE: "Suspense - payments awaiting identification",
        ACCOUNT_FX: "Realised FX gain/loss",
    }
    for c in profile.categories:
        accounts[c.expense_account] = f"Expense - {c.name}"
    accounts = {k: accounts[k] for k in sorted(accounts)}
    return {
        "schema_version": SCHEMA_VERSION,
        "base_currency": world.base_currency,
        "timezone": offset_minutes_to_str(world.offset_minutes),
        "currency_exponents": {c: CURRENCY_EXPONENTS[c] for c in currencies},
        "accounting_date": "The local calendar date, in the company timezone above, of the source document: "
                           "invoice.issued_at for invoices, payment.timestamp for payments.",
        "reporting_period": {
            "start": world.period_start.isoformat(),
            "end": world.period_end.isoformat(),
            "inclusive": True,
            "rule": "A posting belongs to this period if and only if the accounting date of its source document "
                    "falls between start and end inclusive. Ledger timestamps are stored in UTC.",
        },
        "fx": {
            "source": "fx.csv",
            "quote": "1 unit of source_currency = rate units of target_currency (the base currency).",
            "rate_date": "Use the rate dated on the document's accounting date.",
            "settlement": "AP is cleared at the invoice's rate; Bank is credited at the payment's rate; "
                          "the difference is posted to account 7900.",
        },
        "rounding": {
            "mode": ROUNDING_MODE_NAME,
            "rule": "convert(amount_minor) = round_half_up(amount_minor / 10**exp(source) * rate, exp(target)) "
                    "expressed in target minor units. Each document amount (or remittance line) is converted once, as a whole.",
        },
        "accounts": accounts,
        "posting_rules": {
            "invoice": "Dr expense / Cr 2000 AP, base amount of the invoice total.",
            "payment_with_remittance": "One Dr 2000 AP row per remittance line (invoice_id set) at the invoice's rate; "
                                       "Cr 1000 Bank at the payment's rate; difference to 7900.",
            "payment_without_remittance": "Dr 2090 Suspense / Cr 1000 Bank at the payment's rate. This is correct treatment.",
            "reversal": "Mirror image of the original invoice rows; an invoice reversed in full has no net effect.",
        },
        "allocation": "Every remittance line (invoice_refs) of a payment must be applied in full to the referenced "
                      "invoice's AP. Suspense is only for payments without remittance information.",
        "duplicates": "A supplier invoice is identified by (entity_id, vendor_ref). It may be recorded at most once, "
                      "net of reversals. Equal amounts or equal vendor_ref across different suppliers are not duplicates.",
        "tolerance_minor": TOLERANCE_MINOR,
    }


# --------------------------------------------------------------------------- rendering
def _sorted_or_shuffled(items: list[dict], key, order_rng: DeterministicRng | None, name: str) -> list[dict]:
    if order_rng is None:
        return sorted(items, key=key)
    out = sorted(items, key=key)
    order_rng.child(name).shuffle(out)
    return out


def render_tables(world: World, ids: IdMap, nm: Names, order_rng: DeterministicRng | None,
                  timestamp_offset: int = 0) -> dict[str, list[dict]]:
    """``timestamp_offset``: minutes east of UTC used to write ledger/payment timestamps."""
    base = world.base_currency
    ledger: list[dict] = []
    posted_invoices: set[str] = set()
    posted_payments: set[str] = set()
    for p in world.postings:
        if p.kind in ("invoice", "reversal"):
            posted_invoices.add(p.source_key)
        else:
            posted_payments.add(p.source_key)
        for r in p.rows:
            ledger.append({
                "row_id": ids.row[r.key],
                "timestamp": format_ts(r.timestamp, timestamp_offset),
                "account": r.account,
                "debit_minor": r.debit_minor,
                "credit_minor": r.credit_minor,
                "currency": base,
                "entity_id": ids.supplier[r.entity_key] if r.entity_key else None,
                "invoice_id": ids.invoice[r.invoice_key] if r.invoice_key else None,
                "payment_id": ids.payment[r.payment_key] if r.payment_key else None,
            })

    included_invoices = set(posted_invoices)
    for key in posted_payments:
        for a in world.payments[key].refs or []:
            included_invoices.add(a.invoice_key)

    invoices = []
    for key in included_invoices:
        inv = world.invoices[key]
        s = world.suppliers[inv.supplier_key]
        invoices.append({
            "doc_id": ids.doc[key],
            "invoice_id": ids.invoice[key],
            "entity_id": ids.supplier[s.key],
            "issued_at": format_ts(inv.issued_at, s.doc_offset_minutes),
            "due_at": format_ts(inv.due_at, s.doc_offset_minutes),
            "currency": inv.currency,
            "total_minor": inv.total_minor,
            "line_items": [
                {"line_no": i + 1, "description": l.description, "quantity": l.quantity,
                 "unit_price_minor": l.unit_price_minor, "amount_minor": l.amount_minor, "service_period": l.service_period}
                for i, l in enumerate(inv.lines)
            ],
            "vendor_ref": inv.vendor_ref,
            "entity_name": nm.suppliers[s.key],
        })

    payments = []
    for key in posted_payments:
        pay = world.payments[key]
        payments.append({
            "doc_id": ids.doc[key],
            "payment_id": ids.payment[key],
            "timestamp": format_ts(pay.timestamp, timestamp_offset),
            "currency": pay.currency,
            "amount_minor": pay.amount_minor,
            "invoice_refs": None if pay.refs is None else [
                {"invoice_id": ids.invoice[a.invoice_key], "amount_minor": a.amount_minor} for a in pay.refs
            ],
            "entity_id": ids.supplier[pay.supplier_key],
            "entity_name": nm.suppliers[pay.supplier_key],
        })

    fx = [
        {"date": day.isoformat(), "source_currency": cur, "target_currency": base, "rate": rate_to_str(rate)}
        for (day, cur), rate in sorted(world.fx.items())
    ]

    return {
        "ledger": _sorted_or_shuffled(ledger, lambda x: (x["timestamp"], x["row_id"]), order_rng, "ledger"),
        # Natural order is chronological by instant (offsets differ between documents).
        "invoices": _sorted_or_shuffled(invoices, lambda x: (parse_ts(x["issued_at"]), x["invoice_id"]), order_rng, "invoices"),
        "payments": _sorted_or_shuffled(payments, lambda x: (parse_ts(x["timestamp"]), x["payment_id"]), order_rng, "payments"),
        "fx": _sorted_or_shuffled(fx, lambda x: (x["date"], x["source_currency"]), order_rng, "fx"),
    }


def build_manifest(world: World, tables: dict[str, list[dict]], episode_id: str, nm: Names) -> dict:
    profile = PROFILES[world.profile_name]
    return {
        "schema_version": SCHEMA_VERSION,
        "env_version": ENV_VERSION,
        "episode_id": episode_id,
        "company_name": nm.company,
        "company_profile": profile.label,
        "base_currency": world.base_currency,
        "period_start": world.period_start.isoformat(),
        "period_end": world.period_end.isoformat(),
        "timezone": offset_minutes_to_str(world.offset_minutes),
        "record_counts": {name: len(rows) for name, rows in tables.items()},
        "document_count": len(tables["invoices"]) + len(tables["payments"]),
        "rounding": {
            "mode": ROUNDING_MODE_NAME,
            "currency_exponents": {c: CURRENCY_EXPONENTS[c] for c in sorted({world.base_currency, *world.fx_currencies})},
            "fx_rate_format": "decimal string",
            "money_format": "integer minor units",
        },
        "files": {"ledger": "ledger.csv", "invoices": "invoices.jsonl", "payments": "payments.jsonl",
                  "fx": "fx.csv", "policy": "policy.json"},
    }
