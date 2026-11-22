"""Agent-side policies (baseline adapters).

Policies see only observations (public data) and return JSON actions. They
must never import ``ophanim.evaluator`` or ``ophanim.generator`` (enforced by
tests/unit/test_independence.py). The evaluator-only Oracle lives in
``ophanim.evaluator.oracle``, not here.

Official baselines from the case: random_explorer (fixed seed),
simple_reconciliation, mark_everything, and the evaluator-side oracle.
reference_auditor is an extra scripted policy demonstrating solvability. The ablation_* policies
(policies/ablations.py) are scripted variants of it with one ingredient removed, for ablation studies; they
are kept in a separate registry so that the official baselines and published trajectories are unchanged.

No policy in this package is a trained model.
"""

from ophanim.policies.ablations import ABLATION_POLICIES, AblatedAuditor
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


# What each policy is, for reports: none of them is a learned model.
POLICY_KINDS = {
    "random_explorer": "baseline",
    "simple_reconciliation": "baseline",
    "mark_everything": "baseline",
    "reference_auditor": "scripted reference",
    **{name: "scripted ablation" for name in ABLATION_POLICIES},
}


def make_policy(name: str, seed: int = 0) -> Policy:
    factory = AGENT_POLICIES.get(name) or ABLATION_POLICIES.get(name)
    if factory is None:
        raise ValueError(f"unknown policy {name!r}; choose from {sorted(AGENT_POLICIES) + sorted(ABLATION_POLICIES)}")
    return factory(seed)


__all__ = ["ABLATION_POLICIES", "AGENT_POLICIES", "AblatedAuditor", "MarkEverything", "POLICY_KINDS", "Policy",
           "RandomExplorer", "ReferenceAuditor", "SimpleReconciliation", "make_policy"]
