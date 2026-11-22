"""Red herrings: legitimate records that look suspicious, and false-positive resistance.

1. Every red-herring kind has a valid accounting explanation, checked on the PUBLIC records it names
   (clean books, so nothing else touches those documents).
2. The independent auditor never reports a red herring: on clean books it finds nothing; on books that
   mix real errors with red herrings it finds exactly the injected issues and never names a red-herring
   document that is not itself the subject of an error.
3. The red herrings are adversarial in practice: the naive reconciliation baseline reports some of them,
   while the reference auditor reports none.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

import pytest

from ophanim.analytics import TrajectoryLogger
from ophanim.audit.dataset import PublicDataset
from ophanim.audit.reconcile import reconcile
from ophanim.audit.rules import Rules
from ophanim.env import OphanimEnv
from ophanim.evaluator.provenance_check import PROTECTED_RED_HERRINGS
from ophanim.evaluator.runner import run_episode
from ophanim.evaluator.verifier import verify_generated
from ophanim.generator.episode import generate_episode
from ophanim.policies import ReferenceAuditor, SimpleReconciliation

KINDS = ("recurring_same_amount", "repeat_order_same_amount", "vendor_ref_collision", "reversed_duplicate",
         "split_payment", "partial_payment", "batch_payment", "unidentified_payment", "correct_refund",
         "boundary_utc_date")
PROFILES = ("retail", "trading", "software", "manufacturing", "logistics", "consulting")
CLEAN = [(3000 + i, {"profile": PROFILES[i % 6], "size": ("small", "medium", "large")[i % 3],
                     "distractors": ("normal", "high")[i % 2]}) for i in range(24)]
MIXED = [(3100 + i, {"profile": PROFILES[i % 6], "distractors": "high",
                     "errors": {"duplicate_invoice": 1, "payment_allocation": 1, "fx_rate": 1, "period_attribution": 1},
                     "scenarios": {"fx_partial_payment_boundary": i % 2, "fx_invoice_unapplied_payment": (i + 1) % 2}})
         for i in range(12)]


@pytest.fixture(scope="module")
def clean_episodes():
    return [generate_episode(s, c) for s, c in CLEAN]


class _View:
    """Public records of one episode, addressed through the evaluator-only id map."""

    def __init__(self, ep) -> None:
        self.m = ep.sealed.provenance["id_map"]
        t = ep.public.tables
        self.inv = {d["invoice_id"]: d for d in t["invoices"]}
        self.pay = {d["payment_id"]: d for d in t["payments"]}
        self.rows = defaultdict(list)
        for r in t["ledger"]:
            self.rows[r["payment_id"] or r["invoice_id"]].append(r)
        self.rules = Rules(ep.public.policy)
        self.base = ep.public.policy["base_currency"]

    def invoices(self, d) -> list[dict]:
        return [self.inv[self.m[k]] for k in d.get("invoices", [])]

    def payments(self, d) -> list[dict]:
        return [self.pay[self.m[k]] for k in d.get("payments", [])]

    def ap(self, doc_id: str, side: str) -> int:
        return sum(r[side] for r in self.rows[doc_id] if r["account"] == self.rules.ap)


def _line_for(payment: dict, invoice_id: str) -> int:
    return sum(x["amount_minor"] for x in payment["invoice_refs"] or [] if x["invoice_id"] == invoice_id)


def _explained(kind: str, d: dict, v: _View) -> bool:
    inv, pay = v.invoices(d), v.payments(d)
    if kind in ("recurring_same_amount", "repeat_order_same_amount"):
        a, b = inv
        same = a["entity_id"] == b["entity_id"] and (a["currency"], a["total_minor"]) == (b["currency"], b["total_minor"])
        return same and a["vendor_ref"] != b["vendor_ref"] and (kind == "recurring_same_amount" or a["issued_at"] != b["issued_at"])
    if kind == "vendor_ref_collision":
        a, b = inv
        return a["vendor_ref"] == b["vendor_ref"] and a["entity_id"] != b["entity_id"]
    if kind == "reversed_duplicate":
        a, b = inv
        same_ref = (a["entity_id"], a["vendor_ref"]) == (b["entity_id"], b["vendor_ref"])
        reversed_ = [x for x in inv if v.ap(x["invoice_id"], "debit_minor") and
                     v.ap(x["invoice_id"], "debit_minor") == v.ap(x["invoice_id"], "credit_minor")]
        return same_ref and len(reversed_) == 1
    if kind == "split_payment":
        (i,), (p1, p2) = inv, pay
        return _line_for(p1, i["invoice_id"]) > 0 and _line_for(p2, i["invoice_id"]) > 0 and \
            _line_for(p1, i["invoice_id"]) + _line_for(p2, i["invoice_id"]) <= i["total_minor"]
    if kind == "partial_payment":
        (i,), (p,) = inv, pay
        applied = sum(r["debit_minor"] for r in v.rows[p["payment_id"]] if r["account"] == v.rules.ap and r["invoice_id"] == i["invoice_id"])
        return 0 < _line_for(p, i["invoice_id"]) < i["total_minor"] and applied > 0
    if kind == "batch_payment":
        (p,) = pay
        ids = {x["invoice_id"] for x in p["invoice_refs"] or []}
        return len(ids) >= 2 and {i["invoice_id"] for i in inv} <= ids and \
            all((i["entity_id"], i["currency"]) == (p["entity_id"], p["currency"]) for i in inv)
    if kind == "unidentified_payment":
        (p,) = pay
        susp = sum(r["debit_minor"] for r in v.rows[p["payment_id"]] if r["account"] == v.rules.suspense)
        return p["invoice_refs"] is None and susp > 0
    if kind == "correct_refund":
        original, refund = pay
        return (refund["direction"], refund["refund_of"], original["invoice_refs"]) == ("inbound", original["payment_id"], None) and \
            (refund["entity_id"], refund["currency"], refund["amount_minor"]) == (original["entity_id"], original["currency"], original["amount_minor"])
    if kind == "boundary_utc_date":
        (i,) = inv
        local = v.rules.accounting_date(i["issued_at"])
        utc = datetime.fromisoformat(i["issued_at"]).astimezone(timezone.utc).date()
        return v.rules.in_period(local) and not v.rules.in_period(utc) and i["currency"] != v.base
    raise AssertionError(f"unknown red-herring kind {kind}")


def test_every_red_herring_kind_occurs_and_has_a_valid_accounting_explanation(clean_episodes):
    seen: Counter = Counter()
    for ep in clean_episodes:
        v = _View(ep)
        for d in ep.sealed.provenance["distractors"]:
            assert _explained(d["kind"], d, v), f"{ep.public.episode_id}: {d['kind']} {d.get('note')}"
            seen[d["kind"]] += 1
    assert set(KINDS) <= set(seen) and min(seen[k] for k in KINDS) >= 3, seen


def test_the_independent_auditor_reports_nothing_on_clean_books_full_of_red_herrings(clean_episodes):
    for ep in clean_episodes:
        report = reconcile(PublicDataset.from_tables(ep.public.manifest, ep.public.policy, ep.public.tables))
        assert report.findings == [] and report.anomalies == [], ep.public.episode_id
        assert verify_generated(ep).ok


@pytest.mark.parametrize("seed,cfg", MIXED)
def test_real_errors_among_red_herrings_are_found_exactly(seed, cfg):
    ep = generate_episode(seed, cfg)
    assert verify_generated(ep).ok                      # exactly the declared issues, nothing else
    prov, m = ep.sealed.provenance, ep.sealed.provenance["id_map"]
    subjects = {m[i["details"][k]] for i in prov["injections"] for k in ("original", "copy", "invoice", "payment")
                if i["details"].get(k)}
    report = reconcile(PublicDataset.from_tables(ep.public.manifest, ep.public.policy, ep.public.tables))
    named = {a for f in report.findings for a in f.affected_ids}
    for d in prov["distractors"]:
        docs = {m[k] for k in d.get("invoices", []) + d.get("payments", [])}
        if d["kind"] in PROTECTED_RED_HERRINGS:
            assert not docs & named, f"{d['kind']} reported"
        assert not (docs - subjects) & named, f"{d['kind']}: a legitimate document was reported"


def _submitted(policy, seed: int, cfg: dict) -> list[dict]:
    logger = TrajectoryLogger()
    run_episode(OphanimEnv(mode="train"), policy, seed, cfg, logger)
    import json
    last = json.loads(logger.lines[-1])["action"]
    return last["findings"]["findings"] if last and last.get("action") == "submit" else []


def test_red_herrings_fool_the_naive_baseline_but_not_the_reference_auditor(clean_episodes):
    fooled: Counter = Counter()
    for (seed, cfg), ep in zip(CLEAN, clean_episodes):
        m = ep.sealed.provenance["id_map"]
        kind_of = {m[k]: d["kind"] for d in ep.sealed.provenance["distractors"] for k in d.get("invoices", []) + d.get("payments", [])}
        assert _submitted(ReferenceAuditor(), seed, cfg) == []
        for f in _submitted(SimpleReconciliation(), seed, cfg):
            for a in f["affected_ids"]:
                if a in kind_of:
                    fooled[kind_of[a]] += 1
    assert sum(fooled.values()) > 0 and len(fooled) >= 3, fooled
