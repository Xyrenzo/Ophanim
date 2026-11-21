"""Closed-evaluation isolation: the agent runs in its own process and cannot reach hidden data.

Hostile agents are real child processes (small scripts written to tmp_path).
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from ophanim.env import OphanimEnv
from ophanim.evaluator.process_runner import agent_command, run_episode_isolated
from ophanim.generator import generate_episode

CFG = {"errors": {"duplicate_invoice": 1, "payment_allocation": 1, "fx_rate": 1, "period_attribution": 1}}
SECRET = b"jury-secret-value"


def _script(tmp_path, body: str) -> list[str]:
    path = tmp_path / "agent.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(path)]


def test_agent_process_receives_no_hidden_data_and_no_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("OPHANIM_EVAL_SECRET", SECRET.decode())
    dump = tmp_path / "received.jsonl"
    snoop = tmp_path / "snoop.json"
    cmd = _script(tmp_path, f"""
        import json, os, sys
        env_keys = sorted(os.environ)
        info = {{"secret": os.environ.get("OPHANIM_EVAL_SECRET"), "cwd_files": os.listdir("."),
                 "ophanim_vars": [k for k in env_keys if k.upper().startswith("OPHANIM")]}}
        open({str(snoop)!r}, "w").write(json.dumps(info))
        out = open({str(dump)!r}, "w")
        for line in sys.stdin:
            out.write(line); out.flush()
            msg = json.loads(line)
            if msg["type"] == "end":
                break
            if msg["type"] == "reset":
                eid = msg["observation"]["manifest"]["episode_id"]
                print(json.dumps({{"action": {{"action": "list_records", "table": "ledger", "cursor": None, "limit": 50}}}}), flush=True)
            elif not (msg["terminated"] or msg["truncated"]):
                print(json.dumps({{"action": {{"action": "submit", "findings": {{"episode_id": eid, "findings": []}}}}}}), flush=True)
    """)
    env = OphanimEnv(mode="eval", secret=SECRET)
    rec = run_episode_isolated(env, cmd, 77, CFG, policy_name="snoop")
    assert rec.terminated and rec.steps == 2

    info = json.loads(snoop.read_text())
    assert info["secret"] is None and info["ophanim_vars"] == [] and info["cwd_files"] == []

    received = dump.read_text()
    sealed = generate_episode(77, CFG, secret=SECRET).sealed
    for t in sealed.truth.issues:
        assert t.issue_id not in received
    for needle in ("provenance", "allowed_evidence_sets", "expected_amount_minor", SECRET.decode(), '"seed"'):
        assert needle not in received
    # closed mode: every reward the agent saw is 0.0 and info is empty
    for line in received.splitlines():
        msg = json.loads(line)
        if msg["type"] == "step":
            assert msg["reward"] == 0.0 and msg["info"] == {}


def test_malformed_and_oversized_messages_are_invalid_actions(tmp_path):
    cmd = _script(tmp_path, """
        import json, sys
        for i, line in enumerate(sys.stdin):
            msg = json.loads(line)
            if msg["type"] == "end":
                break
            if msg["type"] == "step" and (msg["terminated"] or msg["truncated"]):
                continue
            if i == 0:
                print("this is not json", flush=True)
            elif i == 1:
                print(json.dumps({"action": {"action": "calculator", "expression": "1" * 2_000_000}}), flush=True)
            elif i == 2:
                print(json.dumps(["not", "a", "dict"]), flush=True)
            else:
                print(json.dumps({"action": {"action": "submit", "findings": {"episode_id": "x", "findings": []}}}), flush=True)
    """)
    env = OphanimEnv(mode="train")
    rec = run_episode_isolated(env, cmd, 78, CFG, policy_name="garbage")
    assert rec.steps == 4 and rec.terminated
    codes = [e for e in env.evaluator_log() if e["event"] == "invalid_submission"]
    assert codes  # wrong episode id -> invalid submission, -1
    assert rec.reward == -1.0


def test_crashing_agent_is_scored_as_empty_answer(tmp_path):
    cmd = _script(tmp_path, "import sys; sys.exit(3)\n")
    rec = run_episode_isolated(OphanimEnv(mode="eval"), cmd, 79, {}, policy_name="crash")
    assert rec.truncated and rec.outcome_reason == "agent_exited" and rec.reward == 1.0  # clean books: empty answer is right


def test_hanging_agent_is_cut_off_by_the_time_budget(tmp_path):
    cmd = _script(tmp_path, "import time\ntime.sleep(60)\n")
    rec = run_episode_isolated(OphanimEnv(mode="eval", time_limit_seconds=0.5), cmd, 80, CFG, policy_name="hang")
    assert rec.truncated and rec.outcome_reason == "agent_timeout" and rec.reward == -1.0
    assert rec.runtime_seconds < 10


@pytest.mark.parametrize("policy", ["random_explorer", "simple_reconciliation", "mark_everything", "reference_auditor"])
def test_isolated_and_in_process_runs_are_identical(policy):
    from ophanim.evaluator.runner import run_episode
    from ophanim.policies import make_policy

    iso = run_episode_isolated(OphanimEnv(mode="eval", secret=SECRET), agent_command(policy), 81, CFG, policy_name=policy)
    inp = run_episode(OphanimEnv(mode="eval", secret=SECRET), make_policy(policy), 81, CFG)
    assert (iso.reward, iso.steps, iso.tp, iso.fp, iso.fn) == (inp.reward, inp.steps, inp.tp, inp.fp, inp.fn)


def test_secret_defeats_seed_brute_force():
    """With the evaluator's secret, the public generator cannot reproduce the episode from the seed alone."""
    closed = generate_episode(5, CFG, secret=SECRET)
    for guess in (None, b"", b"jury-secret-valuE"):
        opened = generate_episode(5, CFG, secret=guess)
        assert opened.public.episode_id != closed.public.episode_id
        assert opened.public.tables["ledger"] != closed.public.tables["ledger"]
    assert generate_episode(5, CFG, secret=SECRET).public.tables == closed.public.tables  # still reproducible
