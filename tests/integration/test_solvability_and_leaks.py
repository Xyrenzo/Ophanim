"""Solvability through the tools, and no hidden data in anything the agent sees."""

from __future__ import annotations

import json

import pytest

from ophanim.analytics import TrajectoryLogger
from ophanim.env import OphanimEnv
from ophanim.evaluator.runner import run_episode
from ophanim.generator import generate_episode
from ophanim.policies import ReferenceAuditor

CONFIGS = [{}, {"errors": {"duplicate_invoice": 1, "payment_allocation": 2}},
           {"size": "large", "errors": {"duplicate_invoice": 4, "payment_allocation": 4}}]


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("config", CONFIGS, ids=["clean", "mixed", "large"])
def test_reference_auditor_solves_every_episode_within_budget(seed, config):
    rec = run_episode(OphanimEnv(mode="train"), ReferenceAuditor(), seed, config)
    assert rec.f1 == 1.0 and rec.fp == 0 and rec.fn == 0
    assert rec.terminated and rec.steps < 60
    assert rec.reward == pytest.approx(1.0 - 0.002 * rec.inspection_steps)


def _hidden_strings(seed, config) -> list[str]:
    ep = generate_episode(seed, config)
    hidden = [t.issue_id for t in ep.sealed.truth.issues]
    hidden += ["truth.json", "provenance", "allowed_evidence_sets", "expected_amount_minor", "issue_id", "secret"]
    hidden += [d["kind"] for d in ep.sealed.provenance["distractors"]]
    hidden += [str(k) for k in ep.sealed.provenance["id_map"] if k[0] in "IPRS" and k[1:].isdigit()]  # internal keys
    return hidden


@pytest.mark.parametrize("mode", ["train", "eval"])
def test_trajectories_contain_no_hidden_information(mode):
    seed, config = 3, {"errors": {"duplicate_invoice": 2, "payment_allocation": 2}}
    logger = TrajectoryLogger()
    run_episode(OphanimEnv(mode=mode), ReferenceAuditor(), seed, config, logger)
    text = "\n".join(logger.lines)
    for line in logger.lines:
        row = json.loads(line)
        assert list(row) == ["episode_id", "step", "action", "observation", "reward", "terminated", "truncated"]
    # Issue ids, truth/provenance vocabulary, red-herring labels and internal keys (I0001, R00001, ...)
    # must never appear in anything the agent saw.
    for needle in _hidden_strings(seed, config):
        assert f'"{needle}"' not in text and f'{needle}"' not in text, needle
    assert f'"{seed}"' not in text and '"seed"' not in text


def test_observations_never_include_seed_or_config():
    env = OphanimEnv()
    obs, info = env.reset(987654321, {"errors": {"duplicate_invoice": 1}, "presentation": {"id_salt": "salty"}})
    dumped = json.dumps([obs, info])
    assert "987654321" not in dumped and "salty" not in dumped and "id_salt" not in dumped
