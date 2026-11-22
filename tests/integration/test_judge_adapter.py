"""Official jury adapter (judge_adapter.py / ophanim.adapter): entry points, closed loading,
action envelope, observation contract, step boundaries, scoring on published fixtures, isolation."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from fractions import Fraction
from pathlib import Path

import pytest

import judge_adapter
from ophanim import adapter
from ophanim.adapter import generate_episode, load_public_episode, load_sealed_episode, make_env, score_episode
from ophanim.evaluator.oracle import oracle_submission
from ophanim.evaluator.verifier import verify_directory

DIRTY = {"errors": {"duplicate_invoice": 1, "payment_allocation": 1, "fx_rate": 1, "period_attribution": 1}}
PUBLIC_FILES = ("manifest.json", "policy.json", "ledger.csv", "invoices.jsonl", "payments.jsonl", "fx.csv")
EVALUATOR_FILES = ("truth.json", "provenance.json")


def _hashes(directory: Path) -> dict[str, str]:
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def episode_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("ep") / "episode"
    generate_episode(4242, DIRTY, str(d))
    return d


def closed(env, d, seed=1):
    return env.reset(seed=seed, options={"mode": "closed", "episode_dir": str(d), "team_config": {}})


def act(name, **args):
    return {"name": name, "args": args}


# ----------------------------------------------------------------------------- entry points
def test_root_module_exposes_the_three_entry_points():
    assert judge_adapter.generate_episode is generate_episode
    assert judge_adapter.make_env is make_env
    assert judge_adapter.score_episode is score_episode


def test_generate_episode_writes_all_required_files(episode_dir):
    for f in PUBLIC_FILES:
        assert (episode_dir / "public" / f).is_file(), f
    for f in EVALUATOR_FILES:
        assert (episode_dir / "evaluator" / f).is_file(), f
    rep = verify_directory(episode_dir)          # every reference resolves; truth independently verified
    assert rep.ok, rep.problems[:3]
    assert rep.issues_declared == 4


def test_generate_episode_is_deterministic_and_accepts_both_config_forms(tmp_path):
    generate_episode(77, DIRTY, str(tmp_path / "a"))
    generate_episode(77, DIRTY, str(tmp_path / "b"))
    generate_episode(77, {"team_config": DIRTY}, str(tmp_path / "c"))
    assert _hashes(tmp_path / "a") == _hashes(tmp_path / "b") == _hashes(tmp_path / "c")
    generate_episode(78, DIRTY, str(tmp_path / "d"))
    assert _hashes(tmp_path / "a") != _hashes(tmp_path / "d")


def test_generate_episode_rejects_bad_arguments(tmp_path):
    with pytest.raises(TypeError):
        generate_episode("7", {}, str(tmp_path))
    with pytest.raises(Exception):
        generate_episode(7, {"errors": {"duplicate_invoice": "1"}}, str(tmp_path))


# ----------------------------------------------------------------------------- modes and loading
def test_train_mode_generates_from_seed_and_team_config():
    env = make_env()
    obs, info = env.reset(seed=5, options={"mode": "train", "team_config": DIRTY})
    assert info["mode"] == "train"
    eid = obs["manifest"]["episode_id"]
    o, r, term, trunc, _ = env.step(act("submit", findings={"episode_id": eid, "findings": []}))
    assert term and not trunc and r == -1.0           # train mode: terminal reward visible (empty answer, 4 issues)


def test_train_mode_with_episode_dir_returns_terminal_reward(episode_dir):
    env = make_env()
    env.reset(seed=1, options={"mode": "train", "episode_dir": str(episode_dir)})
    sub = oracle_submission(load_sealed_episode(episode_dir, load_public_episode(episode_dir)))
    _, r, term, _, _ = env.step(act("submit", findings=sub))
    assert term and r == 1.0


def test_closed_mode_loads_the_exact_episode(episode_dir):
    env = make_env()
    obs, info = closed(env, episode_dir)
    manifest = json.loads((episode_dir / "public" / "manifest.json").read_text(encoding="utf-8"))
    assert obs["manifest"] == manifest and info["mode"] == "closed"
    public = load_public_episode(episode_dir)
    for table in ("ledger", "invoices", "payments", "fx"):
        served, cursor = [], None
        while True:
            o, *_ = env.step(act("list_records", table=table, cursor=cursor, limit=50))
            served += o["result"]["records"]
            cursor = o["result"]["next_cursor"]
            if cursor is None:
                break
        assert served == public.tables[table], table   # same ids, same order, same values


def test_closed_mode_never_regenerates_or_mutates(episode_dir, monkeypatch):
    import ophanim.env.environment as envmod
    import ophanim.generator.episode as genmod

    def forbidden(*a, **k):
        raise AssertionError("closed mode must not generate")

    monkeypatch.setattr(envmod, "generate_episode", forbidden)
    monkeypatch.setattr(genmod, "generate_episode", forbidden)
    before = _hashes(episode_dir)
    env = make_env()
    for _ in range(2):
        closed(env, episode_dir)
        env.step(act("list_records", table="ledger", cursor=None, limit=50))
        env.step(act("submit", findings={"episode_id": "x", "findings": []}))
    assert _hashes(episode_dir) == before


def test_closed_mode_needs_no_truth_at_all(episode_dir, tmp_path):
    public_only = tmp_path / "public_only"
    shutil.copytree(episode_dir / "public", public_only / "public")   # evaluator/ deliberately absent
    env = make_env()
    obs, _ = closed(env, public_only)
    o, r, term, _, info = env.step(act("submit", findings={"episode_id": obs["manifest"]["episode_id"], "findings": []}))
    assert term and r == 0.0 and o["result"] == {"accepted": True} and info == {}
    assert env._env._state.judge is None                               # nothing evaluator-side in the env object


def test_reset_restores_the_initial_state(episode_dir):
    env = make_env()
    first, _ = closed(env, episode_dir)
    trace1 = [env.step(act("list_records", table="ledger", cursor=None, limit=7))[0] for _ in range(3)]
    env.step(act("submit", findings={"episode_id": "x", "findings": []}))
    again, _ = closed(env, episode_dir)
    trace2 = [env.step(act("list_records", table="ledger", cursor=None, limit=7))[0] for _ in range(3)]
    assert first == again and trace1 == trace2
    assert trace2[0]["remaining_steps"] == 99


def test_closed_mode_requires_episode_dir_and_rejects_unknown_keys():
    env = make_env()
    with pytest.raises(ValueError):
        env.reset(seed=1, options={"mode": "closed"})
    with pytest.raises(ValueError):
        env.reset(seed=1, options={"mode": "closed", "episode_dir": "x", "surprise": 1})
    with pytest.raises(ValueError):
        env.reset(seed=1, options={"mode": "evaluation"})
    with pytest.raises(RuntimeError):
        make_env().step(act("list_records", table="ledger"))


# ----------------------------------------------------------------------------- observation contract
def test_first_observation_has_exactly_the_required_fields(episode_dir):
    obs, info = closed(make_env(), episode_dir)
    assert set(obs) == {"task", "manifest", "policy", "remaining_steps"}
    assert isinstance(obs["task"], str) and isinstance(obs["manifest"], dict) and isinstance(obs["policy"], dict)
    assert obs["remaining_steps"] == 100
    json.dumps([obs, info])


def test_subsequent_observations_have_exactly_the_required_fields(episode_dir):
    env = make_env()
    closed(env, episode_dir)
    for action in (act("list_records", table="ledger", cursor=None, limit=5), act("nope"),
                   act("calculator", expression="2*3"), act("get_record", table="ledger", id="NOT-AN-ID")):
        o, r, term, trunc, info = env.step(action)
        assert set(o) == {"result", "error", "remaining_steps"}
        assert type(r) is float and type(term) is bool and type(trunc) is bool and isinstance(info, dict)
        json.dumps([o, r, term, trunc, info])


# ----------------------------------------------------------------------------- the five actions
def test_all_five_actions_in_valid_scenarios(episode_dir):
    env = make_env()
    obs, _ = closed(env, episode_dir)
    public = load_public_episode(episode_dir)
    o, *_ = env.step(act("list_records", table="ledger", cursor=None, limit=50))
    assert set(o["result"]) == {"records", "next_cursor"} and o["error"] is None
    row, inv, pay, fx = public.tables["ledger"][3], public.tables["invoices"][2], public.tables["payments"][1], public.tables["fx"][0]
    assert env.step(act("get_record", table="ledger", id=row["row_id"]))[0]["result"] == row
    assert env.step(act("get_record", table="invoices", id=inv["invoice_id"]))[0]["result"] == inv
    assert env.step(act("get_record", table="payments", id=pay["payment_id"]))[0]["result"] == pay
    key = f"{fx['date']}:{fx['source_currency']}:{fx['target_currency']}"
    assert env.step(act("get_record", table="fx", id=key))[0]["result"] == fx
    assert env.step(act("get_document", doc_id=inv["doc_id"]))[0]["result"] == inv
    assert env.step(act("get_document", doc_id=pay["doc_id"]))[0]["result"] == pay
    assert env.step(act("calculator", expression="0.1+0.2"))[0]["result"] == "0.3"
    o, r, term, trunc, info = env.step(act("submit", findings={"episode_id": obs["manifest"]["episode_id"], "findings": []}))
    assert o == {"result": {"accepted": True}, "error": None, "remaining_steps": 91}
    assert term and not trunc and r == 0.0 and info == {}


@pytest.mark.parametrize("bad", [
    act("drop_table"), act("shell", cmd="ls"), {"name": "list_records"}, {"name": 5, "args": {}},
    {"name": "list_records", "args": "ledger"}, {"name": "list_records", "args": {"table": "ledger"}, "extra": 1},
    {"name": "get_record", "args": {"action": "submit", "table": "ledger", "id": "x"}},
    {"action": "list_records", "table": "ledger"}, "list_records", None, 42, [],
])
def test_unknown_or_malformed_actions_are_bounded_and_consume_a_step(episode_dir, bad):
    env = make_env()
    closed(env, episode_dir)
    o, r, term, trunc, _ = env.step(bad)
    assert o["result"] is None and set(o["error"]) == {"code", "message"} and o["remaining_steps"] == 99
    assert r == 0.0 and not term and not trunc
    o, *_ = env.step(act("list_records", table="ledger", cursor=None, limit=1))   # still usable
    assert o["error"] is None and o["remaining_steps"] == 98


def test_unknown_ids_give_bounded_errors(episode_dir):
    env = make_env()
    closed(env, episode_dir)
    public = load_public_episode(episode_dir)
    universe = public.evidence_universe() | {i["invoice_id"] for i in public.tables["invoices"]}
    unknown = "UNKNOWN-ID-0001"
    assert unknown not in universe
    o, *_ = env.step(act("get_record", table="ledger", id=unknown))
    assert o["error"]["code"] == "unknown_id" and o["result"] is None
    o, *_ = env.step(act("get_document", doc_id=unknown))
    assert o["error"]["code"] == "unknown_document" and o["result"] is None
    assert unknown not in json.dumps(o)                                # input never echoed


def test_pagination_max_50_no_gaps_no_repeats_stable_cursor(episode_dir):
    env = make_env()
    closed(env, episode_dir)
    total = load_public_episode(episode_dir).manifest["record_counts"]["ledger"]
    assert total >= 101                                                # fixture L: at least three pages
    seen, cursor, pages = [], None, 0
    while True:
        o, *_ = env.step(act("list_records", table="ledger", cursor=cursor, limit=50))
        assert len(o["result"]["records"]) <= 50
        seen += [r["row_id"] for r in o["result"]["records"]]
        pages += 1
        if o["result"]["next_cursor"] is None:
            break
        cursor = o["result"]["next_cursor"]
    assert pages >= 3 and len(seen) == len(set(seen)) == total
    a = env.step(act("list_records", table="ledger", cursor=cursor, limit=50))[0]
    b = env.step(act("list_records", table="ledger", cursor=cursor, limit=50))[0]
    assert a["result"] == b["result"]


@pytest.mark.parametrize("expr", ["open('/etc/passwd')", "__import__('os').system('id')", "1e3", "2**8"])
def test_calculator_is_exact_and_safe(episode_dir, expr):
    env = make_env()
    closed(env, episode_dir)
    assert env.step(act("calculator", expression="1/4 + 0.05"))[0]["result"] == "0.3"
    o, *_ = env.step(act("calculator", expression=expr))
    assert o["result"] is None and o["error"]["code"] == "invalid_expression"


# ----------------------------------------------------------------------------- termination boundaries
def test_submit_terminates_and_later_actions_change_nothing(episode_dir):
    env = make_env()
    obs, _ = closed(env, episode_dir)
    sub = {"episode_id": obs["manifest"]["episode_id"], "findings": []}
    env.step(act("submit", findings=sub))
    o, r, term, trunc, _ = env.step(act("submit", findings={"episode_id": "other", "findings": []}))
    assert o["error"]["code"] == "episode_finished" and r == 0.0 and term and not trunc
    assert env.submitted_findings == sub


def test_closed_mode_reward_is_always_exactly_zero(episode_dir):
    env = make_env()
    obs, _ = closed(env, episode_dir)
    sub = oracle_submission(load_sealed_episode(episode_dir, load_public_episode(episode_dir)))
    rewards = [env.step(act("list_records", table=t, cursor=None, limit=50))[1] for t in ("ledger", "fx")]
    rewards.append(env.step(act("bogus"))[1])
    o, r, term, trunc, info = env.step(act("submit", findings=sub))     # a perfect answer
    rewards.append(r)
    assert rewards == [0.0, 0.0, 0.0, 0.0] and all(type(x) is float for x in rewards)
    assert info == {} and o["result"] == {"accepted": True}
    env2 = make_env()
    closed(env2, episode_dir)
    o, r, term, *_ = env2.step(act("submit", findings={"episode_id": 5}))   # invalid structure
    assert term and r == 0.0 and o["error"]["code"] == "invalid_submission"


def test_99_inspection_actions_then_submit_as_action_100(episode_dir):
    env = make_env()
    obs, _ = closed(env, episode_dir)
    for i in range(99):
        o, r, term, trunc, _ = env.step(act("calculator", expression="1+1"))
        assert not term and not trunc
    o, r, term, trunc, _ = env.step(act("submit", findings={"episode_id": obs["manifest"]["episode_id"], "findings": []}))
    assert term and not trunc and o["result"] == {"accepted": True} and o["remaining_steps"] == 0
    assert env.inspection_steps == 99


def test_100_inspection_actions_truncate_with_empty_findings(episode_dir):
    env = make_env()
    closed(env, episode_dir)
    for i in range(100):
        o, r, term, trunc, info = env.step(act("calculator", expression="1+1"))
    assert trunc and not term and o["remaining_steps"] == 0 and r == 0.0
    assert info == {"truncation_reason": "step_limit", "final_answer": "empty"}
    assert env.submitted_findings is None and env.inspection_steps == 100
    o, *_ = env.step(act("submit", findings={"episode_id": "x", "findings": []}))
    assert o["error"]["code"] == "episode_finished" and env.submitted_findings is None


def test_time_limit_truncates_with_empty_findings(episode_dir):
    now = [0.0]
    env = make_env(clock=lambda: now[0])
    obs, _ = closed(env, episode_dir)
    env.step(act("list_records", table="ledger", cursor=None, limit=5))
    now[0] = 60.5
    o, r, term, trunc, info = env.step(act("submit", findings={"episode_id": obs["manifest"]["episode_id"], "findings": []}))
    assert trunc and not term and r == 0.0 and o["error"]["code"] == "time_limit"
    assert env.submitted_findings is None


# ----------------------------------------------------------------------------- score_episode
@pytest.fixture(scope="module")
def fixture_dir(tmp_path_factory) -> dict:
    """Block-3 fixture: one issue A of a supported type, affected {R1}, 10000 KZT, evidence {D1, D2}, tau = 0."""
    d = tmp_path_factory.mktemp("block3") / "episode"
    generate_episode(9001, {"profile": "retail"}, str(d))
    public = load_public_episode(d)
    inv = public.tables["invoices"]
    ids = {"R": [i["invoice_id"] for i in inv[:5]], "D": [i["doc_id"] for i in inv[:3]], "eid": public.episode_id,
           "dir": d}
    return ids


def _write_truth(fx: dict, issues: list[dict], tolerance: int = 0) -> str:
    truth = {"schema_version": "1.0", "episode_id": fx["eid"], "base_currency": "KZT", "tolerance_minor": tolerance,
             "issues": issues}
    (fx["dir"] / "evaluator" / "truth.json").write_text(json.dumps(truth), encoding="utf-8")
    return str(fx["dir"])


def _issue(iid, ids, ev, type_="duplicate_invoice", amount=10000):
    # Minimal issue: only the officially listed fields (no "scenario").
    return {"issue_id": iid, "type": type_, "affected_ids": ids, "expected_amount_minor": amount, "currency": "KZT",
            "allowed_evidence_sets": [ev]}


def _f(ids, ev, type_="duplicate_invoice", amount=10000, cur="KZT", text="short"):
    return {"type": type_, "affected_ids": ids, "claimed_amount_minor": amount, "currency": cur,
            "evidence_ids": ev, "explanation": text}


def _expect(score, tp, fp, fn, ret):
    assert (score["tp"], score["fp"], score["fn"]) == (tp, fp, fn)
    assert abs(score["return"] - float(ret)) <= 1e-9
    f1 = Fraction(2 * tp, 2 * tp + fp + fn) if (2 * tp + fp + fn) else Fraction(1)
    assert abs(score["f1"] - float(f1)) <= 1e-9
    assert set(score) == {"tp", "fp", "fn", "precision", "recall", "f1", "return"}


def test_score_episode_published_block3_fixtures(fixture_dir):
    fx = fixture_dir
    R, D = fx["R"], fx["D"]
    A = _issue("A", [R[0]], [D[0], D[1]])
    B = _issue("B", [R[1]], [D[1], D[2]])
    F = _f([R[0]], [D[0], D[1]])
    sub = lambda findings: {"episode_id": fx["eid"], "findings": findings}  # noqa: E731
    d = _write_truth(fx, [A])
    _expect(score_episode(d, sub([F]), 10), 1, 0, 0, Fraction(98, 100))                       # 1
    _expect(score_episode(d, sub([]), 10), 0, 0, 1, -1)                                         # 2
    _expect(score_episode(d, sub([F, F]), 10), 1, 1, 0, Fraction(47, 150))                      # 5
    _expect(score_episode(d, sub([_f([R[0]], [D[0], D[1]], type_="fx_rate")]), 10), 0, 1, 1, -1)   # 6
    _expect(score_episode(d, sub([_f([R[1]], [D[0], D[1]])]), 10), 0, 1, 1, -1)                # 7
    _expect(score_episode(d, sub([_f([R[0]], [D[0], D[1]], amount=10001)]), 10), 0, 1, 1, -1)   # 8 (tau = 0)
    _expect(score_episode(d, sub([_f([R[0]], [D[0], D[1]], cur="USD")]), 10), 0, 1, 1, -1)     # 9
    _expect(score_episode(d, sub([_f([R[0]], [D[0]])]), 10), 0, 1, 1, -1)                      # 10
    _expect(score_episode(d, sub([_f([R[0]], [D[0], "UNKNOWN-ID-0001"])]), 10), 0, 1, 1, -1)    # 11
    mass = [_f([r], [D[0], D[1]], type_=t) for r in R
            for t in ("duplicate_invoice", "payment_allocation", "fx_rate", "period_attribution")]
    _expect(score_episode(d, sub(mass), 10), 1, 19, 0, Fraction(-871, 1050))                    # 12
    for steps, ret in ((0, 1), (50, Fraction(9, 10)), (100, Fraction(8, 10))):                  # 15-17
        _expect(score_episode(d, sub([F]), steps), 1, 0, 0, ret)
    d = _write_truth(fx, [])
    _expect(score_episode(d, sub([]), 10), 0, 0, 0, Fraction(98, 100))                         # 3
    _expect(score_episode(d, sub([F]), 10), 0, 1, 0, -1)                                        # 4
    d = _write_truth(fx, [A, B])
    _expect(score_episode(d, sub([F]), 10), 1, 0, 1, Fraction(47, 150))                         # 13
    _expect(score_episode(d, sub([F, _f([R[2]], [D[0], D[1]])]), 10), 1, 1, 1, Fraction(-2, 100))  # 14


@pytest.mark.parametrize("case", ["31_findings", "11_evidence", "1001_explanation", "string_amount", "bool_amount",
                                  "not_an_object"])
def test_score_episode_invalid_structure_returns_minus_one_and_nulls(fixture_dir, case):
    fx = fixture_dir
    R, D = fx["R"], fx["D"]
    d = _write_truth(fx, [_issue("A", [R[0]], [D[0], D[1]])])
    F = _f([R[0]], [D[0], D[1]])
    payload = {
        "31_findings": {"episode_id": fx["eid"], "findings": [F] * 31},
        "11_evidence": {"episode_id": fx["eid"], "findings": [dict(F, evidence_ids=[f"E{i}" for i in range(11)])]},
        "1001_explanation": {"episode_id": fx["eid"], "findings": [dict(F, explanation="x" * 1001)]},
        "string_amount": {"episode_id": fx["eid"], "findings": [dict(F, claimed_amount_minor="10000")]},
        "bool_amount": {"episode_id": fx["eid"], "findings": [dict(F, claimed_amount_minor=True)]},
        "not_an_object": [],
    }[case]
    score = score_episode(d, payload, 10)
    assert score == {"tp": None, "fp": None, "fn": None, "precision": None, "recall": None, "f1": None, "return": -1.0}


def test_score_episode_on_a_generated_episode(episode_dir):
    public = load_public_episode(episode_dir)
    sub = oracle_submission(load_sealed_episode(episode_dir, public))
    s = score_episode(str(episode_dir), sub, 12)
    assert (s["tp"], s["fp"], s["fn"]) == (4, 0, 0) and abs(s["return"] - (1 - 0.002 * 12)) < 1e-9
    s = score_episode(str(episode_dir), {"episode_id": public.episode_id, "findings": []}, 0)
    assert (s["tp"], s["fn"], s["return"]) == (0, 4, -1.0)
    with pytest.raises(ValueError):
        score_episode(str(episode_dir), sub, -1)


# ----------------------------------------------------------------------------- jury-style paired copies
_ID = re.compile(r"\b(?:GL|DOC|INV|PAY|SUP)-[A-Z0-9]+\b")


def _jury_copy(src: Path, dst: Path, reverse_ledger: bool, remap: bool) -> dict[str, str]:
    """Imitate the jury: copy the episode, permute ledger rows and/or replace every id bijectively in all
    files (public and evaluator); FX keys are natural keys and stay as they are."""
    shutil.copytree(src, dst)
    mapping: dict[str, str] = {}
    if remap:
        for p in sorted(dst.rglob("*")):
            if p.is_file():
                for token in _ID.findall(p.read_text(encoding="utf-8")):
                    mapping.setdefault(token, f"j{len(mapping):06d}")
        for p in sorted(dst.rglob("*")):
            if p.is_file():
                p.write_text(_ID.sub(lambda m: mapping[m.group(0)], p.read_text(encoding="utf-8")), encoding="utf-8")
    if reverse_ledger:
        ledger = dst / "public" / "ledger.csv"
        header, *rows = ledger.read_text(encoding="utf-8").splitlines()
        ledger.write_text("\n".join([header, *reversed(rows)]) + "\n", encoding="utf-8")
    return mapping


@pytest.mark.parametrize("reverse_ledger,remap", [(True, False), (False, True), (True, True)],
                         ids=["permute", "ids", "permute+ids"])
def test_jury_style_transformed_copy_loads_and_scores_identically(episode_dir, tmp_path, reverse_ledger, remap):
    variant = tmp_path / "variant"
    mapping = _jury_copy(episode_dir, variant, reverse_ledger, remap)
    original = load_public_episode(episode_dir)
    env = make_env()
    closed(env, variant)
    o, *_ = env.step(act("list_records", table="ledger", cursor=None, limit=50))
    first = o["result"]["records"][0]
    expected_first = original.tables["ledger"][-1 if reverse_ledger else 0]
    assert first["row_id"] == mapping.get(expected_first["row_id"], expected_first["row_id"])   # file order served
    sub_original = oracle_submission(load_sealed_episode(episode_dir, original))
    sub_variant = oracle_submission(load_sealed_episode(variant, load_public_episode(variant)))
    assert score_episode(str(episode_dir), sub_original, 7) == score_episode(str(variant), sub_variant, 7)
    # The original findings with ids mapped by the jury score identically on the variant.
    tr = lambda xs: [mapping.get(x, x) for x in xs]  # noqa: E731
    remapped = {"episode_id": sub_original["episode_id"],
                "findings": [dict(f, affected_ids=tr(f["affected_ids"]), evidence_ids=tr(f["evidence_ids"]))
                             for f in sub_original["findings"]]}
    assert score_episode(str(variant), remapped, 7) == score_episode(str(episode_dir), sub_original, 7)


# ----------------------------------------------------------------------------- isolation
def test_no_hidden_information_in_any_agent_visible_output(episode_dir, tmp_path):
    secret_dir = tmp_path / "jury-private-dir-q7z3"          # distinctive path: must never be echoed
    shutil.copytree(episode_dir, secret_dir)
    episode_dir = secret_dir
    sealed = load_sealed_episode(episode_dir, load_public_episode(episode_dir))
    env = make_env()
    outputs = []
    obs, info = closed(env, episode_dir, seed=987654321123)
    outputs.append([obs, info])
    for table in ("ledger", "invoices", "payments", "fx"):
        cursor = None
        while True:
            step = env.step(act("list_records", table=table, cursor=cursor, limit=50))
            outputs.append(step)
            cursor = step[0]["result"]["next_cursor"]
            if cursor is None:
                break
    for bad in (act("get_record", table="truth", id="x"), act("get_document", doc_id="../evaluator/truth.json"),
                act("calculator", expression="open('truth.json')"), act("nope")):
        outputs.append(env.step(bad))
    outputs.append(env.step(act("submit", findings=oracle_submission(sealed))))
    text = json.dumps(outputs)
    hidden = [t.issue_id for t in sealed.truth.issues] + [
        "provenance", "allowed_evidence_sets", "expected_amount_minor", "truth.json", "evaluator",
        "987654321123", str(episode_dir), episode_dir.name, '"seed"', '"tp"', '"f1"', '"return"']
    for needle in hidden:
        assert needle not in text, needle
    assert all(step[1] == 0.0 for step in outputs[1:])
