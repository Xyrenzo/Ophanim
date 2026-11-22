"""Phase 3 generator compliance (official D-matrix): D03 correct refund, D09-D11 missing/partial allocation,
D02 legitimate split payment, D05 FX/period boundary, provenance format."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from ophanim.adapter import generate_episode as adapter_generate
from ophanim.adapter import load_public_episode, load_sealed_episode, make_env, score_episode
from ophanim.audit.dataset import PublicDataset
from ophanim.audit.reconcile import reconcile
from ophanim.audit.rules import Rules
from ophanim.evaluator.oracle import oracle_submission
from ophanim.evaluator.verifier import verify_generated
from ophanim.generator import generate_episode
from ophanim.generator.history import HistoryBuilder
from ophanim.generator.model import GenerationError
from ophanim.generator.posting import post_world, validate_world
from ophanim.rng import DeterministicRng
from ophanim.schemas import EpisodeConfig

SEEDS = range(8)


def _ds(ep, tables=None):
    return PublicDataset.from_tables(ep.public.manifest, ep.public.policy, tables or ep.public.tables)


def _rate(ep, day, currency):
    if currency == ep.public.manifest["base_currency"]:
        return Decimal(1)
    for r in ep.public.tables["fx"]:
        if r["date"] == day.isoformat() and r["source_currency"] == currency:
            return Decimal(r["rate"])
    raise AssertionError("missing FX rate")


def _closed_env(tmp_path, seed, config):
    d = tmp_path / f"ep-{seed}"
    adapter_generate(seed, config, str(d))
    env = make_env()
    obs, _ = env.reset(seed=seed, options={"mode": "closed", "episode_dir": str(d), "team_config": {}})
    return d, env, obs


def _fetch_evidence(env, ev_id):
    """Retrieve one evidence id with the official tools (the agent's view)."""
    if ev_id.count(":") == 2:
        o, *_ = env.step({"name": "get_record", "args": {"table": "fx", "id": ev_id}})
    elif ev_id.startswith("DOC-"):
        o, *_ = env.step({"name": "get_document", "args": {"doc_id": ev_id}})
    else:
        o, *_ = env.step({"name": "get_record", "args": {"table": "ledger", "id": ev_id}})
    assert o["error"] is None, (ev_id, o["error"])
    return o["result"]


# ============================================================================= D03 correct refund
def _refund_pair(ep):
    pays = {p["payment_id"]: p for p in ep.public.tables["payments"]}
    refunds = [p for p in pays.values() if p["direction"] == "inbound"]
    assert len(refunds) == 1
    return refunds[0], pays[refunds[0]["refund_of"]]


@pytest.mark.parametrize("seed", SEEDS)
def test_d03_clean_episode_contains_one_correct_refund(seed):
    ep = generate_episode(seed, {})                                   # clean, distractors "normal"
    assert ep.sealed.truth.issues == []
    refund, original = _refund_pair(ep)
    rules = Rules(ep.public.policy)
    # record relationships, amount, currency, dates
    assert original["direction"] == "outbound" and original["refund_of"] is None and original["invoice_refs"] is None
    assert refund["invoice_refs"] is None
    assert (refund["entity_id"], refund["currency"], refund["amount_minor"]) == \
           (original["entity_id"], original["currency"], original["amount_minor"])
    t_orig, t_ref = datetime.fromisoformat(original["timestamp"]), datetime.fromisoformat(refund["timestamp"])
    assert t_orig < t_ref and rules.in_period(rules.accounting_date(original["timestamp"])) \
        and rules.in_period(rules.accounting_date(refund["timestamp"]))
    # ledger: Dr Bank at the refund's rate, Cr Suspense = what the original parked, FX difference, balanced
    rows = [r for r in ep.public.tables["ledger"] if r["payment_id"] == refund["payment_id"]]
    orig_rows = [r for r in ep.public.tables["ledger"] if r["payment_id"] == original["payment_id"]]
    bank = [r for r in rows if r["account"] == rules.bank]
    susp = [r for r in rows if r["account"] == rules.suspense]
    parked = sum(r["debit_minor"] for r in orig_rows if r["account"] == rules.suspense)
    expected_bank = rules.convert(refund["amount_minor"], refund["currency"],
                                  _rate(ep, rules.accounting_date(refund["timestamp"]), refund["currency"]))
    assert len(bank) == 1 and bank[0]["debit_minor"] == expected_bank and bank[0]["credit_minor"] == 0
    assert len(susp) == 1 and susp[0]["credit_minor"] == parked > 0
    assert sum(r["debit_minor"] for r in rows) == sum(r["credit_minor"] for r in rows)
    fx_rows = [r for r in rows if r["account"] == rules.fx_account]
    assert (len(fx_rows) == 1) == (expected_bank != parked)
    # evaluator side: a correct refund is not an issue; the independent auditor agrees
    rep = reconcile(_ds(ep))
    assert rep.findings == [] and rep.anomalies == []
    assert verify_generated(ep).ok
    prov = ep.sealed.provenance
    labelled = [d for d in prov["distractors"] if d["kind"] == "correct_refund"]
    assert len(labelled) == 1
    assert [prov["id_map"][k] for k in labelled[0]["payments"]] == [original["payment_id"], refund["payment_id"]]


def test_d03_refunds_in_foreign_currency_use_the_refund_date_rate():
    seen_foreign = False
    for seed in range(40):
        ep = generate_episode(seed, {})
        refund, _ = _refund_pair(ep)
        if refund["currency"] != ep.public.manifest["base_currency"]:
            seen_foreign = True
            assert verify_generated(ep).ok
    assert seen_foreign


def test_d03_refund_is_reachable_through_the_tools_and_scores_clean(tmp_path):
    d, env, obs = _closed_env(tmp_path, 3, {})
    public = load_public_episode(d)
    refund = next(p for p in public.tables["payments"] if p["direction"] == "inbound")
    assert env.step({"name": "get_document", "args": {"doc_id": refund["doc_id"]}})[0]["result"] == refund
    original = env.step({"name": "get_record", "args": {"table": "payments", "id": refund["refund_of"]}})[0]["result"]
    assert original["payment_id"] == refund["refund_of"] and original["direction"] == "outbound"
    rows = [r for r in public.tables["ledger"] if r["payment_id"] == refund["payment_id"]]
    for r in rows:
        assert env.step({"name": "get_record", "args": {"table": "ledger", "id": r["row_id"]}})[0]["result"] == r
    score = score_episode(str(d), {"episode_id": obs["manifest"]["episode_id"], "findings": []}, 5)
    assert (score["tp"], score["fp"], score["fn"], score["f1"]) == (0, 0, 0, 1.0)


@pytest.mark.parametrize("tamper", ["suspense_amount", "refund_of_unknown", "amount_mismatch", "earlier_than_original"])
def test_d03_auditor_rejects_an_inconsistent_refund(tamper):
    """Negative control: the refund checks are real, not vacuous."""
    ep = generate_episode(2, {})
    tables = copy.deepcopy(ep.public.tables)
    refund = next(p for p in tables["payments"] if p["direction"] == "inbound")
    if tamper == "suspense_amount":
        row = next(r for r in tables["ledger"] if r["payment_id"] == refund["payment_id"] and r["credit_minor"]
                   and r["account"] == "2090")
        row["credit_minor"] += 1
        bank = next(r for r in tables["ledger"] if r["payment_id"] == refund["payment_id"] and r["account"] == "1000")
        bank["debit_minor"] += 1                                         # keep the posting balanced
    elif tamper == "refund_of_unknown":
        refund["refund_of"] = "PAY-NOTHERE"
    elif tamper == "amount_mismatch":
        refund["amount_minor"] += 100
    else:
        refund["timestamp"] = "2000-01-01T00:00:00+00:00"
    rep = reconcile(_ds(ep, tables))
    assert rep.anomalies or rep.findings


def test_d03_no_refund_at_low_distractor_level_and_refunds_never_receive_errors():
    assert not any(p["direction"] == "inbound" for p in generate_episode(4, {"distractors": "low"}).public.tables["payments"])
    for seed in range(15):
        ep = generate_episode(seed, {"errors": {"fx_rate": 4, "period_attribution": 2}})
        prov = ep.sealed.provenance
        protected = {k for d in prov["distractors"] if d["kind"] == "correct_refund" for k in d["payments"]}
        for inj in prov["injections"]:
            assert not ({inj["details"].get("payment"), inj["details"].get("invoice")} & protected)
        assert verify_generated(ep).ok


def test_d03_deterministic():
    a, b = generate_episode(11, {}), generate_episode(11, {})
    assert a.public.tables == b.public.tables and a.sealed.provenance == b.sealed.provenance


# ============================================================================= D09-D11 allocation modes
def _allocation_issue_facts(ep):
    """Per allocation issue: (lines on the payment, applied amount, unapplied amount, payment amount)."""
    pays = {p["payment_id"]: p for p in ep.public.tables["payments"]}
    invs = {i["invoice_id"]: i for i in ep.public.tables["invoices"]}
    out = []
    for t in ep.sealed.truth.issues:
        if t.type != "payment_allocation":
            continue
        pid = next(x for x in t.affected_ids if x in pays)
        iid = next(x for x in t.affected_ids if x in invs)
        pay = pays[pid]
        line = next(l for l in pay["invoice_refs"] if l["invoice_id"] == iid)
        applied_rows = [r for r in ep.public.tables["ledger"] if r["payment_id"] == pid and r["account"] == "2000"]
        applied_doc = pay["amount_minor"] - line["amount_minor"]              # payment currency, minor units
        out.append((len(pay["invoice_refs"]), applied_doc, line["amount_minor"], pay["amount_minor"], applied_rows, t))
    return out


@pytest.mark.parametrize("seed", SEEDS)
def test_d09_missing_mode_produces_genuinely_missing_allocations(seed):
    ep = generate_episode(seed, {"errors": {"payment_allocation": 2}, "allocation_mode": "missing"})
    facts = _allocation_issue_facts(ep)
    assert len(facts) == 2
    for n_lines, applied, unapplied, amount, ap_rows, _ in facts:
        assert n_lines == 1 and applied == 0 and unapplied == amount > 0 and ap_rows == []
    assert all(i["details"]["allocation_kind"] == "missing" for i in ep.sealed.provenance["injections"])
    assert verify_generated(ep).ok


@pytest.mark.parametrize("seed", SEEDS)
def test_d10_partial_mode_produces_strictly_partial_allocations(seed):
    ep = generate_episode(seed, {"errors": {"payment_allocation": 3}, "allocation_mode": "partial"})
    facts = _allocation_issue_facts(ep)
    assert len(facts) == 3
    for n_lines, applied, unapplied, amount, ap_rows, _ in facts:
        assert n_lines == 2
        assert 0 < applied < amount and 0 < unapplied < amount and applied + unapplied == amount   # exact minor units
        assert len(ap_rows) == 1 and ap_rows[0]["debit_minor"] > 0          # the other line is applied in the ledger
    assert all(i["details"]["allocation_kind"] == "partial" for i in ep.sealed.provenance["injections"])
    assert verify_generated(ep).ok


def test_d09_d11_three_episodes_with_both_kinds_pass_end_to_end(tmp_path):
    """Mirror of the official D09-D11 block: three allocation episodes incl. >= 1 missing and >= 1 partial."""
    for seed, mode in ((901, "missing"), (902, "partial"), (903, "partial")):
        d, env, obs = _closed_env(tmp_path, seed, {"errors": {"payment_allocation": 1}, "allocation_mode": mode})
        sealed = load_sealed_episode(d, load_public_episode(d))
        (issue,) = sealed.truth.issues
        for ev_id in issue.allowed_evidence_sets[0]:                      # complete evidence via the tools
            _fetch_evidence(env, ev_id)
        sub = oracle_submission(sealed)
        o, r, term, *_ = env.step({"name": "submit", "args": {"findings": sub}})
        assert term and r == 0.0 and o["result"] == {"accepted": True}
        score = score_episode(str(d), sub, env.inspection_steps)
        assert (score["tp"], score["fp"], score["fn"]) == (1, 0, 0)
        assert abs(score["return"] - (1 - 0.002 * env.inspection_steps)) < 1e-9


def test_allocation_modes_are_deterministic_and_distinct():
    m1 = generate_episode(5, {"errors": {"payment_allocation": 1}, "allocation_mode": "missing"})
    m2 = generate_episode(5, {"errors": {"payment_allocation": 1}, "allocation_mode": "missing"})
    p1 = generate_episode(5, {"errors": {"payment_allocation": 1}, "allocation_mode": "partial"})
    assert m1.public.tables == m2.public.tables and m1.sealed.truth == m2.sealed.truth
    assert _allocation_issue_facts(m1)[0][0] == 1 and _allocation_issue_facts(p1)[0][0] == 2


@pytest.mark.parametrize("bad", ["partially", "", "MISSING", None, 1, True])
def test_invalid_allocation_mode_is_rejected(bad):
    with pytest.raises(ValidationError):
        EpisodeConfig.model_validate({"errors": {"payment_allocation": 1}, "allocation_mode": bad})


def test_explicit_mode_never_falls_back():
    from ophanim.generator.injectors import ErrorInjector

    cfg = EpisodeConfig.model_validate({})
    world = HistoryBuilder(DeterministicRng.from_seed(7).child("content"), cfg).build()
    post_world(world)
    inj = ErrorInjector(world, DeterministicRng.from_seed(7).child("errors"))
    single = next(p for p in world.payments.values() if p.refs and len(p.refs) == 1)
    with pytest.raises(GenerationError):
        inj.payment_allocation(DeterministicRng.from_seed(1), payment_key=single.key,
                               invoice_key=single.refs[0].invoice_key, required_kind="partial")


def test_auto_mode_is_unchanged_default():
    assert EpisodeConfig.model_validate({}).allocation_mode == "auto"
    assert verify_generated(generate_episode(6, {"errors": {"payment_allocation": 2}})).ok


# ============================================================================= D02 split payment
@pytest.mark.parametrize("cfg", [{}, {"size": "small"}, {"size": "large", "distractors": "high"}, {"profile": "consulting"}])
@pytest.mark.parametrize("seed", range(4))
def test_d02_clean_episode_has_a_legitimate_split_payment(seed, cfg):
    ep = generate_episode(seed, cfg)
    assert ep.sealed.truth.issues == []
    invs = {i["invoice_id"]: i for i in ep.public.tables["invoices"]}
    lines_by_invoice: dict[str, list[tuple[str, int]]] = {}
    for p in ep.public.tables["payments"]:
        for l in p["invoice_refs"] or []:
            lines_by_invoice.setdefault(l["invoice_id"], []).append((p["payment_id"], l["amount_minor"]))
    splits = [iid for iid, ls in lines_by_invoice.items()
              if len({pid for pid, _ in ls}) >= 2 and sum(a for _, a in ls) == invs[iid]["total_minor"]]
    assert splits, "expected at least one invoice fully settled by two or more payments"
    for iid in splits:
        for pid, _ in lines_by_invoice[iid]:                             # each part applied to that invoice's AP
            assert any(r["payment_id"] == pid and r["invoice_id"] == iid and r["account"] == "2000" and r["debit_minor"] > 0
                       for r in ep.public.tables["ledger"])
    rep = reconcile(_ds(ep))
    assert rep.findings == [] and rep.anomalies == []


def test_d02_guarantee_path_plants_a_valid_split_when_none_occurred():
    cfg = EpisodeConfig.model_validate({})
    builder = HistoryBuilder(DeterministicRng.from_seed(3).child("content"), cfg)
    world = builder.build()
    before = sum(1 for d in world.distractors if d["kind"] == "split_payment")
    world.distractors = [d for d in world.distractors if d["kind"] != "split_payment"]    # pretend none occurred
    builder._guarantee_split_payment(DeterministicRng.from_seed(99))
    planted = [d for d in world.distractors if d["kind"] == "split_payment"]
    assert before >= 1 and len(planted) == 1
    inv = world.invoices[planted[0]["invoices"][0]]
    parts = [world.payments[k] for k in planted[0]["payments"]]
    assert sum(p.amount_minor for p in parts) == inv.total_minor and all(p.amount_minor > 0 for p in parts)
    post_world(world)
    assert validate_world(world) == []


# ============================================================================= D05 FX / period boundary
@pytest.mark.parametrize("seed", SEEDS)
def test_d05_clean_foreign_boundary_document_is_correct_and_provable_with_tools(seed, tmp_path):
    d, env, obs = _closed_env(tmp_path, seed, {})
    public = load_public_episode(d)
    sealed = load_sealed_episode(d, public)
    rules = Rules(public.policy)
    prov = sealed.provenance
    label = next(x for x in prov["distractors"] if x["kind"] == "boundary_utc_date")
    inv_id = prov["id_map"][label["invoices"][0]]
    inv = env.step({"name": "get_record", "args": {"table": "invoices", "id": inv_id}})[0]["result"]
    base = public.manifest["base_currency"]
    assert inv["currency"] != base                                       # foreign: FX applies
    local = rules.accounting_date(inv["issued_at"])
    utc = datetime.fromisoformat(inv["issued_at"]).astimezone(timezone.utc).date()
    assert rules.in_period(local) and not rules.in_period(utc) and local != utc
    key = f"{local.isoformat()}:{inv['currency']}:{base}"                # policy: rate of the accounting date
    fx = env.step({"name": "get_record", "args": {"table": "fx", "id": key}})[0]["result"]
    assert fx["source_currency"] == inv["currency"] and fx["target_currency"] == base   # pair direction
    ap = next(r for r in public.tables["ledger"] if r["invoice_id"] == inv_id and r["payment_id"] is None
              and r["account"] == "2000" and r["credit_minor"] > 0)
    ap_seen = env.step({"name": "get_record", "args": {"table": "ledger", "id": ap["row_id"]}})[0]["result"]
    assert ap_seen["credit_minor"] == rules.convert(inv["total_minor"], inv["currency"], Decimal(fx["rate"]))
    utc_rate = next(r["rate"] for r in public.tables["fx"] if r["date"] == utc.isoformat() and r["source_currency"] == inv["currency"])
    assert ap_seen["credit_minor"] != rules.convert(inv["total_minor"], inv["currency"], Decimal(utc_rate))
    assert sealed.truth.issues == []
    score = score_episode(str(d), {"episode_id": obs["manifest"]["episode_id"], "findings": []}, 3)
    assert score["f1"] == 1.0 and score["fp"] == 0


# ============================================================================= provenance format
DOCUMENTED_KEYS = {"schema_version", "env_version", "episode_id", "generation", "company", "id_map", "distractors",
                   "scenario_carriers", "injections", "pre_mutation"}


def test_provenance_has_exactly_the_documented_top_level_keys():
    ep = generate_episode(1, {"errors": {"payment_allocation": 1}, "allocation_mode": "partial",
                              "scenarios": {"fx_partial_payment_boundary": 1}})
    prov = ep.sealed.provenance
    assert set(prov) == DOCUMENTED_KEYS
    assert set(prov["generation"]) == {"seed", "secret_used", "config"}
    assert set(prov["company"]) == {"profile", "base_currency", "offset_minutes", "period"}
    assert set(prov["pre_mutation"]) == {"validation_problems", "tables"}
    assert {c["scenario"] for c in prov["scenario_carriers"]} == {"fx_partial_payment_boundary", "allocation_partial"}
    for inj in prov["injections"]:
        assert set(inj) == {"issue_id", "type", "scenario", "cause", "details"}
        assert inj["issue_id"] in {t.issue_id for t in ep.sealed.truth.issues}
    json.dumps(prov)
    doc = (Path(__file__).resolve().parents[2] / "docs" / "provenance_format.md").read_text(encoding="utf-8")
    for key in DOCUMENTED_KEYS:
        assert f"`{key}`" in doc, key
