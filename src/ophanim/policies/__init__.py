"""Agent-side policies (baseline adapters).

Policies see only observations (public data) and return JSON actions. They
must never import ``ophanim.evaluator`` or ``ophanim.generator`` (enforced by
tests/unit/test_independence.py). The evaluator-only Oracle lives in
``ophanim.evaluator.oracle``, not here.

Official baselines from the case: random_explorer (fixed seed),
simple_reconciliation, mark_everything, and the evaluator-side oracle.
reference_auditor is an extra scripted policy demonstrating solvability.
"""

from ophanim.policies.base import Policy
from ophanim.policies.mark_everything import MarkEverything
from ophanim.policies.random_explorer import RandomExplorer
from ophanim.policies.reference_auditor import ReferenceAuditor
from ophanim.policies.simple_reconciliation import SimpleReconciliation

AGENT_POLICIES = {
    "random_explorer": lambda seed=0: RandomExplorer(seed),
    "simple_reconciliation": lambda seed=0: SimpleReconciliation(),
    "mark_everything": lambda seed=0: MarkEverything(),
    "reference_auditor": lambda seed=0: ReferenceAuditor(),
}


def make_policy(name: str, seed: int = 0) -> Policy:
    try:
        return AGENT_POLICIES[name](seed)
    except KeyError:
        raise ValueError(f"unknown policy {name!r}; choose from {sorted(AGENT_POLICIES)}") from None


__all__ = ["AGENT_POLICIES", "MarkEverything", "Policy", "RandomExplorer", "ReferenceAuditor", "SimpleReconciliation", "make_policy"]
