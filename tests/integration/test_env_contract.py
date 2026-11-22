"""Environment contract: reset/step, tools, limits, termination, determinism, isolation."""

from __future__ import annotations

import json

import pytest

from ophanim.env import MAX_STEPS, OphanimEnv
from ophanim.env.tools import ERROR_MESSAGES, encode_cursor
from ophanim.evaluator.oracle import oracle_action
from ophanim.generator import generate_episode

DIRTY = {"errors": {"duplicate_invoice": 1, "payment_allocation": 1}}


def new_env(mode="train", **kw) -> OphanimEnv:
    return OphanimEnv(mode=mode, **kw)


def listing(table="ledger", cursor=None, limit=50):
    return {"action": "list_records", "table": table, "cursor": cursor, "limit": limit}


# ----------------------------------------------------------------------------- reset / step shape
def test_reset_returns_observation_and_info():
    obs, info = new_env().reset(1, DIRTY)
    assert set(obs) == {"task", "manifest", "policy", "tools", "remaining_steps", "time_budget_seconds"}
    assert obs["remaining_steps"] == MAX_STEPS == 100
    assert set(info) == {"env_version", "schema_version", "mode"}
    json.dumps(obs)
    json.dumps(info)


def test_step_returns_five_tuple_of_json_values():
    env = new_env()
    env.reset(1)
    out = env.step(listing())
    assert len(out) == 5
    obs, reward, terminated, truncated, info = out
    assert isinstance(obs, dict) and isinstance(reward, float) and terminated is False and truncated is False
    assert set(obs) == {"ok", "result", "error", "remaining_steps"}
    assert obs["remaining_steps"] == 99 and reward == 0.0 and info == {}
    json.dumps(obs)


def test_step_before_reset_is_an_error():
    with pytest.raises(RuntimeError):
        new_env().step(listing())


def test_options_alias_and_gymnasium_style_keywords():
    env = new_env()
    o1, _ = env.reset(seed=5, options=DIRTY)
    o2, _ = new_env().reset(seed=5, config=DIRTY)
    assert o1 == o2


# ----------------------------------------------------------------------------- tools
def test_pagination_covers_every_row_once_with_max_50():
    env = new_env()
    obs, _ = env.reset(2)
    total = obs["manifest"]["record_counts"]["ledger"]
    seen, cursor = [], None
    while True:
        o, *_ = env.step(listing("ledger", cursor, 50))
        assert o["ok"] and len(o["result"]["records"]) <= 50 and o["result"]["total"] == total
        seen += [r["row_id"] for r in o["result"]["records"]]
        cursor = o["result"]["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == total


def test_cursors_are_stable_and_validated():
    env = new_env()
    env.reset(2)
    first, *_ = env.step(listing("ledger", None, 10))
    cur = first["result"]["next_cursor"]
    a, *_ = env.step(listing("ledger", cur, 10))
    b, *_ = env.step(listing("ledger", cur, 10))
    assert a["result"] == b["result"]
    for bad in ("garbage", encode_cursor("invoices", 10), encode_cursor("ledger", 10**6), "c1_!!!", "c1_" + "A" * 100):
        o, *_ = env.step(listing("ledger", bad, 10))
        assert o["error"]["code"] == "invalid_cursor"


@pytest.mark.parametrize("limit,code", [(51, "invalid_limit"), (0, "invalid_limit"), (-1, "invalid_limit"),
                                        ("50", "invalid_action"), (True, "invalid_action"), (10.0, "invalid_action")])
def test_limit_validation(limit, code):
    env = new_env()
    env.reset(2)
    o, *_ = env.step(listing("ledger", None, limit))
    assert o["error"]["code"] == code and o["result"] is None


def test_get_record_and_get_document():
    env = new_env()
    obs, _ = env.reset(3)
    page, *_ = env.step(listing("invoices", None, 5))
    inv = page["result"]["records"][0]
    o, *_ = env.step({"action": "get_record", "table": "invoices", "id": inv["invoice_id"]})
    assert o["result"]["record"] == inv
    for variant in (" " + inv["invoice_id"], inv["invoice_id"] + " ", inv["invoice_id"].lower()):
        o, *_ = env.step({"action": "get_record", "table": "invoices", "id": variant})
        assert o["error"]["code"] == "unknown_id"                   # exact lookup: no case/space folding
    o, *_ = env.step({"action": "get_document", "doc_id": inv["doc_id"]})
    assert o["result"] == {"doc_type": "invoice", "document": inv}
    fxp, *_ = env.step(listing("fx", None, 1))
    r = fxp["result"]["records"][0]
    key = f"{r['date']}:{r['source_currency']}:{r['target_currency']}"
    o, *_ = env.step({"action": "get_record", "table": "fx", "id": key})
    assert o["result"]["record"] == r


@pytest.mark.parametrize("action,code", [
    ({"action": "get_record", "table": "ledger", "id": "GL-DOESNOTEXIST"}, "unknown_id"),
    ({"action": "get_record", "table": "truth", "id": "x"}, "unknown_table"),
    ({"action": "list_records", "table": "provenance", "cursor": None, "limit": 5}, "unknown_table"),
    ({"action": "get_document", "doc_id": "../evaluator/truth.json"}, "unknown_document"),
    ({"action": "calculator", "expression": "__import__('os').system('dir')"}, "invalid_expression"),
    ({"action": "shell", "cmd": "ls"}, "invalid_action"),
    ({"action": "sql", "query": "select * from truth"}, "invalid_action"),
    ({"action": "get_record", "table": "ledger"}, "invalid_action"),
    ({"action": "get_record", "table": "ledger", "id": "x", "extra": 1}, "invalid_action"),
    ("list_records", "invalid_action"),
    (["list_records"], "invalid_action"),
    (None, "invalid_action"),
    (42, "invalid_action"),
])
def test_invalid_actions_are_bounded_and_consume_a_step(action, code):
    env = new_env()
    env.reset(4, DIRTY)
    o, r, term, trunc, info = env.step(action)
    assert o["ok"] is False and o["error"]["code"] == code and o["remaining_steps"] == 99
    assert r == 0.0 and not term and not trunc and info == {}
    assert o["error"]["message"] == ERROR_MESSAGES[code]  # fixed text, agent input never echoed
    dumped = json.dumps(o)
    for needle in ("Traceback", "File \"", "provenance", "seed", "ophanim", "evaluator", ".json"):
        assert needle not in dumped


# ----------------------------------------------------------------------------- termination
def test_submit_terminates_and_reward_returned_in_train_mode():
    env = new_env()
    env.reset(6)
    o, r, term, trunc, _ = env.step({"action": "submit", "findings": {"episode_id": env._state.manifest["episode_id"], "findings": []}})
    assert term is True and trunc is False and r == 1.0 and o["ok"]


def test_step_limit_truncates_with_empty_answer():
    env = new_env()
    env.reset(7)  # clean books -> empty answer is correct (F1 = 1)
    for i in range(MAX_STEPS - 1):
        o, r, term, trunc, _ = env.step({"action": "calculator", "expression": "1+1"})
        assert not term and not trunc and r == 0.0
    o, r, term, trunc, info = env.step({"action": "calculator", "expression": "1+1"})
    assert trunc is True and term is False and o["remaining_steps"] == 0
    assert r == pytest.approx(1.0 - 0.002 * 100)
    assert info == {"truncation_reason": "step_limit", "final_answer": "empty"}
    o, r, term, trunc, _ = env.step({"action": "submit", "findings": {"episode_id": "x", "findings": []}})
    assert o["error"]["code"] == "episode_finished" and r == 0.0 and trunc is True


def test_step_limit_on_erroneous_books_gives_minus_one():
    env = new_env()
    env.reset(7, DIRTY)
    for _ in range(MAX_STEPS):
        o, r, term, trunc, _ = env.step({"action": "nonsense"})
    assert trunc and r == -1.0


def test_submit_on_the_last_step_terminates_not_truncates():
    env = new_env()
    obs, _ = env.reset(8)
    for _ in range(MAX_STEPS - 1):
        env.step({"action": "calculator", "expression": "2*2"})
    o, r, term, trunc, _ = env.step({"action": "submit", "findings": {"episode_id": obs["manifest"]["episode_id"], "findings": []}})
    assert term is True and trunc is False and r == pytest.approx(1.0 - 0.002 * 99)


def test_time_limit_truncates():
    now = [0.0]
    env = new_env(clock=lambda: now[0])
    env.reset(9, DIRTY)
    env.step(listing())
    now[0] = 61.0
    o, r, term, trunc, info = env.step(listing())
    assert trunc and not term and o["error"]["code"] == "time_limit"
    assert info["truncation_reason"] == "time_limit" and r == -1.0  # empty answer on erroneous books


# ----------------------------------------------------------------------------- closed mode
def test_eval_mode_withholds_reward_and_diagnostics():
    env = new_env(mode="eval")
    env.reset(10, DIRTY)
    ep = generate_episode(10, DIRTY)
    o, r, term, trunc, info = env.step(oracle_action(ep.sealed))
    assert term and r == 0.0 and info == {} and o == {"ok": True, "result": {"status": "submitted"}, "error": None, "remaining_steps": 99}
    assert env.evaluator_outcome().reward == 1.0  # the evaluator still knows


# ----------------------------------------------------------------------------- determinism and isolation
def _trace(seed, config, actions, mode="train"):
    env = new_env(mode)
    out = [env.reset(seed, config)]
    for a in actions:
        out.append(env.step(a))
    return json.dumps(out, sort_keys=True)


def test_same_seed_config_actions_reproduce_everything():
    actions = [listing(), listing("invoices", None, 7), {"action": "calculator", "expression": "1/7"},
               {"action": "get_record", "table": "ledger", "id": "nope"}, {"action": "submit", "findings": {"episode_id": "x", "findings": []}}]
    assert _trace(11, DIRTY, actions) == _trace(11, DIRTY, actions)
    assert _trace(11, DIRTY, actions) != _trace(12, DIRTY, actions)


def test_reset_isolates_episodes():
    env = new_env()
    env.reset(13, DIRTY)
    for _ in range(30):
        env.step(listing())
    env.step({"action": "submit", "findings": {"episode_id": "x", "findings": []}})
    obs_b, info_b = env.reset(14)
    fresh_obs, fresh_info = new_env().reset(14)
    assert (obs_b, info_b) == (fresh_obs, fresh_info)
    o, *_ = env.step(listing())
    assert o["remaining_steps"] == 99
    assert env.evaluator_outcome() is None


def test_returned_records_are_copies():
    env = new_env()
    env.reset(15)
    o, *_ = env.step(listing("ledger", None, 1))
    o["result"]["records"][0]["debit_minor"] = -999
    again, *_ = env.step(listing("ledger", None, 1))
    assert again["result"]["records"][0]["debit_minor"] != -999
