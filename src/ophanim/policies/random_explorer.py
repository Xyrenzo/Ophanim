"""Baseline 1 - Random explorer with a fixed seed.

Takes 5-40 random actions (some deliberately invalid), remembering every id it
sees, then submits 0-3 random findings built from observed ids. Deterministic
for a given policy seed and observation sequence.
"""

from __future__ import annotations

from ophanim.policies.base import list_action, submit_action
from ophanim.rng import DeterministicRng

_TABLES = ("ledger", "invoices", "payments", "fx")
_TYPES = ("duplicate_invoice", "payment_allocation", "fx_rate", "period_attribution")


class RandomExplorer:
    name = "random_explorer"

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

    def reset(self, observation: dict, info: dict) -> None:
        # Fixed policy seed + the public episode id: reproducible per episode, varied across episodes.
        self.rng = DeterministicRng.from_seed(self.seed).child(f"episode/{observation['manifest']['episode_id']}")
        self.manifest = observation["manifest"]
        self.budget = self.rng.randint(5, 40)
        self.steps = 0
        self.cursors: dict[str, str | None] = {}
        self.ids: dict[str, list[str]] = {"row": [], "doc": [], "invoice": [], "payment": [], "fx": []}
        self.amounts: list[int] = []

    def _ingest(self, observation: dict) -> None:
        res = observation.get("result") if isinstance(observation, dict) else None
        if not isinstance(res, dict):
            return
        records = res.get("records") or ([res["record"]] if "record" in res else []) or \
            ([res["document"]] if "document" in res else [])
        if "next_cursor" in res:
            self.cursors[res["table"]] = res["next_cursor"]
        for rec in records:
            if "row_id" in rec:
                self.ids["row"].append(rec["row_id"])
                self.amounts.append(rec["debit_minor"] or rec["credit_minor"])
            if "doc_id" in rec:
                self.ids["doc"].append(rec["doc_id"])
            if "invoice_id" in rec and "total_minor" in rec:
                self.ids["invoice"].append(rec["invoice_id"])
            if "payment_id" in rec and "amount_minor" in rec:
                self.ids["payment"].append(rec["payment_id"])
            if "rate" in rec:
                self.ids["fx"].append(f"{rec['date']}:{rec['source_currency']}:{rec['target_currency']}")

    def act(self, observation: dict) -> dict:
        self._ingest(observation)
        self.steps += 1
        r = self.rng
        if self.steps > self.budget:
            return self._submit()
        kind = r.weighted_choice(["list", "get", "doc", "calc", "junk"], [45, 20, 15, 10, 10])
        if kind == "list":
            table = r.choice(_TABLES)
            return list_action(table, self.cursors.get(table) if r.chance(1, 2) else None, r.randint(1, 50))
        if kind == "get" and self.ids["row"]:
            return {"action": "get_record", "table": "ledger", "id": r.choice(self.ids["row"])}
        if kind == "doc" and self.ids["doc"]:
            return {"action": "get_document", "doc_id": r.choice(self.ids["doc"])}
        if kind == "calc":
            return {"action": "calculator", "expression": f"{r.randint(1, 9999)} * {r.randint(1, 99)}.{r.randint(0, 99)}"}
        return r.choice([{"action": "explore"}, {"action": "get_record", "table": "secrets", "id": "x"},
                         {"action": "get_document", "doc_id": "DOC-" + r.token(10)}])

    def _submit(self) -> dict:
        r = self.rng
        findings = []
        pool = self.ids["invoice"] + self.ids["payment"]
        evidence_pool = self.ids["row"] + self.ids["doc"] + self.ids["fx"]
        for _ in range(r.randint(0, 3)):
            if not pool:
                break
            findings.append({
                "type": r.choice(_TYPES),
                "affected_ids": r.sample(pool, min(len(pool), r.randint(1, 2))),
                "claimed_amount_minor": r.choice(self.amounts) if self.amounts else r.randint(1, 10**6),
                "currency": self.manifest["base_currency"],
                "evidence_ids": r.sample(evidence_pool, min(len(evidence_pool), r.randint(1, 3))),
                "explanation": "random guess",
            })
        return submit_action(self.manifest["episode_id"], findings)
