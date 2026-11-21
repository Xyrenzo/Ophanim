"""Equivalent episodes (new order, ids, names, timestamp representation) are evaluated equivalently."""

from __future__ import annotations

import pytest

from ophanim.evaluator.metamorphic import check_pair, id_mapping, translate_findings, variant_config
from ophanim.evaluator.oracle import oracle_submission
from ophanim.generator import generate_episode

CONFIGS = [
    {},
    {"errors": {"duplicate_invoice": 1, "payment_allocation": 1, "fx_rate": 1, "period_attribution": 1}},
    {"scenarios": {"fx_partial_payment_boundary": 1, "fx_invoice_unapplied_payment": 1}, "errors": {"period_attribution": 1}},
    {"size": "large", "errors": {"duplicate_invoice": 3, "payment_allocation": 3}, "presentation": {"order": "shuffled"}},
]
VARIANTS = [
    {"id_salt": "v1", "name_salt": "default", "order": "shuffled", "timestamp_offset": "utc"},       # order + ids
    {"id_salt": "v2", "name_salt": "n2", "order": "natural", "timestamp_offset": "company"},        # ids + names + tz text
    {"id_salt": "v3", "name_salt": "n3", "order": "shuffled", "timestamp_offset": "company"},       # everything
]


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("config", CONFIGS, ids=["clean", "four-types", "interacting", "large-shuffled"])
@pytest.mark.parametrize("variant", VARIANTS, ids=["order+ids", "ids+names+tz", "all"])
def test_metamorphic_pair(seed, config, variant):
    res = check_pair(seed, config, variant)
    assert res.ok, res.checks


def test_variant_really_changes_order_ids_and_names():
    cfg = {"errors": {"duplicate_invoice": 1}}
    a = generate_episode(3, cfg)
    b = generate_episode(3, variant_config(cfg, VARIANTS[2]))
    assert [r["row_id"] for r in a.public.tables["ledger"]] != [r["row_id"] for r in b.public.tables["ledger"]]
    assert a.public.manifest["company_name"] != b.public.manifest["company_name"]
    m = id_mapping(a, b)
    order_a = [m[r["row_id"]] for r in a.public.tables["ledger"]]
    order_b = [r["row_id"] for r in b.public.tables["ledger"]]
    assert sorted(order_a) == sorted(order_b) and order_a != order_b   # same rows, different order
    assert a.public.tables["ledger"][0]["timestamp"].endswith("+00:00")
    assert not b.public.tables["ledger"][0]["timestamp"].endswith("+00:00") or b.public.manifest["timezone"] == "+00:00"


def test_untranslated_oracle_answer_fails_on_the_variant():
    """Sanity: the variant is genuinely different - the old ids earn nothing there."""
    from ophanim.env import OphanimEnv

    cfg = {"errors": {"duplicate_invoice": 1, "fx_rate": 1}}
    a = generate_episode(4, cfg)
    b = generate_episode(4, variant_config(cfg, VARIANTS[0]))
    stale = oracle_submission(a.sealed)
    env = OphanimEnv()
    env.reset(4, variant_config(cfg, VARIANTS[0]))
    _, r, *_ = env.step({"action": "submit", "findings": dict(stale, episode_id=b.public.episode_id)})
    assert r == -1.0
    env.reset(4, variant_config(cfg, VARIANTS[0]))
    fixed = {"episode_id": b.public.episode_id, "findings": translate_findings(stale["findings"], id_mapping(a, b))}
    _, r, *_ = env.step({"action": "submit", "findings": fixed})
    assert r == 1.0
