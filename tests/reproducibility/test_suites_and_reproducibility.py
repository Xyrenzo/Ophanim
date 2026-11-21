"""Versioned suites, split separation, and exact replay of whole trajectories."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from ophanim.analytics import TrajectoryLogger
from ophanim.env import OphanimEnv
from ophanim.evaluator.evaluation import derive_seed
from ophanim.evaluator.runner import run_episode
from ophanim.policies import AGENT_POLICIES, make_policy
from ophanim.schemas import ERROR_TYPES, EpisodeConfig

ROOT = Path(__file__).resolve().parents[2]


def suite(name: str) -> dict:
    return json.loads((ROOT / "configs" / name).read_text(encoding="utf-8"))


def _norm(cfg: dict) -> str:
    c = EpisodeConfig.model_validate(cfg).model_dump()
    c.pop("presentation")
    return json.dumps(c, sort_keys=True)


def test_suites_are_versioned_and_valid():
    for name in ("train/suite.json", "dev/suite.json", "eval/official_suite.json"):
        s = suite(name)
        assert s["suite_version"] == "1.0" and s["config_version"] == "1.0"
        for e in s["episodes"]:
            EpisodeConfig.model_validate(e["config"])


def test_train_and_dev_have_ten_episodes_with_disjoint_seeds():
    train, dev = suite("train/suite.json"), suite("dev/suite.json")
    assert len(train["episodes"]) == len(dev["episodes"]) == 10
    tseeds, dseeds = {e["seed"] for e in train["episodes"]}, {e["seed"] for e in dev["episodes"]}
    assert len(tseeds) == len(dseeds) == 10 and not tseeds & dseeds


def test_official_suite_structure():
    ev = suite("eval/official_suite.json")
    cats = Counter(e["category"] for e in ev["episodes"])
    assert len(ev["episodes"]) == 20 and cats == {"clean": 5, "interacting": 5, "mixed": 10}
    for e in ev["episodes"]:
        cfg = EpisodeConfig.model_validate(e["config"])
        if e["category"] == "clean":
            assert cfg.total_issues() == 0
        if e["category"] == "interacting":
            assert cfg.scenarios.fx_partial_payment_boundary + cfg.scenarios.fx_invoice_unapplied_payment >= 1
    mixed = [EpisodeConfig.model_validate(e["config"]).errors for e in ev["episodes"] if e["category"] == "mixed"]
    for t in ERROR_TYPES:  # balanced: every mandatory type appears in several mixed episodes
        assert sum(1 for m in mixed if getattr(m, t) > 0) >= 5, t
    assert len(ev["metamorphic"]["variants"]) >= 1


def test_eval_uses_new_parameter_combinations_and_unseen_seeds():
    train, dev, ev = suite("train/suite.json"), suite("dev/suite.json"), suite("eval/official_suite.json")
    open_combos = {_norm(e["config"]) for e in train["episodes"] + dev["episodes"]}
    closed = [e for e in ev["episodes"] if EpisodeConfig.model_validate(e["config"]).total_issues() > 0]
    assert all(_norm(e["config"]) not in open_combos for e in closed)
    open_seeds = {e["seed"] for e in train["episodes"] + dev["episodes"]}
    for base in ("ophanim-public-demo-2026", "jury-hidden-base"):
        seeds = {derive_seed(base, "eval", i) for i in range(20)} | {derive_seed(base, "metamorphic", i) for i in range(20)}
        assert len(seeds) == 40 and not seeds & open_seeds


def _trace(policy: str, seed: int, cfg: dict) -> str:
    logger = TrajectoryLogger()
    run_episode(OphanimEnv(mode="train"), make_policy(policy, 0), seed, cfg, logger)
    return hashlib.sha256("\n".join(logger.lines).encode()).hexdigest()


@pytest.mark.parametrize("policy", sorted(AGENT_POLICIES))
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_same_seed_config_and_policy_replay_identically(policy, seed):
    cfg = {"errors": {"duplicate_invoice": 1, "payment_allocation": 1, "fx_rate": 1, "period_attribution": 1}}
    assert _trace(policy, seed, cfg) == _trace(policy, seed, cfg)
