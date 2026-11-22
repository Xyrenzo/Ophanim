"""Phase 2 compliance through the official jury adapter: exact lookups (C11/C12), published matcher
examples M01-M12, structural versus semantic errors, evidence universe and tolerance on episode files."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from ophanim.adapter import generate_episode, load_public_episode, load_sealed_episode, make_env, score_episode
from ophanim.evaluator.judge import Judge
from ophanim.evaluator.oracle import oracle_submission

NULLS = {"tp": None, "fp": None, "fn": None, "precision": None, "recall": None, "f1": None, "return": -1.0}


@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("p2") / "ep"
    generate_episode(31337, {"errors": {"duplicate_invoice": 1, "payment_allocation": 1, "fx_rate": 1,
                                        "period_attribution": 1}}, str(d))
    return d


def _closed(d):
    env = make_env()
    obs, _ = env.reset(seed=1, options={"mode": "closed", "episode_dir": str(d), "team_config": {}})
    return env, obs


# ----------------------------------------------------------------------------- C11 / C12 exact lookups
def test_c11_c12_variants_of_real_ids_are_unknown(generated):
    env, _ = _closed(generated)
    public = load_public_episode(generated)
    row, inv = public.tables["ledger"][0], public.tables["invoices"][0]
    real = [("get_record", {"table": "ledger", "id": row["row_id"]}),
            ("get_record", {"table": "invoices", "id": inv["invoice_id"]}),
            ("get_document", {"doc_id": inv["doc_id"]})]
    for name, args in real:
        o, *_ = env.step({"name": name, "args": args})
        assert o["error"] is None                                           # exact id resolves
    steps = 3
    for name, args in real:
        key = "doc_id" if name == "get_document" else "id"
        for variant in (args[key].lower(), " " + args[key], args[key] + " ", args[key] + "\n"):
            o, r, term, trunc, _ = env.step({"name": name, "args": dict(args, **{key: variant})})
            steps += 1
            assert o["result"] is None and o["error"]["code"] in ("unknown_id", "unknown_document")
            assert o["remaining_steps"] == 100 - steps and r == 0.0 and not term and not trunc
            assert variant.strip() not in json.dumps(o)                     # nothing echoed or disclosed


def test_numeric_ids_are_not_converted(generated):
    env, _ = _closed(generated)
    o, *_ = env.step({"name": "get_record", "args": {"table": "ledger", "id": 12345}})
    assert o["result"] is None and o["error"] is not None and o["remaining_steps"] == 99


# ----------------------------------------------------------------------------- M01-M12 on an episode directory
@pytest.fixture()
def mfix(generated, tmp_path) -> dict:
    """Published example fixture: A = {R1, R2}, 10000 KZT, evidence {D1, D2}, D3 existing extra, U absent."""
    d = tmp_path / "m"
    shutil.copytree(generated, d)
    public = load_public_episode(d)
    inv = public.tables["invoices"]
    fx = {"dir": d, "eid": public.episode_id, "R": [i["invoice_id"] for i in inv[:3]],
          "D": [i["doc_id"] for i in inv[:3]], "U": "U-NOT-IN-THE-DATA"}
    return fx


def _truth(fx, issues, tau=0):
    t = {"schema_version": "1.0", "episode_id": fx["eid"], "base_currency": "KZT", "tolerance_minor": tau, "issues": issues}
    (fx["dir"] / "evaluator" / "truth.json").write_text(json.dumps(t), encoding="utf-8")


def _A(fx, iid="A", ev=None):
    R, D = fx["R"], fx["D"]
    return {"issue_id": iid, "type": "duplicate_invoice", "affected_ids": [R[0], R[1]], "expected_amount_minor": 10000,
            "currency": "KZT", "allowed_evidence_sets": [ev or [D[0], D[1]]]}


def _F(fx, **over):
    R, D = fx["R"], fx["D"]
    f = {"type": "duplicate_invoice", "affected_ids": [R[0], R[1]], "claimed_amount_minor": 10000, "currency": "KZT",
         "evidence_ids": [D[0], D[1]], "explanation": "short"}
    f.update(over)
    return f


def _score(fx, findings, steps=10):
    return score_episode(str(fx["dir"]), {"episode_id": fx["eid"], "findings": findings}, steps)


def _tff(s):
    return (s["tp"], s["fp"], s["fn"])


def test_published_examples_m01_to_m09_and_m12(mfix):
    fx = mfix
    R, D, U = fx["R"], fx["D"], fx["U"]
    _truth(fx, [_A(fx)])
    assert _tff(_score(fx, [_F(fx, affected_ids=[R[1], R[0], R[0]])])) == (1, 0, 0)        # M01
    assert _tff(_score(fx, [_F(fx, affected_ids=[R[0], R[1], R[2]])])) == (0, 1, 1)        # M02
    assert _tff(_score(fx, [_F(fx, evidence_ids=[D[1], D[0], D[2]])])) == (1, 0, 0)        # M03
    assert _tff(_score(fx, [_F(fx, evidence_ids=[D[0], D[1], U])])) == (0, 1, 1)           # M04
    assert _score(fx, [_F(fx, evidence_ids=[D[0]] * 10 + [D[1]])]) == NULLS                # M05
    assert _tff(_score(fx, [_F(fx, currency="kzt")])) == (0, 1, 1)                         # M06 case
    assert _tff(_score(fx, [_F(fx, currency=" KZT")])) == (0, 1, 1)                        # M06 space
    assert _tff(_score(fx, [_F(fx, claimed_amount_minor=10001)])) == (0, 1, 1)             # M07 (tau 0)
    assert _score(fx, [_F(fx, claimed_amount_minor="10000")]) == NULLS                     # M09 string
    assert _score(fx, [_F(fx, claimed_amount_minor=True)]) == NULLS                        # M09 bool
    s = _score(fx, [_F(fx), _F(fx)])                                                       # M12
    assert _tff(s) == (1, 1, 0) and abs(s["return"] - 47 / 150) < 1e-9
    _truth(fx, [_A(fx)], tau=1)
    assert _tff(_score(fx, [_F(fx, claimed_amount_minor=10001)])) == (1, 0, 0)             # M08 inclusive
    assert _tff(_score(fx, [_F(fx, claimed_amount_minor=10002)])) == (0, 1, 1)             # M08


def _pairs(fx, findings):
    public = load_public_episode(fx["dir"])
    judge = Judge(sealed=load_sealed_episode(fx["dir"], public))
    out = judge.submit({"episode_id": fx["eid"], "findings": findings}, 10)
    return out, dict(out.match.pairs)


def test_published_examples_m10_m11_through_the_episode_files(mfix):
    fx = mfix
    D = fx["D"]
    _truth(fx, [_A(fx, "A", [D[0]]), _A(fx, "B", [D[1]])])
    out, pairs = _pairs(fx, [_F(fx, evidence_ids=[D[0], D[1]]), _F(fx, evidence_ids=[D[0]])])   # M10
    assert (out.tp, out.fp, out.fn) == (2, 0, 0) and pairs == {1: "A", 0: "B"}
    _truth(fx, [_A(fx, "A", [D[0]]), _A(fx, "B", [D[0]])])
    out, pairs = _pairs(fx, [_F(fx, evidence_ids=[D[0]]), _F(fx, evidence_ids=[D[0]])])         # M11
    assert (out.tp, out.fp, out.fn) == (2, 0, 0) and pairs == {0: "A", 1: "B"}


# ----------------------------------------------------------------------------- structure vs semantics
@pytest.mark.parametrize("over", [
    {"type": "fraud"}, {"type": "Duplicate_Invoice"}, {"currency": "KZT "}, {"claimed_amount_minor": -10000},
    {"affected_ids": []}, {"affected_ids": ["x" * 300]}, {"evidence_ids": []},
], ids=["unknown_type", "type_case", "currency_space", "negative_amount", "empty_affected", "long_id", "no_evidence"])
def test_semantic_mismatch_counts_as_fp_fn(mfix, over):
    _truth(mfix, [_A(mfix)])
    s = _score(mfix, [_F(mfix, **over)])
    assert _tff(s) == (0, 1, 1) and s["return"] == -1.0 and s["precision"] == 0.0      # normal accounting


@pytest.mark.parametrize("over", [
    {"claimed_amount_minor": 10000.0}, {"claimed_amount_minor": None}, {"affected_ids": [1]}, {"currency": 398},
    {"explanation": "ж" * 1001}, {"evidence_ids": [f"E{i}" for i in range(11)]}, {"note": "extra field"},
], ids=["float_amount", "null_amount", "numeric_id", "numeric_currency", "long_explanation", "11_evidence", "extra_field"])
def test_structure_errors_return_minus_one_and_nulls(mfix, over):
    _truth(mfix, [_A(mfix)])
    assert _score(mfix, [_F(mfix, **over)]) == NULLS


def test_limits_accept_the_boundary_values(mfix):
    _truth(mfix, [_A(mfix)])
    many = [_F(mfix)] + [_F(mfix, affected_ids=[f"X{i}"]) for i in range(29)]
    s = _score(mfix, many)                                                                    # 30 findings
    assert _tff(s) == (1, 29, 0)
    s = _score(mfix, [_F(mfix, explanation="𝄞" * 1000, evidence_ids=mfix["D"][:2] + mfix["D"][:2] * 4)])
    assert _tff(s) == (1, 0, 0)                                                               # 1000 code points, 10 ids


# ----------------------------------------------------------------------------- evidence universe
def test_tool_accessible_ids_are_valid_extra_evidence_entity_ids_are_not(mfix):
    _truth(mfix, [_A(mfix)])
    public = load_public_episode(mfix["dir"])
    inv, pay = public.tables["invoices"][5], public.tables["payments"][0]
    base = _F(mfix)["evidence_ids"]
    assert _tff(_score(mfix, [_F(mfix, evidence_ids=base + [inv["invoice_id"], pay["payment_id"]])])) == (1, 0, 0)
    assert _tff(_score(mfix, [_F(mfix, evidence_ids=base + [inv["entity_id"]])])) == (0, 1, 1)


# ----------------------------------------------------------------------------- tolerance on files
def test_generated_episodes_use_exact_amounts_by_default(generated):
    truth = json.loads((generated / "evaluator" / "truth.json").read_text(encoding="utf-8"))
    policy = json.loads((generated / "public" / "policy.json").read_text(encoding="utf-8"))
    assert truth["tolerance_minor"] == 0 and policy["tolerance_minor"] == 0
    public = load_public_episode(generated)
    sub = oracle_submission(load_sealed_episode(generated, public))
    assert score_episode(str(generated), sub, 0)["return"] == 1.0
    off = dict(sub, findings=[dict(f, claimed_amount_minor=f["claimed_amount_minor"] + 1) for f in sub["findings"]])
    assert _tff(score_episode(str(generated), off, 0)) == (0, 4, 4)            # Block-3 test 8 with the default


def test_truth_file_without_tolerance_defaults_to_zero_and_invalid_tolerance_is_rejected(mfix):
    t = {"schema_version": "1.0", "episode_id": mfix["eid"], "base_currency": "KZT", "issues": [_A(mfix)]}
    path = mfix["dir"] / "evaluator" / "truth.json"
    path.write_text(json.dumps(t), encoding="utf-8")
    assert _tff(_score(mfix, [_F(mfix, claimed_amount_minor=10001)])) == (0, 1, 1)
    for bad in (-1, True, "0", 0.5):
        path.write_text(json.dumps(dict(t, tolerance_minor=bad)), encoding="utf-8")
        with pytest.raises(ValidationError):
            _score(mfix, [_F(mfix)])
