"""Evidence sufficiency: can an issue be proven from its cited records alone?

``check_evidence`` receives ONLY the records in one allowed evidence set (plus
the public policy) and independently recomputes the discrepancy and its amount.
If the cited records do not establish the claim, it returns a reason.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from ophanim.audit.rules import Rules


def _by_kind(records: dict[str, tuple[str, dict]], kind: str) -> list[dict]:
    return [rec for k, rec in records.values() if k == kind]


def check_evidence(issue_type: str, affected_ids: list[str], amount_minor: int, currency: str,
                   records: dict[str, tuple[str, dict]], policy: dict) -> str | None:
    """Return None if the records prove the issue, else a short reason."""
    rules = Rules(policy)
    if currency != rules.base:
        return "issue currency is not the base currency"
    affected = set(affected_ids)
    invoices = _by_kind(records, "invoice")
    payments = _by_kind(records, "payment")
    rows = _by_kind(records, "ledger")
    fx = _by_kind(records, "fx")

    def fx_rate(day, cur) -> Decimal | None:
        if cur == rules.base:
            return Decimal(1)
        for r in fx:
            if r["date"] == day.isoformat() and r["source_currency"] == cur and r["target_currency"] == rules.base:
                return Decimal(r["rate"])
        return None

    if issue_type == "duplicate_invoice":
        docs = [d for d in invoices if d["invoice_id"] in affected]
        if len(docs) != 2 or {d["invoice_id"] for d in docs} != affected:
            return "both invoice documents must be cited"
        a, b = docs
        if (a["entity_id"], a["vendor_ref"]) != (b["entity_id"], b["vendor_ref"]):
            return "documents are not the same supplier invoice"
        if (datetime.fromisoformat(a["issued_at"]) != datetime.fromisoformat(b["issued_at"]) or a["currency"] != b["currency"]
                or a["total_minor"] != b["total_minor"] or a["line_items"] != b["line_items"]):
            return "documents differ in content"
        for d in docs:
            if not rules.in_period(rules.accounting_date(d["issued_at"])):
                return "a copy is outside the period"
        booked = [r for r in rows if r["invoice_id"] in affected and r["payment_id"] is None
                  and ((r["account"] == rules.ap and r["credit_minor"] > 0) or (r["account"] != rules.ap and r["debit_minor"] > 0))]
        if not booked:
            return "no posting of either copy is cited"
        if any(max(r["credit_minor"], r["debit_minor"]) != amount_minor for r in booked):
            return "cited posting amount differs from the claimed amount"
        return None

    if issue_type == "payment_allocation":
        pays = [d for d in payments if d["payment_id"] in affected]
        invs = [d for d in invoices if d["invoice_id"] in affected]
        if len(pays) != 1 or len(invs) != 1 or len(affected) != 2:
            return "cite exactly one payment and one invoice document"
        pay, inv = pays[0], invs[0]
        if not rules.in_period(rules.accounting_date(pay["timestamp"])):
            return "payment is outside the period"
        line = [x for x in (pay["invoice_refs"] or []) if x["invoice_id"] == inv["invoice_id"]]
        if len(line) != 1:
            return "the payment's remittance does not reference the invoice"
        susp = [r for r in rows if r["account"] == rules.suspense and r["payment_id"] == pay["payment_id"]
                and r["invoice_id"] is None and r["debit_minor"] > 0]
        if len(susp) != 1:
            return "the payment's Suspense row must be cited"
        ap_rows = [r for r in rows if r["account"] == rules.ap and r["payment_id"] == pay["payment_id"]]
        if any(r["invoice_id"] == inv["invoice_id"] for r in ap_rows):
            return "a cited row shows the line as applied"
        applied = {r["invoice_id"] for r in ap_rows}
        others = {x["invoice_id"] for x in pay["invoice_refs"] if x["invoice_id"] != inv["invoice_id"]}
        if others - applied:
            return "the AP rows of the other remittance lines must be cited"
        idate = rules.accounting_date(inv["issued_at"])
        rate = fx_rate(idate, inv["currency"])
        if rate is None:
            return "the FX rate for the invoice date must be cited"
        expected = rules.convert(line[0]["amount_minor"], inv["currency"], rate)
        if inv["currency"] == rules.base and susp[0]["debit_minor"] != line[0]["amount_minor"]:
            return "Suspense amount does not match the remittance line"
        return None if expected == amount_minor else "recomputed amount differs"

    if issue_type == "fx_rate":
        if len(affected) != 1:
            return "fx_rate concerns exactly one document"
        (doc_id_value,) = affected
        inv = next((d for d in invoices if d["invoice_id"] == doc_id_value), None)
        pay = next((d for d in payments if d["payment_id"] == doc_id_value), None)
        if inv is not None:
            day = rules.accounting_date(inv["issued_at"])
            if not rules.in_period(day):
                return "document outside the period"
            rate = fx_rate(day, inv["currency"])
            if rate is None or inv["currency"] == rules.base:
                return "the policy FX rate for the accounting date must be cited"
            booked = [r for r in rows if r["invoice_id"] == inv["invoice_id"] and r["payment_id"] is None
                      and ((r["account"] == rules.ap and r["credit_minor"] > 0) or (r["account"] != rules.ap and r["debit_minor"] > 0))]
            if not booked:
                return "the invoice posting must be cited"
            correct = rules.convert(inv["total_minor"], inv["currency"], rate)
            diffs = {abs(max(r["credit_minor"], r["debit_minor"]) - correct) for r in booked}
            return None if diffs == {amount_minor} and amount_minor > 0 else "recomputed difference differs"
        if pay is not None:
            day = rules.accounting_date(pay["timestamp"])
            if not rules.in_period(day):
                return "document outside the period"
            rate = fx_rate(day, pay["currency"])
            if rate is None or pay["currency"] == rules.base:
                return "the policy FX rate for the accounting date must be cited"
            bank = [r for r in rows if r["payment_id"] == pay["payment_id"] and r["account"] == rules.bank]
            if len(bank) != 1:
                return "the payment's bank row must be cited"
            correct = rules.convert(pay["amount_minor"], pay["currency"], rate)
            diff = abs(bank[0]["credit_minor"] - correct)
            return None if diff == amount_minor and diff > 0 else "recomputed difference differs"
        return "the document must be cited"

    if issue_type == "period_attribution":
        if len(affected) != 1:
            return "period_attribution concerns exactly one document"
        (key,) = affected
        inv = next((d for d in invoices if d["invoice_id"] == key), None)
        pay = next((d for d in payments if d["payment_id"] == key), None)
        if inv is not None:
            if rules.in_period(rules.accounting_date(inv["issued_at"])):
                return "the invoice's accounting date is inside the period"
            booked = [r for r in rows if r["invoice_id"] == key and r["payment_id"] is None
                      and ((r["account"] == rules.ap and r["credit_minor"] > 0) or (r["account"] != rules.ap and r["debit_minor"] > 0))]
            if not booked:
                return "the posting in this ledger must be cited"
            return None if {max(r["credit_minor"], r["debit_minor"]) for r in booked} == {amount_minor} else "amount differs"
        if pay is not None:
            if rules.in_period(rules.accounting_date(pay["timestamp"])):
                return "the payment's accounting date is inside the period"
            bank = [r for r in rows if r["payment_id"] == key and r["account"] == rules.bank]
            if len(bank) != 1:
                return "the payment's bank row must be cited"
            return None if bank[0]["credit_minor"] == amount_minor else "amount differs"
        return "the document must be cited"

    return f"unknown issue type {issue_type!r}"
