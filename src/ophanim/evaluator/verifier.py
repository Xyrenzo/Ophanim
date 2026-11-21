"""Independent verification of a generated episode (evaluator side).

Checks, using the stdlib-only auditor in ``ophanim.audit`` (no generator code):

  1. formats    - public files follow the published schemas;
  2. clean      - BEFORE mutation, full reconciliation finds zero issues and zero
                  anomalies (all accounting equalities hold);
  3. declared   - AFTER mutation, full reconciliation finds exactly the issues
                  declared in truth.json (same type, ids, amount, currency):
                  nothing missing, nothing extra, no anomalies;
  4. evidence   - every allowed evidence set of every issue exists in the public
                  data and, on its own, proves the issue and its amount.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ophanim.audit.dataset import PublicDataset
from ophanim.audit.evidence import check_evidence
from ophanim.audit.formats import check_formats
from ophanim.audit.reconcile import reconcile
from ophanim.schemas import TruthFile


@dataclass
class VerificationReport:
    problems: list[str] = field(default_factory=list)
    issues_declared: int = 0
    issues_found_independently: int = 0
    evidence_sets_checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems


def verify(dataset: PublicDataset, truth: TruthFile, pre_mutation_tables: dict | None = None) -> VerificationReport:
    rep = VerificationReport(issues_declared=len(truth.issues))
    rep.problems += [f"format: {x}" for x in check_formats(dataset)]
    if truth.episode_id != dataset.manifest.get("episode_id"):
        rep.problems.append("truth episode_id does not match manifest")

    # 2. pre-mutation books are clean
    if pre_mutation_tables is not None:
        clean = PublicDataset.from_tables(dataset.manifest, dataset.policy, pre_mutation_tables)
        clean_report = reconcile(clean)
        rep.problems += [f"pre-mutation anomaly: {a}" for a in clean_report.anomalies]
        rep.problems += [f"pre-mutation discrepancy: {f.type} {f.affected_ids}" for f in clean_report.findings]

    # 3. post-mutation books show exactly the declared discrepancies
    report = reconcile(dataset)
    rep.issues_found_independently = len(report.findings)
    rep.problems += [f"anomaly: {a}" for a in report.anomalies]
    declared = {(t.type, tuple(sorted(t.affected_ids)), t.currency): t for t in truth.issues}
    found = {f.key(): f for f in report.findings}
    for k in sorted(set(declared) - set(found)):
        rep.problems.append(f"declared issue not visible in public records: {k}")
    for k in sorted(set(found) - set(declared)):
        rep.problems.append(f"undeclared discrepancy in public records: {k}")
    for k in sorted(set(declared) & set(found)):
        if declared[k].expected_amount_minor != found[k].amount_minor:
            rep.problems.append(f"amount mismatch for {k}: truth {declared[k].expected_amount_minor}, records {found[k].amount_minor}")
        if not any(set(s) <= set(found[k].evidence_ids) for s in declared[k].allowed_evidence_sets):
            rep.problems.append(f"independent evidence for {k} matches no allowed evidence set")
    if len(declared) != len(truth.issues):
        rep.problems.append("truth contains issues with identical type and affected ids")

    # 4. every allowed evidence set is sufficient on its own
    index = dataset.records_by_evidence_id()
    for t in truth.issues:
        for s in t.allowed_evidence_sets:
            rep.evidence_sets_checked += 1
            missing = [i for i in s if i not in index]
            if missing:
                rep.problems.append(f"{t.issue_id}: evidence ids not in public data: {missing}")
                continue
            reason = check_evidence(t.type, t.affected_ids, t.expected_amount_minor, t.currency,
                                    {i: index[i] for i in s}, dataset.policy)
            if reason:
                rep.problems.append(f"{t.issue_id}: evidence set insufficient ({reason})")
    return rep


def verify_generated(episode) -> VerificationReport:
    """Verify an in-memory GeneratedEpisode."""
    ds = PublicDataset.from_tables(episode.public.manifest, episode.public.policy, episode.public.tables)
    return verify(ds, episode.sealed.truth, episode.sealed.provenance["pre_mutation"]["tables"])


def verify_directory(directory: str | Path) -> VerificationReport:
    """Verify an episode written to disk as <dir>/public and <dir>/evaluator."""
    import json

    d = Path(directory)
    ds = PublicDataset.from_directory(d / "public")
    truth = TruthFile.model_validate(json.loads((d / "evaluator" / "truth.json").read_text(encoding="utf-8")))
    prov = json.loads((d / "evaluator" / "provenance.json").read_text(encoding="utf-8"))
    return verify(ds, truth, prov["pre_mutation"]["tables"])
