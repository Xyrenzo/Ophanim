"""Reference auditor: a scripted policy that solves episodes from public data.

It pages through every table with ``list_records`` (about 15-30 steps), rebuilds
the public dataset from what it observed, runs the published reconciliation
procedure (``ophanim.audit``) and submits the findings.

Purpose: demonstrate that every episode is solvable through the agent tools
within the 100-step budget, using only accessible evidence. It is NOT an
Oracle: it never sees truth.json, provenance or the seed.
"""

from __future__ import annotations

from ophanim.audit.dataset import PublicDataset
from ophanim.audit.reconcile import reconcile
from ophanim.policies.base import list_action, submit_action

_TABLES = ("ledger", "invoices", "payments", "fx")


class ReferenceAuditor:
    name = "reference_auditor"

    def __init__(self, page_size: int = 50) -> None:
        self.page_size = page_size

    def reset(self, observation: dict, info: dict) -> None:
        self.manifest = observation["manifest"]
        self.policy = observation["policy"]
        self.tables: dict[str, list[dict]] = {t: [] for t in _TABLES}
        self.queue = list(_TABLES)
        self.pending: tuple[str, str | None] | None = None

    def act(self, observation: dict) -> dict:
        result = observation.get("result") if isinstance(observation, dict) else None
        if self.pending is not None and observation.get("ok") and isinstance(result, dict) and "records" in result:
            table = result["table"]
            self.tables[table].extend(result["records"])
            if result["next_cursor"] is not None:
                self.pending = (table, result["next_cursor"])
                return list_action(table, result["next_cursor"], self.page_size)
            self.pending = None
        if self.queue:
            table = self.queue.pop(0)
            self.pending = (table, None)
            return list_action(table, None, self.page_size)
        return self._submit()

    def _submit(self) -> dict:
        ds = PublicDataset.from_tables(self.manifest, self.policy, self.tables)
        return submit_action(self.manifest["episode_id"], findings_from_report(reconcile(ds)))


def findings_from_report(report) -> list[dict]:
    """Audit findings -> official finding dicts, within the published limits (30 findings, 10 evidence ids)."""
    return [
        {
            "type": f.type,
            "affected_ids": list(f.affected_ids),
            "claimed_amount_minor": f.amount_minor,
            "currency": f.currency,
            "evidence_ids": list(f.evidence_ids)[:10],
            "explanation": f.note[:1000],
        }
        for f in report.findings[:30]
    ]
