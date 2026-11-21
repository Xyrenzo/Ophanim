"""Baseline 2 - Simple reconciliation (deliberately naive).

Downloads every table, then applies textbook-but-shallow checks:
  * duplicates   - same supplier and same total (ignores vendor_ref and reversals);
  * allocation   - any payment with remittance info AND a Suspense row; claims the
                   Suspense amount against the first referenced invoice;
  * FX           - recomputes with the rate of the date *as written* in the timestamp
                   string (ignores the company timezone);
  * period       - compares the date prefix of ledger timestamps (UTC) with the period.

It finds some real errors and falls for the red herrings: repeat orders, reversed
duplicates, supplier-time and UTC dates, multi-line remittances, foreign amounts.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from ophanim.policies.base import list_action, submit_action

_TABLES = ("ledger", "invoices", "payments", "fx")


class SimpleReconciliation:
    name = "simple_reconciliation"

    def reset(self, observation: dict, info: dict) -> None:
        self.manifest = observation["manifest"]
        self.policy = observation["policy"]
        self.tables: dict[str, list[dict]] = {t: [] for t in _TABLES}
        self.queue = list(_TABLES)
        self.pending = False

    def act(self, observation: dict) -> dict:
        res = observation.get("result") if isinstance(observation, dict) else None
        if self.pending and isinstance(res, dict) and "records" in res:
            self.tables[res["table"]].extend(res["records"])
            if res["next_cursor"]:
                return list_action(res["table"], res["next_cursor"])
            self.pending = False
        if self.queue:
            self.pending = True
            return list_action(self.queue.pop(0), None)
        return submit_action(self.manifest["episode_id"], self._findings()[:30])

    # ------------------------------------------------------------------ naive checks
    def _convert(self, amount: int, currency: str, rate: str) -> int:
        exps = self.policy["currency_exponents"]
        base = self.policy["base_currency"]
        value = Decimal(amount) / Decimal(10) ** exps[currency] * Decimal(rate)
        q = Decimal(1) / Decimal(10) ** exps[base]
        return int(value.quantize(q, rounding=ROUND_HALF_UP) * Decimal(10) ** exps[base])

    def _findings(self) -> list[dict]:
        base = self.policy["base_currency"]
        acc = {v: k for k, v in self.policy["accounts"].items()}
        ap, bank, susp = acc["Accounts payable"], acc["Bank"], acc["Suspense - payments awaiting identification"]
        start, end = self.policy["reporting_period"]["start"], self.policy["reporting_period"]["end"]
        rates = {(r["date"], r["source_currency"]): r["rate"] for r in self.tables["fx"]}
        invoices = {i["invoice_id"]: i for i in self.tables["invoices"]}
        payments = {p["payment_id"]: p for p in self.tables["payments"]}
        rows_by_inv: dict[str, list[dict]] = defaultdict(list)
        rows_by_pay: dict[str, list[dict]] = defaultdict(list)
        for r in self.tables["ledger"]:
            if r["payment_id"]:
                rows_by_pay[r["payment_id"]].append(r)
            elif r["invoice_id"]:
                rows_by_inv[r["invoice_id"]].append(r)
        out: list[dict] = []

        def add(type_, ids, amount, evidence, why):
            out.append({"type": type_, "affected_ids": sorted(ids), "claimed_amount_minor": max(0, int(amount)),
                        "currency": base, "evidence_ids": sorted(set(evidence))[:10], "explanation": why})

        # duplicates: same supplier + same total
        groups: dict[tuple, list[str]] = defaultdict(list)
        for iid in sorted(rows_by_inv):
            inv = invoices.get(iid)
            if inv:
                groups[(inv["entity_id"], inv["total_minor"], inv["currency"])].append(iid)
        for ids in groups.values():
            if len(ids) == 2:
                ap_row = next((r for r in rows_by_inv[ids[1]] if r["account"] == ap and r["credit_minor"]), None)
                if ap_row:
                    add("duplicate_invoice", ids, ap_row["credit_minor"],
                        [invoices[ids[0]]["doc_id"], invoices[ids[1]]["doc_id"], ap_row["row_id"]], "same supplier and amount")

        # allocation: suspense on a payment that has remittance info
        for pid, rows in sorted(rows_by_pay.items()):
            pay = payments.get(pid)
            s = [r for r in rows if r["account"] == susp]
            if pay and pay["invoice_refs"] and s:
                inv = invoices.get(pay["invoice_refs"][0]["invoice_id"])
                if inv:
                    add("payment_allocation", [pid, inv["invoice_id"]], s[0]["debit_minor"],
                        [pay["doc_id"], inv["doc_id"], s[0]["row_id"]], "payment parked in suspense")

        # FX: naive date = first 10 characters of the timestamp as written
        for iid, rows in sorted(rows_by_inv.items()):
            inv = invoices.get(iid)
            if not inv or inv["currency"] == base:
                continue
            day = inv["issued_at"][:10]
            rate = rates.get((day, inv["currency"]))
            ap_row = next((r for r in rows if r["account"] == ap and r["credit_minor"]), None)
            if rate and ap_row:
                diff = abs(ap_row["credit_minor"] - self._convert(inv["total_minor"], inv["currency"], rate))
                if diff:
                    add("fx_rate", [iid], diff, [inv["doc_id"], ap_row["row_id"], f"{day}:{inv['currency']}:{base}"], "rate mismatch")
        for pid, rows in sorted(rows_by_pay.items()):
            pay = payments.get(pid)
            if not pay or pay["currency"] == base:
                continue
            day = pay["timestamp"][:10]
            rate = rates.get((day, pay["currency"]))
            b = next((r for r in rows if r["account"] == bank), None)
            if rate and b:
                diff = abs(b["credit_minor"] - self._convert(pay["amount_minor"], pay["currency"], rate))
                if diff:
                    add("fx_rate", [pid], diff, [pay["doc_id"], b["row_id"], f"{day}:{pay['currency']}:{base}"], "rate mismatch")

        # period: UTC date prefix of the ledger timestamp
        for iid, rows in sorted(rows_by_inv.items()):
            r0 = rows[0]
            if not (start <= r0["timestamp"][:10] <= end) and iid in invoices:
                ap_row = next((r for r in rows if r["account"] == ap and r["credit_minor"]), r0)
                add("period_attribution", [iid], ap_row["credit_minor"], [invoices[iid]["doc_id"], ap_row["row_id"]], "outside period")
        for pid, rows in sorted(rows_by_pay.items()):
            b = next((r for r in rows if r["account"] == bank), None)
            if b and not (start <= b["timestamp"][:10] <= end) and pid in payments:
                add("period_attribution", [pid], b["credit_minor"], [payments[pid]["doc_id"], b["row_id"]], "outside period")
        return out
