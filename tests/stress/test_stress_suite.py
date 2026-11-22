"""Quick stress level (part of the regular test suite) and the structure of the longer levels.

The standard and full levels run through `python -m ophanim stress --level standard|full`; they are not part
of pytest so that `ophanim verify` stays fast.
"""

from __future__ import annotations

from itertools import product

import pytest
from pydantic import ValidationError

from ophanim.evaluator.stress import (
    INVALID_CONFIGS,
    MIXES,
    PROFILES,
    RED_HERRING_LEVELS,
    SIZES,
    case_seed,
    check_case,
    grid,
    run_stress,
)
from ophanim.generator.episode import generate_episode
from ophanim.schemas import ERROR_TYPES, EpisodeConfig


@pytest.fixture(scope="module")
def smoke() -> dict:
    return run_stress("smoke")


def test_smoke_level_is_clean_and_reports_every_required_count(smoke):
    assert smoke["ok"], smoke["failures"]
    assert smoke["configurations_tested"] == len(MIXES) + len(INVALID_CONFIGS)
    assert smoke["successful_generations"] == smoke["valid_configurations"] == len(MIXES)
    assert smoke["rejected_invalid_configurations"] == smoke["invalid_configurations"] == len(INVALID_CONFIGS)
    assert smoke["invariant_violations"] == smoke["reproducibility_failures"] == smoke["presentation_invariance_failures"] == 0
    assert smoke["presentation_checks"] > 0 and isinstance(smoke["duration_seconds"], float)


def test_smoke_level_covers_every_error_type_scenario_size_and_red_herring_level(smoke):
    cov = smoke["coverage"]
    assert set(cov["error_types"]) == set(ERROR_TYPES)
    assert set(cov["scenarios"]) == {"fx_partial_payment_boundary", "fx_invoice_unapplied_payment"}
    assert set(cov["sizes"]) == set(SIZES) and set(cov["red_herring_levels"]) == set(RED_HERRING_LEVELS)
    assert set(cov["allocation_kinds"]) == {"missing", "partial"}
    assert len(cov["profiles"]) == 6 and len(cov["currencies"]) >= 5 and len(cov["offsets_minutes"]) >= 4
    assert smoke["ranges"]["issues"] == [0, 12]


def test_summary_is_deterministic_apart_from_the_duration(smoke):
    again = run_stress("smoke")
    strip = lambda s: {k: v for k, v in s.items() if k != "duration_seconds"}
    assert strip(again) == strip(smoke)


@pytest.mark.parametrize("name,cfg", INVALID_CONFIGS, ids=[n for n, _ in INVALID_CONFIGS])
def test_every_invalid_configuration_is_rejected_by_schema_and_generator(name, cfg):
    with pytest.raises(ValidationError):
        EpisodeConfig.model_validate(cfg)
    with pytest.raises(ValidationError):
        generate_episode(1, cfg)


def test_levels_are_deterministic_and_cover_the_grid():
    assert grid("standard") == grid("standard")
    full = grid("full")
    assert len(full) == len(MIXES) * len(PROFILES) * len(SIZES) * len(RED_HERRING_LEVELS)
    combos = {(c["config"]["profile"], c["config"]["size"], c["config"]["distractors"]) for c in full}
    assert combos == set(product(PROFILES, SIZES, RED_HERRING_LEVELS))
    assert len({c["seed"] for c in full}) == len(full)          # distinct seeds
    assert len(grid("standard")) >= 300
    assert case_seed("smoke/clean") == case_seed("smoke/clean")
    with pytest.raises(ValueError):
        grid("everything")


def test_a_case_reports_a_generation_failure_instead_of_crashing():
    res = check_case(1, {"errors": {"fraud": 1}}, presentation_check=False)
    assert not res["generated"] and res["problems"] and res["problems"][0].startswith("generation failed")
