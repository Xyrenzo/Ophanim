"""The shared, deterministic matcher (published rules).

A finding is ELIGIBLE for a truth issue when ALL of these hold:
  1. finding.type == issue.type
  2. normalised set(finding.affected_ids) == set(issue.affected_ids)
  3. |finding.claimed_amount_minor - issue.expected_amount_minor| <= tolerance_minor (1)
  4. finding.currency == issue.currency (exact ISO code; no conversion)
  5. every evidence id exists in the episode's public data, AND the normalised
     evidence set contains at least one complete allowed evidence set
     (extra valid ids are allowed, up to the 10-id limit).

Normalisation of ids: strip surrounding whitespace, upper-case. affected_ids and
evidence_ids are compared as sets (order and repeats are ignored).

Matching is one-to-one: a maximum bipartite matching computed with augmenting
paths, visiting findings in submission order and candidate issues in
issue_id order, so the result is deterministic. Each truth issue can be matched
by at most one finding; a repeated finding therefore becomes a false positive.

The explanation text is never read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ophanim.schemas import Finding, TruthIssue


def normalize_id(value: str) -> str:
    return value.strip().upper()


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


def eligibility(finding: Finding, issue: TruthIssue, evidence_universe: frozenset[str], tolerance: int) -> list[str]:
    """Reasons why ``finding`` cannot match ``issue`` (empty list = eligible)."""
    reasons: list[str] = []
    if finding.type != issue.type:
        reasons.append("type")
    if {normalize_id(x) for x in finding.affected_ids} != {normalize_id(x) for x in issue.affected_ids}:
        reasons.append("affected_ids")
    if abs(finding.claimed_amount_minor - issue.expected_amount_minor) > tolerance:
        reasons.append("amount")
    if finding.currency != issue.currency:
        reasons.append("currency")
    evidence = {normalize_id(x) for x in finding.evidence_ids}
    if not evidence <= evidence_universe:
        reasons.append("evidence_unknown_id")
    elif not any({normalize_id(x) for x in allowed} <= evidence for allowed in issue.allowed_evidence_sets):
        reasons.append("evidence_insufficient")
    return reasons


def match(findings: list[Finding], issues: list[TruthIssue], evidence_universe: frozenset[str], tolerance: int) -> MatchResult:
    universe = frozenset(normalize_id(x) for x in evidence_universe)
    ordered = sorted(issues, key=lambda t: t.issue_id)
    edges: list[list[int]] = []
    reasons_by_finding: list[tuple[str, ...]] = []
    for f in findings:
        adj = []
        best: tuple[str, ...] | None = None
        for j, t in enumerate(ordered):
            r = eligibility(f, t, universe, tolerance)
            if not r:
                adj.append(j)
            elif best is None or len(r) < len(best):
                best = tuple(r)
        edges.append(adj)
        reasons_by_finding.append(() if adj else (best or ("no_issue",)))

    owner: list[int | None] = [None] * len(ordered)  # issue index -> finding index

    def augment(i: int, seen: set[int]) -> bool:
        for j in edges[i]:
            if j in seen:
                continue
            seen.add(j)
            if owner[j] is None or augment(owner[j], seen):
                owner[j] = i
                return True
        return False

    for i in range(len(findings)):
        augment(i, set())

    matched_by_finding: dict[int, str] = {owner[j]: ordered[j].issue_id for j in range(len(ordered)) if owner[j] is not None}
    verdicts = []
    for i in range(len(findings)):
        if i in matched_by_finding:
            verdicts.append(FindingVerdict(i, matched_by_finding[i], ()))
        else:
            why = reasons_by_finding[i] if reasons_by_finding[i] else ("duplicate_or_already_matched",)
            verdicts.append(FindingVerdict(i, None, why))
    tp = len(matched_by_finding)
    return MatchResult(
        tp=tp,
        fp=len(findings) - tp,
        fn=len(ordered) - tp,
        pairs=sorted(matched_by_finding.items()),
        verdicts=verdicts,
        unmatched_issues=[ordered[j].issue_id for j in range(len(ordered)) if owner[j] is None],
    )
