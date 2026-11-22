"""Ablation study: every ablation removes exactly what it claims to remove, and the study is reproducible."""

from __future__ import annotations

import json

import pytest

from ophanim.evaluator.ablation import POLICIES, render_markdown, run_ablation
from ophanim.policies import ABLATION_POLICIES, AGENT_POLICIES, POLICY_KINDS, make_policy
from ophanim.schemas import ERROR_TYPES

MINI = {"suite_version": "1.0", "name": "ablation-mini", "episodes": [
    {"id": "clean", "category": "clean", "seed": 7101, "config": {"distractors": "normal"}},
    {"id": "dup-alloc", "category": "single_type", "seed": 7102,
     "config": {"errors": {"duplicate_invoice": 1, "payment_allocation": 1}, "allocation_mode": "partial"}},
    {"id": "fx-period", "category": "single_type", "seed": 7103,
     "config": {"errors": {"fx_rate": 1, "period_attribution": 1}, "distractors": "high"}},
    {"id": "s1", "category": "interacting", "seed": 7104, "config": {"scenarios": {"fx_partial_payment_boundary": 1}}},
]}


@pytest.fixture(scope="module")
def study(tmp_path_factory):
    d = tmp_path_factory.mktemp("ablation")
    (d / "suite.json").write_text(json.dumps(MINI), encoding="utf-8")
    return run_ablation(d / "suite.json", d / "out"), d


def _strip(r: dict) -> dict:
    return {k: v for k, v in r.items() if k != "duration_seconds"}


def test_reference_auditor_and_oracle_are_exact(study):
    r, _ = study
    assert r["data_problems"] == []
    for name in ("reference_auditor", "oracle"):
        o = r["policies"][name]["overall"]
        assert o["fp"] == o["fn"] == 0 and o["tp"] == sum(r["issues_by_type"].values())
    assert "evaluator-only" in r["policies"]["oracle"]["kind"]


@pytest.mark.parametrize("name,dropped", [("ablation_no_duplicate_check", "duplicate_invoice"),
                                          ("ablation_no_allocation_check", "payment_allocation"),
                                          ("ablation_no_fx_check", "fx_rate"),
                                          ("ablation_no_period_check", "period_attribution")])
def test_switching_off_one_check_loses_exactly_that_error_type(study, name, dropped):
    r, _ = study
    ref, abl = r["policies"]["reference_auditor"], r["policies"][name]
    for t in ERROR_TYPES:
        if t == dropped:
            assert (abl["per_type"][t]["tp"], abl["per_type"][t]["fp"], abl["per_type"][t]["fn"]) == (0, 0, r["issues_by_type"][t])
        else:
            assert abl["per_type"][t] == ref["per_type"][t]
    assert abl["overall"]["mean_inspection_steps"] == ref["overall"]["mean_inspection_steps"]   # same acquisition


def test_without_ledger_evidence_no_finding_is_credited(study):
    r, _ = study
    o = r["policies"]["ablation_documents_only_evidence"]["overall"]
    total = sum(r["issues_by_type"].values())
    assert o["tp"] == 0 and o["fp"] == total and o["fn"] == total


def test_without_company_time_zone_reasoning_legitimate_documents_are_accused(study):
    r, _ = study
    s = r["policies"]["ablation_utc_dates"]
    assert s["clean_episodes"]["false_positives"] > 0 and s["red_herring_false_positives"]["total"] > 0
    assert s["overall"]["precision"] < 1.0
    assert r["policies"]["reference_auditor"]["red_herring_false_positives"]["total"] == 0


def test_study_is_reproducible_and_writes_its_report(study):
    r, d = study
    again = run_ablation(d / "suite.json")
    assert _strip(again) == _strip(r)
    assert json.loads((d / "out" / "report.json").read_text(encoding="utf-8"))["episodes"] == 4
    md = (d / "out" / "report.md").read_text(encoding="utf-8")
    assert md == render_markdown(r) and "Learned models: none" in md


def test_policy_kinds_are_explicit_and_no_policy_is_called_a_model():
    assert set(POLICIES) == set(POLICY_KINDS) | {"oracle"}
    assert set(ABLATION_POLICIES).isdisjoint(AGENT_POLICIES)          # official registry unchanged
    assert {POLICY_KINDS[n] for n in ABLATION_POLICIES} == {"scripted ablation"}
    assert not any("model" in k or "learned" in k for k in POLICY_KINDS.values())
    for name in ABLATION_POLICIES:
        assert make_policy(name).name == name
