"""Posting engine: turns documents into double-entry ledger rows (correctly).

Posting rules (published in policy.json):

* Supplier invoice, accounting date d (local date of issued_at):
      Dr <expense account>  convert(total, rate(d))
      Cr 2000 AP            convert(total, rate(d))
* Payment with remittance lines (I_k, a_k), accounting date p:
      Dr 2000 AP            convert(a_k, rate(date of I_k))      one row per line
      Cr 1000 Bank          convert(amount, rate(p))
      Dr/Cr 7900 FX         bank - sum(AP)                        only if non-zero
* Payment without remittance information:
      Dr 2090 Suspense      convert(amount, rate(p))
      Cr 1000 Bank          convert(amount, rate(p))
* Reversal of an invoice posting: the mirror image of the original rows.

All rows are in the base currency. The ledger timestamp of an original posting
is the source document's timestamp (rendered in UTC); reversals carry their own time.
"""

from __future__ import annotations

from datetime import datetime

from ophanim.generator.model import (
    ACCOUNT_AP,
    ACCOUNT_BANK,
    ACCOUNT_FX,
    ACCOUNT_SUSPENSE,
    Invoice,
    Payment,
    Posting,
    Row,
    World,
)
from ophanim.money import convert_minor


def invoice_base_amount(world: World, inv: Invoice) -> int:
    rate = world.rate(inv.currency, world.accounting_date(inv.issued_at))
    return convert_minor(inv.total_minor, inv.currency, world.base_currency, rate)


def allocation_base_amount(world: World, invoice_key: str, amount_minor: int) -> int:
    inv = world.invoices[invoice_key]
    rate = world.rate(inv.currency, world.accounting_date(inv.issued_at))
    return convert_minor(amount_minor, inv.currency, world.base_currency, rate)


def payment_base_amount(world: World, pay: Payment, rate_override=None) -> int:
    rate = rate_override if rate_override is not None else world.rate(pay.currency, world.accounting_date(pay.timestamp))
    return convert_minor(pay.amount_minor, pay.currency, world.base_currency, rate)


def _row(world: World, ts: datetime, account: str, debit: int, credit: int, entity: str | None,
         invoice: str | None, payment: str | None, role: str) -> Row:
    return Row(key=world.new_row_key(), timestamp=ts, account=account, debit_minor=debit, credit_minor=credit,
               entity_key=entity, invoice_key=invoice, payment_key=payment, role=role)


def post_invoice(world: World, inv: Invoice) -> Posting:
    supplier = world.suppliers[inv.supplier_key]
    amount = invoice_base_amount(world, inv)
    rows = [
        _row(world, inv.issued_at, supplier.expense_account, amount, 0, supplier.key, inv.key, None, "expense"),
        _row(world, inv.issued_at, ACCOUNT_AP, 0, amount, supplier.key, inv.key, None, "ap"),
    ]
    return Posting(key=f"post:{inv.key}", kind="invoice", source_key=inv.key, rows=rows)


def post_reversal(world: World, inv: Invoice, when: datetime) -> Posting:
    supplier = world.suppliers[inv.supplier_key]
    amount = invoice_base_amount(world, inv)
    rows = [
        _row(world, when, ACCOUNT_AP, amount, 0, supplier.key, inv.key, None, "reversal_ap"),
        _row(world, when, supplier.expense_account, 0, amount, supplier.key, inv.key, None, "reversal_expense"),
    ]
    return Posting(key=f"rev:{inv.key}", kind="reversal", source_key=inv.key, rows=rows)


def fx_balancing_row(world: World, pay: Payment, bank: int, applied: int) -> Row | None:
    diff = bank - applied
    if diff == 0:
        return None
    if diff > 0:  # paid more base currency than the AP carried: exchange loss
        return _row(world, pay.timestamp, ACCOUNT_FX, diff, 0, pay.supplier_key, None, pay.key, "fx")
    return _row(world, pay.timestamp, ACCOUNT_FX, 0, -diff, pay.supplier_key, None, pay.key, "fx")


def refund_suspense_amount(world: World, refund: Payment) -> int:
    """Suspense carried for the refunded payment = what it was parked at (its policy-rate base amount)."""
    original = world.payments[refund.refund_of]
    return payment_base_amount(world, original)


def post_refund(world: World, refund: Payment) -> Posting:
    """Supplier refund of a payment that had no remittance information (parked in Suspense).

        Dr 1000 Bank        convert(amount, rate(refund date))       money comes back
        Cr 2090 Suspense    the refunded payment's Suspense amount   clears the parked item
        Dr/Cr 7900 FX       difference                                only if non-zero
    """
    bank = payment_base_amount(world, refund)
    cleared = refund_suspense_amount(world, refund)
    rows = [
        _row(world, refund.timestamp, ACCOUNT_BANK, bank, 0, refund.supplier_key, None, refund.key, "bank"),
        _row(world, refund.timestamp, ACCOUNT_SUSPENSE, 0, cleared, refund.supplier_key, None, refund.key, "suspense_refund"),
    ]
    diff = cleared - bank  # Suspense carried more than the bank received -> exchange loss (debit)
    if diff > 0:
        rows.append(_row(world, refund.timestamp, ACCOUNT_FX, diff, 0, refund.supplier_key, None, refund.key, "fx"))
    elif diff < 0:
        rows.append(_row(world, refund.timestamp, ACCOUNT_FX, 0, -diff, refund.supplier_key, None, refund.key, "fx"))
    return Posting(key=f"post:{refund.key}", kind="payment", source_key=refund.key, rows=rows)


def post_payment(world: World, pay: Payment) -> Posting:
    if pay.direction == "inbound":
        return post_refund(world, pay)
    bank = payment_base_amount(world, pay)
    rows: list[Row] = []
    if pay.refs is None:
        rows.append(_row(world, pay.timestamp, ACCOUNT_SUSPENSE, bank, 0, pay.supplier_key, None, pay.key, "suspense"))
        rows.append(_row(world, pay.timestamp, ACCOUNT_BANK, 0, bank, pay.supplier_key, None, pay.key, "bank"))
        return Posting(key=f"post:{pay.key}", kind="payment", source_key=pay.key, rows=rows)
    applied = 0
    for alloc in pay.refs:
        amount = allocation_base_amount(world, alloc.invoice_key, alloc.amount_minor)
        applied += amount
        rows.append(_row(world, pay.timestamp, ACCOUNT_AP, amount, 0, pay.supplier_key, alloc.invoice_key, pay.key, "ap_clear"))
    rows.append(_row(world, pay.timestamp, ACCOUNT_BANK, 0, bank, pay.supplier_key, None, pay.key, "bank"))
    fx = fx_balancing_row(world, pay, bank, applied)
    if fx is not None:
        rows.append(fx)
    return Posting(key=f"post:{pay.key}", kind="payment", source_key=pay.key, rows=rows)


def post_world(world: World) -> None:
    """Create all correct postings that belong to this period's ledger."""
    world.postings = []
    for key in sorted(world.invoices):
        inv = world.invoices[key]
        if inv.origin in ("period", "reversed_copy") and world.in_period(inv.issued_at):
            world.postings.append(post_invoice(world, inv))
    for key in sorted(world.payments):
        pay = world.payments[key]
        if pay.origin == "period" and world.in_period(pay.timestamp):
            world.postings.append(post_payment(world, pay))
    for key in sorted(world.reversals):
        world.postings.append(post_reversal(world, world.invoices[key], world.reversals[key]))


def validate_world(world: World) -> list[str]:
    """Generator self-check of accounting equalities on the (pre-mutation) world.

    Returns a list of violations (empty when the books are internally consistent).
    The independent verifier repeats these checks from the public files only.
    """
    problems: list[str] = []
    for p in world.postings:
        if p.debit_total() != p.credit_total():
            problems.append(f"{p.key}: unbalanced posting")
        if p.kind in ("invoice", "payment"):
            src = world.invoices.get(p.source_key) if p.kind == "invoice" else world.payments.get(p.source_key)
            ts = src.issued_at if p.kind == "invoice" else src.timestamp
            if not world.in_period(ts):
                problems.append(f"{p.key}: source document outside the period")
        if p.kind == "invoice":
            inv = world.invoices[p.source_key]
            expected = invoice_base_amount(world, inv)
            ap = sum(r.credit_minor for r in p.rows if r.role == "ap")
            if ap != expected:
                problems.append(f"{p.key}: AP {ap} != expected {expected}")
        if p.kind == "payment" and world.payments[p.source_key].direction == "inbound":
            refund = world.payments[p.source_key]
            original = world.payments.get(refund.refund_of or "")
            bank_in = sum(r.debit_minor - r.credit_minor for r in p.rows if r.role == "bank")
            cleared = sum(r.credit_minor for r in p.rows if r.role == "suspense_refund")
            if original is None or original.refs is not None or original.direction != "outbound":
                problems.append(f"{p.key}: refund must refund an outbound payment without remittance")
            elif (original.supplier_key, original.currency, original.amount_minor) != (refund.supplier_key, refund.currency, refund.amount_minor):
                problems.append(f"{p.key}: refund does not match the refunded payment")
            elif not original.timestamp < refund.timestamp:
                problems.append(f"{p.key}: refund precedes the refunded payment")
            if bank_in != payment_base_amount(world, refund) or (original is not None and cleared != payment_base_amount(world, original)):
                problems.append(f"{p.key}: refund amounts inconsistent")
            continue
        if p.kind == "payment":
            pay = world.payments[p.source_key]
            bank = sum(r.credit_minor for r in p.rows if r.role == "bank")
            if bank != payment_base_amount(world, pay):
                problems.append(f"{p.key}: bank amount mismatch")
            if pay.refs is not None:
                if sum(a.amount_minor for a in pay.refs) != pay.amount_minor:
                    problems.append(f"{p.key}: remittance lines do not sum to the payment amount")
                for a in pay.refs:
                    applied = sum(r.debit_minor for r in p.rows if r.role == "ap_clear" and r.invoice_key == a.invoice_key)
                    if applied != allocation_base_amount(world, a.invoice_key, a.amount_minor):
                        problems.append(f"{p.key}: line for {a.invoice_key} not applied correctly")
    # No invoice may be paid more than its total.
    paid: dict[str, int] = {}
    for pay in world.payments.values():
        for a in pay.refs or []:
            paid[a.invoice_key] = paid.get(a.invoice_key, 0) + a.amount_minor
    for key, amount in paid.items():
        if amount > world.invoices[key].total_minor:
            problems.append(f"{key}: over-allocated")
    # Each (supplier, vendor_ref) recorded at most once, net of reversals.
    seen: dict[tuple[str, str], str] = {}
    for p in world.postings:
        if p.kind != "invoice" or p.source_key in world.reversals:
            continue
        inv = world.invoices[p.source_key]
        k = (inv.supplier_key, inv.vendor_ref)
        if k in seen:
            problems.append(f"{p.source_key}: duplicate of {seen[k]}")
        seen[k] = p.source_key
    return problems
