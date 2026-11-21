"""Baseline 3 - "Mark everything" attack.

Lists invoices and payments, then submits the maximum 30 findings: every
document accused of every error type in turn, with its own amount and its own
document as evidence. A sound reward must make this strictly worse than silence
on clean books and no better than silence on erroneous books.
"""

from __future__ import annotations

from ophanim.policies.base import list_action, submit_action

_TYPES = ("duplicate_invoice", "payment_allocation", "fx_rate", "period_attribution")


class MarkEverything:
    name = "mark_everything"

    def reset(self, observation: dict, info: dict) -> None:
        self.manifest = observation["manifest"]
        self.queue = ["invoices", "payments"]
        self.docs: list[dict] = []
        self.pending = False

    def act(self, observation: dict) -> dict:
        res = observation.get("result") if isinstance(observation, dict) else None
        if self.pending and isinstance(res, dict) and "records" in res:
            self.docs.extend(res["records"])
            if res["next_cursor"]:
                return list_action(res["table"], res["next_cursor"])
            self.pending = False
        if self.queue:
            self.pending = True
            return list_action(self.queue.pop(0), None)
        findings = []
        for i, doc in enumerate(self.docs[:30]):
            ident = doc.get("invoice_id") if "total_minor" in doc else doc.get("payment_id")
            findings.append({
                "type": _TYPES[i % 4],
                "affected_ids": [ident],
                "claimed_amount_minor": doc.get("total_minor", doc.get("amount_minor", 0)),
                "currency": self.manifest["base_currency"],
                "evidence_ids": [doc["doc_id"]],
                "explanation": "everything is suspicious",
            })
        return submit_action(self.manifest["episode_id"], findings)
