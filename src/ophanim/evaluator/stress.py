"""Large-scale stress testing of the generator, the independent auditor and the verifier (evaluator side).

Every case is a fixed (seed, config) pair; seeds are derived from the case id, so a case has the same seed at
every level and every run is reproducible. For each valid case the suite checks:

  * generation succeeds and the full independent verification passes: formats, clean books before mutation,
    exactly the declared issues after mutation, sufficient evidence sets, referential integrity (unique ids,
    no dangling references, consistent entities and amounts, accessible evidence) and the provenance chain
    (clean books + recorded injections == published books);
  * reproducibility: generating the same case twice gives byte-identical public data, truth and provenance;
  * presentation invariance (every case at level "full", every third case otherwise): a variant with other
    ids, names, record order and timestamp offset describes the same accounting truth after id mapping, and
    it verifies too.

Every invalid configuration must be rejected both by the schema and by the generator.

Levels: ``smoke`` (one case per error mix; used by the test suite), ``standard`` (mixes x profiles x 3
seeds), ``full`` (mixes x profiles x sizes x red-herring levels). The official ``ophanim verify`` runs only
the smoke level, through pytest.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections import Counter
from itertools import product

from pydantic import ValidationError

from ophanim.evaluator.metamorphic import canonical_truth, id_mapping, variant_config
from ophanim.evaluator.verifier import verify_generated
from ophanim.generator.episode import GeneratedEpisode, generate_episode
from ophanim.generator.model import GenerationError
from ophanim.schemas import ERROR_TYPES, EpisodeConfig
from ophanim.version import ENV_VERSION

ALL = {t: 1 for t in ERROR_TYPES}
S1, S2 = "fx_partial_payment_boundary", "fx_invoice_unapplied_payment"

# Error mixes from clean books to the 12-issue limit; every type, both scenarios, both explicit allocation modes.
MIXES: list[tuple[str, dict]] = [
    ("clean", {}),
    ("duplicate_x1", {"errors": {"duplicate_invoice": 1}}),
    ("allocation_auto_x1", {"errors": {"payment_allocation": 1}}),
    ("allocation_missing_x2", {"errors": {"payment_allocation": 2}, "allocation_mode": "missing"}),
    ("allocation_partial_x2", {"errors": {"payment_allocation": 2}, "allocation_mode": "partial"}),
    ("fx_x2", {"errors": {"fx_rate": 2}}),
    ("period_x2", {"errors": {"period_attribution": 2}}),
    ("all_four_x1", {"errors": dict(ALL)}),
    ("all_four_x2", {"errors": {t: 2 for t in ERROR_TYPES}}),
    ("singles_12", {"errors": {t: 3 for t in ERROR_TYPES}}),
    ("s1", {"scenarios": {S1: 1}}),
    ("s2", {"scenarios": {S2: 1}}),
    ("s1_s2", {"scenarios": {S1: 1, S2: 1}}),
    ("scenarios_12", {"scenarios": {S1: 3, S2: 3}}),
    ("mixed_12", {"errors": {t: 2 for t in ERROR_TYPES}, "scenarios": {S1: 1, S2: 1}}),
    ("partial_with_s1", {"errors": {"payment_allocation": 2, "fx_rate": 1}, "allocation_mode": "partial",
                         "scenarios": {S1: 1}}),
]
PROFILES = ("auto", "retail", "trading", "software", "manufacturing", "logistics", "consulting")
SIZES = ("small", "medium", "large")
RED_HERRING_LEVELS = ("low", "normal", "high")
PRESENTATIONS = (
    {},
    {"order": "shuffled"},
    {"timestamp_offset": "company"},
    {"id_salt": "stress", "name_salt": "stress", "order": "shuffled", "timestamp_offset": "company"},
)

# Each must be rejected by EpisodeConfig validation and therefore by generate_episode.
INVALID_CONFIGS: list[tuple[str, dict]] = [
    ("13_issues", {"errors": {"duplicate_invoice": 4, "payment_allocation": 4, "fx_rate": 4, "period_attribution": 1}}),
    ("scenarios_push_over_12", {"errors": {"fx_rate": 1}, "scenarios": {S1: 3, S2: 3}}),
    ("negative_count", {"errors": {"fx_rate": -1}}),
    ("count_as_string", {"errors": {"fx_rate": "1"}}),
    ("count_as_float", {"errors": {"fx_rate": 1.0}}),
    ("count_as_bool", {"errors": {"fx_rate": True}}),
    ("unknown_error_type", {"errors": {"fraud": 1}}),
    ("scenario_over_3", {"scenarios": {S1: 4}}),
    ("unknown_scenario", {"scenarios": {"fx_everything": 1}}),
    ("unknown_size", {"size": "huge"}),
    ("unknown_profile", {"profile": "banking"}),
    ("unknown_red_herring_level", {"distractors": "extreme"}),
    ("unknown_allocation_mode", {"allocation_mode": "random"}),
    ("unknown_order", {"presentation": {"order": "reversed"}}),
    ("empty_id_salt", {"presentation": {"id_salt": ""}}),
    ("unknown_timestamp_offset", {"presentation": {"timestamp_offset": "local"}}),
    ("unknown_config_version", {"config_version": "2.0"}),
    ("unknown_top_level_key", {"noise": 1}),
]

_PREFIX = "ophanim-stress"


def case_seed(case_id: str) -> int:
    return int(hashlib.sha256(f"{_PREFIX}|{case_id}".encode("utf-8")).hexdigest()[:12], 16)


def grid(level: str = "standard") -> list[dict]:
    """The deterministic list of valid cases for a level."""
    cases: list[dict] = []

    def add(case_id: str, mix: dict, profile: str, size: str, level_rh: str, pres: dict) -> None:
        cfg = copy.deepcopy(mix) | {"profile": profile, "size": size, "distractors": level_rh}
        if pres:
            cfg["presentation"] = dict(pres)
        cases.append({"case": case_id, "seed": case_seed(case_id), "config": cfg})

    if level == "smoke":
        for i, (name, mix) in enumerate(MIXES):
            add(f"smoke/{name}", mix, PROFILES[i % len(PROFILES)], SIZES[i % 3], RED_HERRING_LEVELS[(i // 3) % 3],
                PRESENTATIONS[i % len(PRESENTATIONS)])
    elif level == "standard":
        i = 0
        for (name, mix), profile in product(MIXES, PROFILES):
            for rep in range(3):
                add(f"standard/{name}/{profile}/{rep}", mix, profile, SIZES[(i + rep) % 3],
                    RED_HERRING_LEVELS[(i // 3 + rep) % 3], PRESENTATIONS[(i + rep) % len(PRESENTATIONS)])
            i += 1
    elif level == "full":
        for i, ((name, mix), profile, size, rh) in enumerate(product(MIXES, PROFILES, SIZES, RED_HERRING_LEVELS)):
            add(f"full/{name}/{profile}/{size}/{rh}", mix, profile, size, rh, PRESENTATIONS[i % len(PRESENTATIONS)])
    else:
        raise ValueError(f"unknown stress level {level!r}; choose smoke, standard or full")
    return cases


def episode_digest(ep: GeneratedEpisode) -> str:
    blob = {"manifest": ep.public.manifest, "policy": ep.public.policy, "tables": ep.public.tables,
            "truth": ep.sealed.truth.model_dump(), "provenance": ep.sealed.provenance}
    return hashlib.sha256(json.dumps(blob, sort_keys=True).encode("utf-8")).hexdigest()


def _variant_presentation(config: dict) -> dict:
    own = config.get("presentation", {})
    return {"id_salt": "stress-variant", "name_salt": "stress-variant",
            "order": "natural" if own.get("order") == "shuffled" else "shuffled",
            "timestamp_offset": "utc" if own.get("timestamp_offset") == "company" else "company"}


def check_case(seed: int, config: dict, *, presentation_check: bool) -> dict:
    out: dict = {"problems": [], "generated": False, "reproducible": None, "presentation_ok": None}
    try:
        ep = generate_episode(seed, config)
    except (GenerationError, ValidationError) as exc:
        out["problems"].append(f"generation failed: {type(exc).__name__}: {str(exc)[:200]}")
        return out
    out["generated"] = True
    out["problems"] += verify_generated(ep).problems

    out["reproducible"] = episode_digest(ep) == episode_digest(generate_episode(seed, config))
    if presentation_check:
        variant = generate_episode(seed, variant_config(config, _variant_presentation(config)))
        mapping = id_mapping(ep, variant)
        same_counts = ep.public.manifest["record_counts"] == variant.public.manifest["record_counts"]
        out["presentation_ok"] = (canonical_truth(ep, mapping) == canonical_truth(variant) and same_counts
                                  and verify_generated(variant).ok)

    prov, manifest = ep.sealed.provenance, ep.public.manifest
    out["stats"] = {
        "profile": prov["company"]["profile"], "currency": prov["company"]["base_currency"],
        "offset_minutes": prov["company"]["offset_minutes"], "size": config.get("size", "medium"),
        "red_herrings": config.get("distractors", "normal"), "issues": len(ep.sealed.truth.issues),
        "ledger_rows": manifest["record_counts"]["ledger"], "documents": manifest["document_count"],
        "types": [t.type for t in ep.sealed.truth.issues], "scenarios": [t.scenario for t in ep.sealed.truth.issues],
        "red_herring_kinds": [d["kind"] for d in prov["distractors"]],
        "allocation_kinds": [i["details"]["allocation_kind"] for i in prov["injections"] if i["type"] == "payment_allocation"],
    }
    return out


def check_invalid(config: dict) -> bool:
    """True when the configuration is rejected by the schema and by the generator."""
    try:
        EpisodeConfig.model_validate(config)
        return False
    except ValidationError:
        pass
    try:
        generate_episode(1, config)
        return False
    except ValidationError:
        return True


def run_stress(level: str = "standard", *, max_failures: int = 25) -> dict:
    started = time.perf_counter()
    cases = grid(level)
    every = 1 if level == "full" else 3
    generated = violations = cases_with_violations = repro_fail = pres_fail = pres_checked = 0
    failures: list[dict] = []
    cov: dict[str, Counter] = {k: Counter() for k in ("profiles", "currencies", "offsets_minutes", "sizes",
                                                     "red_herring_levels", "error_types", "scenarios",
                                                     "red_herring_kinds", "allocation_kinds")}
    ranges: dict[str, list[int]] = {"ledger_rows": [], "documents": [], "issues": []}
    for i, c in enumerate(cases):
        res = check_case(c["seed"], c["config"], presentation_check=(i % every == 0))
        generated += res["generated"]
        if res["problems"]:
            violations += len(res["problems"])
            cases_with_violations += 1
        if res["reproducible"] is False:
            repro_fail += 1
        if res["presentation_ok"] is not None:
            pres_checked += 1
            pres_fail += res["presentation_ok"] is False
        if (res["problems"] or res["reproducible"] is False or res["presentation_ok"] is False) and len(failures) < max_failures:
            failures.append({"case": c["case"], "seed": c["seed"], "config": c["config"], "problems": res["problems"][:5],
                             "reproducible": res["reproducible"], "presentation_ok": res["presentation_ok"]})
        s = res.get("stats")
        if s:
            cov["profiles"][s["profile"]] += 1
            cov["currencies"][s["currency"]] += 1
            cov["offsets_minutes"][str(s["offset_minutes"])] += 1
            cov["sizes"][s["size"]] += 1
            cov["red_herring_levels"][s["red_herrings"]] += 1
            cov["error_types"].update(s["types"])
            cov["scenarios"].update(x for x in s["scenarios"] if x != "single")
            cov["red_herring_kinds"].update(s["red_herring_kinds"])
            cov["allocation_kinds"].update(s["allocation_kinds"])
            for k in ranges:
                ranges[k].append(s[k])

    rejected = [name for name, cfg in INVALID_CONFIGS if check_invalid(cfg)]
    accepted_invalid = sorted({name for name, _ in INVALID_CONFIGS} - set(rejected))
    summary = {
        "suite": "ophanim-stress",
        "level": level,
        "env_version": ENV_VERSION,
        "configurations_tested": len(cases) + len(INVALID_CONFIGS),
        "valid_configurations": len(cases),
        "successful_generations": generated,
        "invalid_configurations": len(INVALID_CONFIGS),
        "rejected_invalid_configurations": len(rejected),
        "accepted_invalid_configurations": accepted_invalid,
        "invariant_violations": violations,
        "cases_with_violations": cases_with_violations,
        "reproducibility_failures": repro_fail,
        "presentation_checks": pres_checked,
        "presentation_invariance_failures": pres_fail,
        "issues_checked": sum(ranges["issues"]),
        "ranges": {k: [min(v), max(v)] if v else None for k, v in ranges.items()},
        "coverage": {k: dict(sorted(v.items())) for k, v in cov.items()},
        "failures": failures,
        "duration_seconds": round(time.perf_counter() - started, 2),
    }
    summary["ok"] = (generated == len(cases) and violations == 0 and repro_fail == 0 and pres_fail == 0
                     and not accepted_invalid)
    return summary
