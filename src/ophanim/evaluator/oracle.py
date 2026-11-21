"""Oracle policy - EVALUATOR ONLY.

The oracle reads the sealed truth and submits exactly the correct findings with
a valid evidence set and zero inspection steps. It measures the *maximum*
achievable reward and checks that the evaluator can award it. It says nothing
about how hard the environment is and must never be given to an agent: it runs
inside the evaluator process, receives the SealedEpisode directly, and is not
reachable through any agent tool or the agent-side protocol.
"""

from __future__ import annotations


def oracle_submission(sealed) -> dict:
    truth = sealed.truth
    return {
        "episode_id": truth.episode_id,
        "findings": [
            {
                "type": issue.type,
                "affected_ids": list(issue.affected_ids),
                "claimed_amount_minor": issue.expected_amount_minor,
                "currency": issue.currency,
                "evidence_ids": list(issue.allowed_evidence_sets[0]),
                "explanation": "oracle",
            }
            for issue in truth.issues
        ],
    }


def oracle_action(sealed) -> dict:
    return {"action": "submit", "findings": oracle_submission(sealed)}


class OraclePolicy:
    """Baseline 4 adapter. Constructed by the evaluator with the sealed episode; submits immediately."""

    name = "oracle"

    def __init__(self, sealed) -> None:
        self._sealed = sealed

    def reset(self, observation: dict, info: dict) -> None:
        if observation["manifest"]["episode_id"] != self._sealed.truth.episode_id:
            raise ValueError("oracle bound to a different episode")

    def act(self, observation: dict) -> dict:
        return oracle_action(self._sealed)
