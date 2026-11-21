"""Generator: consistency, causal errors, configurability, formats, reproducibility."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime

import pytest
from pydantic import ValidationError

from ophanim.audit.dataset import PublicDataset
from ophanim.evaluator.verifier import verify_directory, verify_generated
from ophanim.generator import generate_episode
from ophanim.schemas import EpisodeConfig
from ophanim.timeutil import parse_offset

from tests.conftest import episode

ALL_CONFIGS = [
    {},
    {"errors": {"duplicate_invoice": 1}},
    {"errors": {"payment_allocation": 1}},
    {"errors": {"fx_rate": 1}},
    {"errors": {"period_attribution": 1}},
    {"errors": {"duplicate_invoice": 2, "payment_allocation": 3}},
    {"size": "small", "distractors": "high", "errors": {"duplicate_invoice": 1, "payment_allocation": 1, "fx_rate": 1}},
    {"size": "large", "distractors": "low", "errors": {"duplicate_invoice": 3, "payment_allocation": 3, "fx_rate": 3, "period_attribution": 3}},
    {"scenarios": {"fx_partial_payment_boundary": 1, "fx_invoice_unapplied_payment": 1}, "errors": {"period_attribution": 1}},
]


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("config", ALL_CONFIGS, ids=lambda c: json.dumps(c, sort_keys=True))
def test_every_episode_passes_independent_verification(seed, config):
    """Clean before mutation, exactly the declared discrepancies after, sufficient evidence."""
    rep = verify_generated(episode(seed, config))
    assert rep.ok, rep.problems[:5]
    assert rep.issues_found_independently == rep.issues_declared


def test_generation_is_byte_for_byte_reproducible(tmp_path):
    cfg = {"errors": {"duplicate_invoice": 1, "payment_allocation": 2}}
    a, b = generate_episode(123, cfg), generate_episode(123, cfg)
    a.write(tmp_path / "a")
    b.write(tmp_path / "b")
    for rel in ["public/manifest.json", "public/policy.json", "public/ledger.csv", "public/invoices.jsonl",
                "public/payments.jsonl", "public/fx.csv", "evaluator/truth.json", "evaluator/provenance.json"]:
        assert (tmp_path / "a" / rel).read_bytes() == (tmp_path / "b" / rel).read_bytes(), rel


def test_different_seeds_give_different_episodes():
    a, b = episode(1), episode(2)
    assert a.public.episode_id != b.public.episode_id
    assert a.public.tables["ledger"] != b.public.tables["ledger"]


@pytest.mark.parametrize("error_type", ["duplicate_invoice", "payment_allocation"])
@pytest.mark.parametrize("count", [0, 1, 3])
def test_each_error_type_is_independently_configurable(error_type, count):
    ep = episode(31, {"errors": {error_type: count}})
    types = Counter(t.type for t in ep.sealed.truth.issues)
    assert types[error_type] == count
    assert sum(types.values()) == count


def test_clean_episode_has_no_truth_but_has_red_herrings():
    ep = episode(5, {"distractors": "high"})
    assert ep.sealed.truth.issues == []
    kinds = {d["kind"] for d in ep.sealed.provenance["distractors"]}
    assert {"reversed_duplicate", "vendor_ref_collision", "repeat_order_same_amount"} <= kinds
    assert kinds & {"split_payment", "partial_payment", "batch_payment"}
    assert verify_generated(ep).ok


def test_same_seed_same_company_with_and_without_errors():
    clean, dirty = episode(8), episode(8, {"errors": {"duplicate_invoice": 1}})
    for k in ("base_currency", "period_start", "period_end", "timezone", "company_profile"):
        assert clean.public.manifest[k] == dirty.public.manifest[k]
    assert clean.public.episode_id != dirty.public.episode_id           # config is part of the episode identity
    assert clean.public.tables["fx"] == dirty.public.tables["fx"]


def test_config_validation_is_strict():
    with pytest.raises(ValidationError):
        EpisodeConfig.model_validate({"errors": {"duplicate_invoice": 7, "payment_allocation": 6}})  # 13 > 12
    with pytest.raises(ValidationError):
        EpisodeConfig.model_validate({"errors": {"duplicate_invoice": "1"}})
    with pytest.raises(ValidationError):
        EpisodeConfig.model_validate({"surprise": True})
    with pytest.raises(ValidationError):
        EpisodeConfig.model_validate({"errors": {"new_secret_type": 1}})


def test_public_formats():
    ep = episode(3, {"errors": {"duplicate_invoice": 1, "payment_allocation": 1}})
    t = ep.public.tables
    assert list(t["ledger"][0]) == ["row_id", "timestamp", "account", "debit_minor", "credit_minor", "currency",
                                    "entity_id", "invoice_id", "payment_id"]
    assert list(t["fx"][0]) == ["date", "source_currency", "target_currency", "rate"]
    for k in ("doc_id", "invoice_id", "entity_id", "issued_at", "due_at", "currency", "total_minor", "line_items"):
        assert k in t["invoices"][0]
    for k in ("doc_id", "payment_id", "timestamp", "currency", "amount_minor", "invoice_refs"):
        assert k in t["payments"][0]
    for row in t["ledger"]:
        assert type(row["debit_minor"]) is int and type(row["credit_minor"]) is int
        assert datetime.fromisoformat(row["timestamp"]).utcoffset() is not None
    # Explicit nulls exist (bank rows reference no invoice) and are None, never "".
    assert any(r["invoice_id"] is None for r in t["ledger"])
    assert all(r["invoice_id"] != "" for r in t["ledger"])
    assert any(p["invoice_refs"] is None for p in t["payments"])  # remittance absent -> explicit null
    for r in t["fx"]:
        assert isinstance(r["rate"], str) and "e" not in r["rate"].lower()
    m = ep.public.manifest
    for k in ("schema_version", "episode_id", "base_currency", "period_start", "period_end", "timezone",
              "record_counts", "document_count", "rounding"):
        assert k in m
    parse_offset(m["timezone"])


def test_files_roundtrip_and_verify_from_disk(tmp_path):
    ep = episode(4, {"errors": {"duplicate_invoice": 1, "payment_allocation": 2}})
    ep.write(tmp_path / "ep")
    loaded = PublicDataset.from_directory(tmp_path / "ep" / "public")
    assert loaded.ledger == ep.public.tables["ledger"]
    assert loaded.invoices == ep.public.tables["invoices"]
    assert loaded.payments == ep.public.tables["payments"]
    assert loaded.fx == ep.public.tables["fx"]
    assert "null" in (tmp_path / "ep" / "public" / "ledger.csv").read_text(encoding="utf-8")
    assert verify_directory(tmp_path / "ep").ok


def test_currency_precision_zero_and_three_decimal_currencies_are_exercised():
    seen = set()
    for seed in range(40):
        ep = episode(seed)
        exps = ep.public.policy["currency_exponents"]
        seen.update(c for c, e in exps.items() if e in (0, 3))
        if {"JPY", "KWD"} <= seen:
            break
    assert {"JPY", "KWD"} <= seen


def test_utc_date_differs_from_local_date_in_clean_books():
    """Red herring: legitimate documents whose UTC date is not their accounting date."""
    hits = 0
    for seed in range(10):
        ep = episode(seed)
        tz = parse_offset(ep.public.manifest["timezone"])
        for p in ep.public.tables["payments"]:
            ts = datetime.fromisoformat(p["timestamp"])
            if ts.date() != ts.astimezone(tz).date():
                hits += 1
        assert verify_generated(ep).ok
    assert hits > 0


def test_ids_reveal_nothing_about_injection():
    """The injected copy's public id is a random token: its rank among ids is spread out."""
    relative_ranks = set()
    for seed in range(20):
        ep = episode(seed, {"errors": {"duplicate_invoice": 1}})
        prov = ep.sealed.provenance
        copy_key = prov["injections"][0]["details"]["copy"]
        copy_id = prov["id_map"][copy_key]
        ids = sorted(i["invoice_id"] for i in ep.public.tables["invoices"])
        relative_ranks.add(round(ids.index(copy_id) / len(ids), 1))
        assert len(copy_id) == len("INV-") + 8
    assert len(relative_ranks) >= 5
