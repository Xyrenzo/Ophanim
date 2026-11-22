"""The judge: holds one episode's sealed truth and scores submissions.

The environment owns a Judge but exposes only its *terminal reward* (open
training mode) or nothing at all (closed evaluation mode). Diagnostics
(per-finding verdicts, error logs) stay in ``Judge.log`` / ``Judge.outcome`` and
are read by the evaluation runner after the episode, never by the agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import ValidationError

from ophanim.evaluator.matcher import MatchResult, match
from ophanim.evaluator.reward import INVALID_SUBMISSION_REWARD, f1, official_reward, precision, recall
from ophanim.schemas import FindingsSubmission


def validate_submission(raw_findings: object, expected_episode_id: str) -> tuple[FindingsSubmission | None, list[str]]:
    """Structural validation of a findings submission (the single canonical implementation).

    Used by the judge before scoring and by the closed-mode environment, which accepts or rejects a
    submission without holding any truth. Needs only the public episode id.
    Returns (submission, []) when valid, otherwise (None, bounded list of error descriptions).
    """
    try:
        submission = FindingsSubmission.model_validate(raw_findings)
    except ValidationError as exc:
        return None, [f"{'.'.join(map(str, e['loc']))}: {e['type']}" for e in exc.errors()][:20]
    if submission.episode_id != expected_episode_id:  # exact, like every other id
        return None, ["episode_id: does not match the current episode"]
    return submission, []


@dataclass
class Outcome:
    reward: float
    valid: bool
    reason: str  # submitted | invalid_submission | step_limit | time_limit
    inspection_steps: int
    tp: int = 0
    fp: int = 0
    fn: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    findings_submitted: int = 0
    match: MatchResult | None = None

    def metrics(self) -> dict:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "precision": self.precision, "recall": self.recall,
                "f1": self.f1, "inspection_steps": self.inspection_steps, "findings_submitted": self.findings_submitted}


@dataclass
class Judge:
    sealed: object  # SealedEpisode (typed loosely to keep this module import-light)
    log: list[dict] = field(default_factory=list)
    outcome: Outcome | None = None

    def _score(self, findings, inspection_steps: int, reason: str) -> Outcome:
        truth = self.sealed.truth
        result = match(findings, truth.issues, self.sealed.evidence_universe, truth.tolerance_minor)
        f = f1(result.tp, result.fp, result.fn)
        out = Outcome(
            reward=official_reward(result.tp, result.fp, result.fn, inspection_steps),
            valid=True, reason=reason, inspection_steps=inspection_steps,
            tp=result.tp, fp=result.fp, fn=result.fn,
            precision=float(precision(result.tp, result.fp)), recall=float(recall(result.tp, result.fn)), f1=float(f),
            findings_submitted=len(findings), match=result,
        )
        self.log.append({"event": "scored", "reason": reason, **out.metrics(), "reward": out.reward,
                         "verdicts": [{"finding": v.index, "claimed_type": findings[v.index].type,
                                       "matched_issue": v.matched_issue, "reasons": list(v.reasons)}
                                      for v in result.verdicts],
                         "unmatched_issues": result.unmatched_issues})
        self.outcome = out
        return out

    def submit(self, raw_findings: object, inspection_steps: int) -> Outcome:
        submission, errors = validate_submission(raw_findings, self.sealed.truth.episode_id)
        if submission is None:
            return self._invalid(inspection_steps, errors)
        return self._score(submission.findings, inspection_steps, "submitted")

    def empty_answer(self, inspection_steps: int, reason: str) -> Outcome:
        """Truncation (step or time limit): scored as an empty final answer."""
        return self._score([], inspection_steps, reason)

    def _invalid(self, inspection_steps: int, errors: list[str]) -> Outcome:
        out = Outcome(reward=INVALID_SUBMISSION_REWARD, valid=False, reason="invalid_submission",
                      inspection_steps=inspection_steps)
        self.log.append({"event": "invalid_submission", "errors": errors, "reward": out.reward,
                         "inspection_steps": inspection_steps})
        self.outcome = out
        return out
