"""Shared fixtures. Generated episodes are cached per session to keep the suite fast."""

from __future__ import annotations

import functools
import json

import pytest

from ophanim.generator import generate_episode

DIRTY_P1 = {"errors": {"duplicate_invoice": 2, "payment_allocation": 2}}
CLEAN = {}


def _freeze(config: dict) -> str:
    return json.dumps(config, sort_keys=True)


@functools.lru_cache(maxsize=256)
def _cached(seed: int, frozen: str):
    return generate_episode(seed, json.loads(frozen))


def episode(seed: int, config: dict | None = None):
    return _cached(seed, _freeze(config or {}))


@pytest.fixture
def make_episode():
    return episode


def oracle_findings(ep) -> list[dict]:
    from ophanim.evaluator.oracle import oracle_submission

    return oracle_submission(ep.sealed)["findings"]
