"""Ablations of the scripted reference auditor (agent side, public data only).

Each ablation removes exactly one ingredient of the reference auditor and keeps everything else, including
its acquisition (it pages through all four tables in the same order, so inspection steps are identical):

  ablation_no_duplicate_check    the duplicate-invoice check is switched off
  ablation_no_allocation_check   the payment-allocation check is switched off
  ablation_no_fx_check           the FX-rate check is switched off
  ablation_no_period_check       the reporting-period check is switched off
  ablation_utc_dates             no company-timezone reasoning: accounting dates are taken in UTC, which
                                 changes both the period test and the FX rate date
  ablation_documents_only_evidence  findings cite only the source documents, without ledger rows or FX keys

These are scripted, hand-written variants used to measure which part of the procedure produces which part
of the score. They are not trained models and never read truth, provenance or seeds. Like every policy
here, this module may not import evaluator or generator code (tests/unit/test_independence.py).
"""

from __future__ import annotations

from ophanim.audit.dataset import PublicDataset
from ophanim.audit.reconcile import reconcile
from ophanim.policies.base import submit_action
from ophanim.policies.reference_auditor import ReferenceAuditor, findings_from_report


class AblatedAuditor(ReferenceAuditor):
    kind = "ablation"

    def __init__(self, name: str, *, drop_types: tuple[str, ...] = (), utc_dates: bool = False,
                 documents_only_evidence: bool = False) -> None:
        super().__init__()
        self.name = name
        self.drop_types = drop_types
        self.utc_dates = utc_dates
        self.documents_only_evidence = documents_only_evidence

    def _submit(self) -> dict:
        policy = dict(self.policy, timezone="+00:00") if self.utc_dates else self.policy
        report = reconcile(PublicDataset.from_tables(self.manifest, policy, self.tables))
        findings = [f for f in findings_from_report(report) if f["type"] not in self.drop_types]
        if self.documents_only_evidence:
            docs = {d["doc_id"] for t in ("invoices", "payments") for d in self.tables[t]}
            findings = [dict(f, evidence_ids=[e for e in f["evidence_ids"] if e in docs]) for f in findings]
        return submit_action(self.manifest["episode_id"], findings)


ABLATION_POLICIES = {
    "ablation_no_duplicate_check": lambda seed=0: AblatedAuditor("ablation_no_duplicate_check", drop_types=("duplicate_invoice",)),
    "ablation_no_allocation_check": lambda seed=0: AblatedAuditor("ablation_no_allocation_check", drop_types=("payment_allocation",)),
    "ablation_no_fx_check": lambda seed=0: AblatedAuditor("ablation_no_fx_check", drop_types=("fx_rate",)),
    "ablation_no_period_check": lambda seed=0: AblatedAuditor("ablation_no_period_check", drop_types=("period_attribution",)),
    "ablation_utc_dates": lambda seed=0: AblatedAuditor("ablation_utc_dates", utc_dates=True),
    "ablation_documents_only_evidence": lambda seed=0: AblatedAuditor("ablation_documents_only_evidence", documents_only_evidence=True),
}
