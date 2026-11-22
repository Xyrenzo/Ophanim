"""The shared, deterministic matcher (published rules; official Genesis FinTech matcher conventions).

A finding is ELIGIBLE for a truth issue when ALL of these hold (exact comparisons throughout):
  1. finding.type == issue.type                       (exact string; no aliases, case or space folding)
  2. set(finding.affected_ids) == set(issue.affected_ids)   (exact ids; order/repeats ignored)
  3. |finding.claimed_amount_minor - issue.expected_amount_minor| <= tau   (tau = tolerance_minor, default 0)
  4. finding.currency == issue.currency               (exact string; no conversion, case or space folding)
  5. every evidence id is an existing id that the tools can return (row_id, doc_id, invoice_id,
     payment_id, FX key), AND set(finding.evidence_ids) contains at least one complete allowed
     evidence set (extra existing ids are allowed).

Ids are compared EXACTLY: case and whitespace are significant; nothing is stripped, upper-cased,
converted from numbers or aliased. Structural limits are enforced by the schema on the raw lists
before any set conversion (``ophanim.schemas.Finding``).

Matching (one-to-one): every submitted finding is its own vertex (repeats are not merged); every truth
issue is a vertex; an edge exists only if the finding is eligible for the issue. TP is the size K of a
MAXIMUM-cardinality matching. Among all maximum matchings the official tie-break selects the one whose
sorted sequence of (issue_id, finding index) pairs is lexicographically smallest, with issue_ids sorted
by Unicode code points. TP/FP/FN never depend on the tie-break; only which identical finding is
reported as matched does. FP = findings − K; FN = issues − K. Explanations are never read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ophanim.schemas import Finding, TruthIssue


@dataclass(frozen=True)
class FindingVerdict:
    """Evaluator-only diagnostics for one finding."""

    index: int
    matched_issue: str | None
    reasons: tuple[str, ...]


@dataclass
class MatchResult:
    tp: int
    fp: int
    fn: int
    pairs: list[tuple[int, str]] = field(default_factory=list)  # (finding index, issue_id)
    verdicts: list[FindingVerdict] = field(default_factory=list)
    unmatched_issues: list[str] = field(default_factory=list)


def check_tolerance(tolerance: object) -> int:
    """tau must be an explicit non-negative integer (bool is not an integer here)."""
    if isinstance(tolerance, bool) or not isinstance(tolerance, int) or tolerance < 0:
        raise ValueError("tolerance_minor must be a non-negative integer")
    return tolerance


def eligibility(finding: Finding, issue: TruthIssue, evidence_universe: frozenset[str], tolerance: int) -> list[str]:
    """Reasons why ``finding`` cannot match ``issue`` (empty list = eligible). All comparisons are exact."""
    reasons: list[str] = []
    if finding.type != issue.type:
        reasons.append("type")
    if set(finding.affected_ids) != set(issue.affected_ids):
        reasons.append("affected_ids")
    if abs(finding.claimed_amount_minor - issue.expected_amount_minor) > tolerance:
        reasons.append("amount")
    if finding.currency != issue.currency:
        reasons.append("currency")
    evidence = set(finding.evidence_ids)
    if not evidence <= evidence_universe:
        reasons.append("evidence_unknown_id")
    elif not any(set(allowed) <= evidence for allowed in issue.allowed_evidence_sets):
        reasons.append("evidence_insufficient")
    return reasons


def _max_matching(adj: list[list[int]], issues: list[int], available: set[int]) -> int:
    """Size of a maximum matching between ``issues`` and the ``available`` findings (augmenting paths)."""
    owner: dict[int, int] = {}  # finding -> issue

    def augment(j: int, seen: set[int]) -> bool:
        for i in adj[j]:
            if i not in available or i in seen:
                continue
            seen.add(i)
            if i not in owner or augment(owner[i], seen):
                owner[i] = j
                return True
        return False

    return sum(1 for j in issues if augment(j, set()))


def match(findings: list[Finding], issues: list[TruthIssue], evidence_universe: frozenset[str], tolerance: int) -> MatchResult:
    check_tolerance(tolerance)
    universe = frozenset(evidence_universe)
    ordered = sorted(issues, key=lambda t: t.issue_id)  # Python str order = Unicode code points

    adj: list[list[int]] = [[] for _ in ordered]        # issue j -> eligible finding indices, ascending
    reasons_by_finding: list[tuple[str, ...]] = []
    for i, f in enumerate(findings):
        best: tuple[str, ...] | None = None
        eligible = False
        for j, t in enumerate(ordered):
            r = eligibility(f, t, universe, tolerance)
            if not r:
                adj[j].append(i)
                eligible = True
            elif best is None or len(r) < len(best):
                best = tuple(r)
        reasons_by_finding.append(() if eligible else (best or ("no_issue",)))

    all_findings = set(range(len(findings)))
    k = _max_matching(adj, list(range(len(ordered))), all_findings)

    # Official tie-break: walk issues in code-point order; give each the lowest finding index that still
    # allows a maximum matching of size k for the remaining issues; skip issues that cannot be matched.
    chosen: dict[int, int] = {}                          # issue j -> finding i
    used: set[int] = set()
    for j in range(len(ordered)):
        later = list(range(j + 1, len(ordered)))
        for i in adj[j]:
            if i in used:
                continue
            if len(chosen) + 1 + _max_matching(adj, later, all_findings - used - {i}) == k:
                chosen[j] = i
                used.add(i)
                break
    assert len(chosen) == k, "tie-break must preserve maximum cardinality"

    matched_by_finding = {i: ordered[j].issue_id for j, i in chosen.items()}
    verdicts = []
    for i in range(len(findings)):
        if i in matched_by_finding:
            verdicts.append(FindingVerdict(i, matched_by_finding[i], ()))
        else:
            why = reasons_by_finding[i] if reasons_by_finding[i] else ("duplicate_or_already_matched",)
            verdicts.append(FindingVerdict(i, None, why))
    return MatchResult(
        tp=k,
        fp=len(findings) - k,
        fn=len(ordered) - k,
        pairs=sorted(matched_by_finding.items()),
        verdicts=verdicts,
        unmatched_issues=[ordered[j].issue_id for j in range(len(ordered)) if j not in chosen],
    )
