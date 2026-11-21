"""Full reconciliation of the public records against the published policy.

This is the canonical audit procedure. Given only public data it reports every
discrepancy of the four mandatory types, each exactly once, with a minimal
evidence set. Anything that does not fit the published model (e.g. an
unbalanced posting) is reported as an *anomaly*: a well-formed episode has none.

Reporting rules (identical to the task text shown to the agent):

  period_attribution  a posting in this ledger whose source document's accounting
                      date is outside the period. Reported once; no other check
                      is applied to that posting. Amount: AP credit (invoice) or
                      Bank credit (payment) as booked.
  fx_rate             a foreign-currency posting whose base amount differs from
                      the policy conversion. Amount: |booked - correct| of the AP
                      credit (invoice) or Bank credit (payment).
  payment_allocation  a remittance line not applied to its invoice. Amount: the
                      line converted at the invoice's policy rate (AP left open).
  duplicate_invoice   two active postings for the same (entity_id, vendor_ref).
                      Amount: AP credit booked for one copy.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from ophanim.audit.dataset import PublicDataset
from ophanim.audit.rules import Rules


@dataclass(frozen=True)
class AuditFinding:
    type: str
    affected_ids: tuple[str, ...]
    amount_minor: int
    currency: str
    evidence_ids: tuple[str, ...]
    note: str = ""

    def key(self) -> tuple:
        return (self.type, self.affected_ids, self.currency)


@dataclass
class AuditReport:
    findings: list[AuditFinding] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)


def _fx_key(day, currency: str, base: str) -> str:
    return f"{day.isoformat()}:{currency}:{base}"


def reconcile(ds: PublicDataset) -> AuditReport:
    rules = Rules(ds.policy)
    base = rules.base
    report = AuditReport()
    anomalies = report.anomalies

    rates: dict[tuple[str, str], Decimal] = {}
    for row in ds.fx:
        if row["target_currency"] == base:
            rates[(row["date"], row["source_currency"])] = Decimal(row["rate"])

    def rate(currency: str, day) -> Decimal | None:
        if currency == base:
            return Decimal(1)
        return rates.get((day.isoformat(), currency))

    invoices = {d["invoice_id"]: d for d in ds.invoices}
    payments = {d["payment_id"]: d for d in ds.payments}

    # ---------------------------------------------------------------- structure
    by_payment: dict[str, list[dict]] = defaultdict(list)
    by_invoice: dict[str, list[dict]] = defaultdict(list)
    total_dr = total_cr = 0
    for row in ds.ledger:
        total_dr += row["debit_minor"]
        total_cr += row["credit_minor"]
        if row["currency"] != base:
            anomalies.append(f"row {row['row_id']}: ledger row not in base currency")
        if row["payment_id"] is not None:
            by_payment[row["payment_id"]].append(row)
        elif row["invoice_id"] is not None:
            by_invoice[row["invoice_id"]].append(row)
        else:
            anomalies.append(f"row {row['row_id']}: row without a source document")
    if total_dr != total_cr:
        anomalies.append("ledger does not balance")
    for groups in (by_payment, by_invoice):
        for key, rows in groups.items():
            if sum(r["debit_minor"] for r in rows) != sum(r["credit_minor"] for r in rows):
                anomalies.append(f"posting for {key} does not balance")

    findings: list[AuditFinding] = []

    # ---------------------------------------------------------------- payments
    for pid in sorted(by_payment):
        rows = by_payment[pid]
        doc = payments.get(pid)
        if doc is None:
            anomalies.append(f"payment {pid} posted without a document")
            continue
        pdate = rules.accounting_date(doc["timestamp"])
        bank_rows = [r for r in rows if r["account"] == rules.bank]
        if len(bank_rows) != 1:
            anomalies.append(f"payment {pid}: expected exactly one bank row")
            continue
        bank_row = bank_rows[0]
        bank = bank_row["credit_minor"] - bank_row["debit_minor"]
        if not rules.in_period(pdate):
            findings.append(AuditFinding("period_attribution", (pid,), bank, base,
                                         tuple(sorted((doc["doc_id"], bank_row["row_id"]))),
                                         f"payment dated {pdate} posted in this period"))
            continue
        r_pay = rate(doc["currency"], pdate)
        if r_pay is None:
            anomalies.append(f"payment {pid}: no FX rate for {doc['currency']} on {pdate}")
            continue
        expected_bank = rules.convert(doc["amount_minor"], doc["currency"], r_pay)
        if bank != expected_bank:
            if doc["currency"] == base:
                anomalies.append(f"payment {pid}: base-currency bank amount differs from document")
            else:
                findings.append(AuditFinding("fx_rate", (pid,), abs(bank - expected_bank), base,
                                             tuple(sorted((doc["doc_id"], bank_row["row_id"], _fx_key(pdate, doc["currency"], base)))),
                                             f"bank {bank} vs policy {expected_bank}"))

        refs = doc["invoice_refs"]
        ap_rows = [r for r in rows if r["account"] == rules.ap]
        susp_rows = [r for r in rows if r["account"] == rules.suspense]
        if refs is None:
            if ap_rows:
                anomalies.append(f"payment {pid}: AP applied without remittance information")
            continue
        if sum(x["amount_minor"] for x in refs) != doc["amount_minor"]:
            anomalies.append(f"payment {pid}: remittance lines do not sum to the amount")
        unapplied = []
        for ref in refs:
            inv = invoices.get(ref["invoice_id"])
            if inv is None:
                anomalies.append(f"payment {pid}: remittance references a missing invoice")
                continue
            idate = rules.accounting_date(inv["issued_at"])
            r_inv = rate(inv["currency"], idate)
            if r_inv is None:
                anomalies.append(f"invoice {inv['invoice_id']}: no FX rate on {idate}")
                continue
            expected = rules.convert(ref["amount_minor"], inv["currency"], r_inv)
            applied = sum(r["debit_minor"] - r["credit_minor"] for r in ap_rows if r["invoice_id"] == ref["invoice_id"])
            if applied == 0:
                unapplied.append((inv, expected, idate))
            elif applied != expected:
                anomalies.append(f"payment {pid}: line {ref['invoice_id']} applied {applied}, expected {expected}")
        if len(unapplied) != len(susp_rows):
            anomalies.append(f"payment {pid}: {len(unapplied)} unapplied lines but {len(susp_rows)} suspense rows")
            continue
        if len(unapplied) > 1:
            anomalies.append(f"payment {pid}: more than one unapplied line (ambiguous suspense attribution)")
            continue
        for inv, expected, idate in unapplied:
            evidence = [doc["doc_id"], inv["doc_id"], susp_rows[0]["row_id"]]
            evidence += [r["row_id"] for r in ap_rows]
            if inv["currency"] != base:
                evidence.append(_fx_key(idate, inv["currency"], base))
            findings.append(AuditFinding("payment_allocation", tuple(sorted((pid, inv["invoice_id"]))), expected, base,
                                         tuple(sorted(evidence)), "remittance line parked in Suspense"))

    # ---------------------------------------------------------------- invoices
    active: list[str] = []
    for iid in sorted(by_invoice):
        rows = by_invoice[iid]
        inv = invoices.get(iid)
        if inv is None:
            anomalies.append(f"invoice {iid} posted without a document")
            continue
        ap_rows = [r for r in rows if r["account"] == rules.ap]
        ap_credit = sum(r["credit_minor"] for r in ap_rows)
        ap_debit = sum(r["debit_minor"] for r in ap_rows)
        expense_net = sum(r["debit_minor"] - r["credit_minor"] for r in rows if r["account"] not in (rules.ap,))
        if ap_debit:
            if ap_debit == ap_credit and expense_net == 0:
                continue  # fully reversed: no net effect
            anomalies.append(f"invoice {iid}: partial reversal")
            continue
        if expense_net != ap_credit:
            anomalies.append(f"invoice {iid}: expense and AP sides differ")
        ap_row = next((r for r in ap_rows if r["credit_minor"] > 0), None)
        if ap_row is None:
            anomalies.append(f"invoice {iid}: no AP credit")
            continue
        idate = rules.accounting_date(inv["issued_at"])
        if not rules.in_period(idate):
            findings.append(AuditFinding("period_attribution", (iid,), ap_credit, base,
                                         tuple(sorted((inv["doc_id"], ap_row["row_id"]))),
                                         f"invoice dated {idate} posted in this period"))
            continue
        r_inv = rate(inv["currency"], idate)
        if r_inv is None:
            anomalies.append(f"invoice {iid}: no FX rate on {idate}")
            continue
        expected = rules.convert(inv["total_minor"], inv["currency"], r_inv)
        if ap_credit != expected:
            if inv["currency"] == base:
                anomalies.append(f"invoice {iid}: base-currency AP differs from the document total")
            else:
                findings.append(AuditFinding("fx_rate", (iid,), abs(ap_credit - expected), base,
                                             tuple(sorted((inv["doc_id"], ap_row["row_id"], _fx_key(idate, inv["currency"], base)))),
                                             f"AP {ap_credit} vs policy {expected}"))
        active.append(iid)

    # Every in-period invoice document must be recorded (no unrecorded liabilities in this model).
    recorded = set(by_invoice)
    for inv in ds.invoices:
        if inv["invoice_id"] not in recorded and rules.in_period(rules.accounting_date(inv["issued_at"])):
            anomalies.append(f"invoice {inv['invoice_id']}: in-period invoice with no posting")

    # ---------------------------------------------------------------- duplicates
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for iid in active:
        inv = invoices[iid]
        groups[(inv["entity_id"], inv["vendor_ref"])].append(iid)
    for key in sorted(groups):
        ids = sorted(groups[key])
        if len(ids) < 2:
            continue
        if len(ids) > 2:
            anomalies.append(f"vendor_ref {key[1]}: recorded {len(ids)} times")
            continue
        a, b = (invoices[i] for i in ids)
        same = (_instant(rules, a["issued_at"]) == _instant(rules, b["issued_at"]) and a["currency"] == b["currency"]
                and a["total_minor"] == b["total_minor"] and _lines(a) == _lines(b))
        if not same:
            anomalies.append(f"vendor_ref {key[1]}: same reference, different content")
            continue
        ap_a = next(r for r in by_invoice[ids[0]] if r["account"] == rules.ap and r["credit_minor"] > 0)
        ap_b = next(r for r in by_invoice[ids[1]] if r["account"] == rules.ap and r["credit_minor"] > 0)
        if ap_a["credit_minor"] != ap_b["credit_minor"]:
            anomalies.append(f"vendor_ref {key[1]}: copies booked at different amounts")
            continue
        findings.append(AuditFinding("duplicate_invoice", tuple(ids), ap_b["credit_minor"], base,
                                     tuple(sorted((a["doc_id"], b["doc_id"], ap_a["row_id"]))),
                                     f"invoice {key[1]} recorded twice"))

    report.findings = sorted(findings, key=lambda f: (f.type, f.affected_ids))
    return report


def _instant(rules: Rules, ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _lines(doc: dict) -> list[tuple]:
    return [(l["description"], l["quantity"], l["unit_price_minor"], l["amount_minor"], l["service_period"]) for l in doc["line_items"]]
