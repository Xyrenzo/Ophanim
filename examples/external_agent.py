#!/usr/bin/env python3
"""A complete external OPHANIM agent in the Python standard library only.

It speaks the JSON-lines protocol of docs/agent_protocol.md on stdin/stdout and implements ONE published
rule from the task text: a duplicate invoice is the same supplier invoice (same entity_id and vendor_ref,
same content) with two active postings. It pages through invoices and the ledger, then submits the
duplicates it can prove with the evidence the task text asks for (both invoice doc_ids and the AP row of
one copy). It reports nothing else, so on other error types it scores false negatives, never false
positives: a starting point for your own agent, not a strong one.

Run it against one closed episode:

    python -m ophanim run-agent --cmd "python examples/external_agent.py" --seed 7

Rules worth copying: never print anything but protocol messages to stdout (use stderr for logs; the
evaluator discards it); copy ids exactly as observed; keep amounts as integer minor units.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict

TABLES = ("invoices", "ledger")


class DuplicateInvoiceAgent:
    def reset(self, observation: dict) -> None:
        self.episode_id = observation["manifest"]["episode_id"]
        self.base = observation["policy"]["base_currency"]
        accounts = observation["policy"]["accounts"]
        self.ap = next(code for code, name in accounts.items() if name == "Accounts payable")
        self.records: dict[str, list[dict]] = {t: [] for t in TABLES}
        self.queue = list(TABLES)
        self.table: str | None = None

    def act(self, observation: dict | None) -> dict:
        if observation is not None:
            if observation.get("error"):
                print(f"tool error: {observation['error']['code']}", file=sys.stderr)
            result = observation.get("result")
            if self.table and isinstance(result, dict) and "records" in result:
                self.records[self.table].extend(result["records"])
                if result["next_cursor"] is not None:
                    return {"action": "list_records", "table": self.table, "cursor": result["next_cursor"], "limit": 50}
        if self.queue:
            self.table = self.queue.pop(0)
            return {"action": "list_records", "table": self.table, "cursor": None, "limit": 50}
        return {"action": "submit", "findings": {"episode_id": self.episode_id, "findings": self.duplicates()}}

    def duplicates(self) -> list[dict]:
        ap_rows: dict[str, list[dict]] = defaultdict(list)
        for row in self.records["ledger"]:
            if row["account"] == self.ap and row["invoice_id"] and row["payment_id"] is None:
                ap_rows[row["invoice_id"]].append(row)
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for inv in self.records["invoices"]:
            rows = ap_rows.get(inv["invoice_id"], [])
            active = rows and not any(r["debit_minor"] for r in rows)          # posted and not reversed
            if active:
                content = (inv["issued_at"], inv["currency"], inv["total_minor"], json.dumps(inv["line_items"], sort_keys=True))
                groups[(inv["entity_id"], inv["vendor_ref"], content)].append(inv)
        findings = []
        for copies in groups.values():
            if len(copies) != 2:
                continue
            a, b = sorted(copies, key=lambda d: d["invoice_id"])
            row = next(r for r in ap_rows[a["invoice_id"]] if r["credit_minor"] > 0)
            findings.append({"type": "duplicate_invoice", "affected_ids": [a["invoice_id"], b["invoice_id"]],
                             "claimed_amount_minor": row["credit_minor"], "currency": self.base,
                             "evidence_ids": [a["doc_id"], b["doc_id"], row["row_id"]],
                             "explanation": f"vendor_ref {a['vendor_ref']} recorded twice"})
        return sorted(findings, key=lambda f: f["affected_ids"])[:30]


def main() -> int:
    agent = DuplicateInvoiceAgent()
    for line in sys.stdin:
        msg = json.loads(line)
        if msg["type"] == "end":
            return 0
        if msg["type"] == "reset":
            agent.reset(msg["observation"])
            action = agent.act(None)
        elif msg["type"] == "step" and not (msg["terminated"] or msg["truncated"]):
            action = agent.act(msg["observation"])
        else:
            continue
        sys.stdout.write(json.dumps({"action": action}) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
