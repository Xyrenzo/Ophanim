"""Independent auditing of the PUBLIC records.

This package must stay independent from the generator: it imports nothing from
``ophanim`` outside ``ophanim.audit`` (enforced by tests/unit/test_independence.py)
and re-implements conversion, rounding and time-zone rules from the published
policy text. It is used by:

  * the evaluator-side verifier, to prove that the hidden truth is exactly what
    the public records show (no missing, no extra, no contradictory issues) and
    that each allowed evidence set independently supports its issue;
  * the reference auditor policy, which demonstrates that every episode is
    solvable through the agent tools within the step budget.

It never reads truth.json or provenance.json.
"""

from ophanim.audit.dataset import PublicDataset
from ophanim.audit.reconcile import AuditFinding, AuditReport, reconcile

__all__ = ["AuditFinding", "AuditReport", "PublicDataset", "reconcile"]
