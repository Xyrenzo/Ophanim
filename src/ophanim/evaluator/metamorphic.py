"""Metamorphic testing: equivalent episodes must be evaluated equivalently.

A *variant* of an episode keeps (seed, content config) and changes only
presentation: record order, every public id, company/supplier names and/or the
UTC offset used to write timestamps. The economics, errors and evidence are the
same, so after mapping ids:

  * the truth is identical (type, affected ids, amount, currency, evidence sets);
  * the oracle answer, mapped, is still exactly correct and earns the same reward;
  * a deterministic agent (the reference auditor) finds the same issues and
    earns the same reward (its step count depends only on table sizes);
  * both variants pass independent verification (no discrepancy created/removed).

Id mapping uses the evaluator-only provenance: both variants map the same
internal keys to different public ids.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from ophanim.generator.episode import GeneratedEpisode, generate_episode

DEFAULT_VARIANT = {"id_salt": "metamorphic-b", "name_salt": "metamorphic-b", "order": "shuffled", "timestamp_offset": "company"}


def variant_config(config: dict, presentation: dict | None = None) -> dict:
    cfg = copy.deepcopy(config)
    cfg["presentation"] = dict(presentation or DEFAULT_VARIANT)
    return cfg


def id_mapping(a: GeneratedEpisode, b: GeneratedEpisode) -> dict[str, str]:
    """Public id in A -> public id in B, via shared internal keys. FX keys are content-based (identity)."""
    ma, mb = a.sealed.provenance["id_map"], b.sealed.provenance["id_map"]
    if set(ma) != set(mb):
        raise ValueError("variants do not share the same internal keys - not a metamorphic pair")
    mapping = {ma[k]: mb[k] for k in ma}
    mapping[a.public.episode_id] = b.public.episode_id
    return mapping


def translate_findings(findings: list[dict], mapping: dict[str, str]) -> list[dict]:
    def tr(x: str) -> str:
        return mapping.get(x, x)  # FX keys are unchanged

    return [dict(f, affected_ids=[tr(x) for x in f["affected_ids"]], evidence_ids=[tr(x) for x in f["evidence_ids"]])
            for f in findings]


def canonical_truth(ep: GeneratedEpisode, mapping: dict[str, str] | None = None) -> list[tuple]:
    def tr(x: str) -> str:
        return mapping.get(x, x) if mapping else x

    out = []
    for t in ep.sealed.truth.issues:
        out.append((t.type, tuple(sorted(tr(x) for x in t.affected_ids)), t.expected_amount_minor, t.currency, t.scenario,
                    tuple(sorted(tuple(sorted(tr(x) for x in s)) for s in t.allowed_evidence_sets))))
    return sorted(out)


@dataclass
class PairResult:
    seed: int
    ok: bool
    checks: dict = field(default_factory=dict)


def check_pair(seed: int, config: dict, presentation: dict | None = None, secret: bytes | None = None) -> PairResult:
    """Run every metamorphic check for one (episode, variant) pair."""
    from ophanim.env import OphanimEnv
    from ophanim.evaluator.oracle import oracle_submission
    from ophanim.evaluator.runner import run_episode
    from ophanim.evaluator.verifier import verify_generated
    from ophanim.policies import ReferenceAuditor

    a = generate_episode(seed, config, secret=secret)
    b = generate_episode(seed, variant_config(config, presentation), secret=secret)
    m = id_mapping(a, b)
    checks: dict[str, bool] = {}
    checks["ids_changed"] = a.public.episode_id != b.public.episode_id and not (
        {r["row_id"] for r in a.public.tables["ledger"]} & {r["row_id"] for r in b.public.tables["ledger"]})
    checks["truth_equivalent"] = canonical_truth(a, m) == canonical_truth(b)
    checks["both_verify"] = verify_generated(a).ok and verify_generated(b).ok

    # Oracle answer from A, translated into B's ids, must be exactly correct in B with the same reward.
    oa = oracle_submission(a.sealed)
    ob = {"episode_id": m[oa["episode_id"]], "findings": translate_findings(oa["findings"], m)}
    rewards = []
    for ep_seed_cfg, sub in (((seed, config), oa), ((seed, variant_config(config, presentation)), ob)):
        env = OphanimEnv(mode="train", secret=secret)
        env.reset(*ep_seed_cfg)
        _, r, *_ = env.step({"action": "submit", "findings": sub})
        rewards.append((r, env.evaluator_outcome().tp))
    checks["oracle_reward_equal"] = rewards[0] == rewards[1] and rewards[0][0] == 1.0

    # A deterministic public-data agent behaves identically up to ids.
    ra = run_episode(OphanimEnv(mode="train", secret=secret), ReferenceAuditor(), seed, config)
    rb = run_episode(OphanimEnv(mode="train", secret=secret), ReferenceAuditor(), seed, variant_config(config, presentation))
    checks["agent_reward_equal"] = (ra.reward, ra.steps, ra.tp, ra.fp) == (rb.reward, rb.steps, rb.tp, rb.fp)
    return PairResult(seed=seed, ok=all(checks.values()), checks=checks)
