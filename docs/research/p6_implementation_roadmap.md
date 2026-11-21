# P6 — Implementation roadmap P7–P13

Principles for every phase: the official environment API, reward, findings schema, matcher, closed
evaluation, baselines and dataset reproducibility stay unchanged; the full existing test suite (476 tests)
must still pass; new dependencies arrive only when a phase needs them, as optional extras; every learned
agent is evaluated through the existing process boundary.

## P6-C — Official compliance fixes (blocking; precede P7; awaiting approval)

The official check definitions (2026-11-20) are binding and were not available when P0–P5 were built.
`p6_official_compliance_audit.md` and `p6_traceability_matrix.md` show that the jury currently cannot run
Blocks 1, 3 and 4 (no `judge_adapter.py`, no `episode_dir` loading, no `score_episode`) and that several
matcher/tool conventions differ from the definitions. These fixes belong to the official benchmark, not
to the research phases, and must land first:

1. **P0** `judge_adapter.py` (generate_episode / make_env / reset with `episode_dir` / step envelope /
   score_episode), file-order episode loader, closed-mode env without truth, README section.
2. **P1** exact-id matcher and tool lookups; any-string type and currency compared exactly; remove extra
   structural limits; evidence universe = all tool-accessible ids; τ = 0 default; refund red herring;
   requestable partial vs missing allocation; documented red-herring guarantees.
3. **P2** lexicographic tie-break; provenance and id-field documentation.
4. **Verification:** adapter-level replay of C01–C20, Block-3 tests 1–20 via `score_episode`, M01–M12,
   file-level paired checks; full suite; `ophanim verify`; Docker offline run.

**Acceptance:** every row of the traceability matrix VERIFIED via the adapter; all existing tests pass (with
the adversarial tests updated where they encoded the old −1 behaviour); `data/` regenerated;
`ENV_VERSION` bumped. P7 below assumes P6-C is done and treats the adapter envelope as the agent
interface (`p6_architecture_constraints.md`).

## Dependency graph

```
P7 interface & infrastructure ──► P8 datasets & imitation ──► P9 RL core ──► P10 financial intelligence
        │                                                          │                    │
        └──────────────► P11 generalisation & benchmark research ◄─┴────────────────────┘
                                         │
                                         ▼
                               P12 autonomous auditor ──► P13 research-grade platform
```

## P7 — Agent interface and learning infrastructure (no learning, no new mandatory dependency)

**Deliverables:** `PublicEnv` facade; `RevealedStore`; symbolic primitives (time, money, FX, grouping,
structural links); generic candidate generator and multi-convention feature extractor; finding builder
with pre-submit schema validation; hierarchical action adapter (macro acquisition + candidate submission);
research suites with seed namespaces (`research/*` sets); research-metrics module (records and documents
revealed, tool histogram, evidence quality, near-miss profile) computed from public trajectories and judge
logs; `LabelProvider` for open splits; the silent reference policy; leakage and import tests (architecture
§7). Optional: a thin Gymnasium wrapper behind an extra.

**Acceptance criteria:**
* A *scripted* agent built only from P7 components (fixed rules over candidates and features) reproduces
  the reference auditor's results on `research/test-iid` (F1 = 1 on ≥ 99 % of episodes). This shows the
  adapter loses no information; it is not a learning claim.
* Leakage tests pass: features are unchanged when only the hidden truth changes; agent packages import
  no generator/evaluator/reconcile code; `LabelProvider` refuses secret-keyed episodes.
* Namespace disjointness test passes; research metrics match hand-computed values on fixtures.
* No changes in `env/`, `evaluator/`, `schemas.py`, `policies/`, `configs/`; `python -m ophanim verify`
  still prints PASS.

**Risks:** primitives that silently encode the answer (mitigated by multi-convention features and the
RQ6 ablations); performance of feature extraction (budget: < 1 s per episode).

## P8 — Datasets and imitation learning (introduces the optional `[learning]` extra: PyTorch)

**Deliverables:** demonstration generator with diverse, observation-consistent demonstrators (randomised
table order, targeted FX lookups, early-stop variants), each scored by the judge on training splits;
dataset format (public trajectory + agent annotations + labels from `LabelProvider`); BC for the candidate
and convention heads; BC + DAgger for the acquisition head; first learning curves with ≥ 5 seeds.

**Acceptance criteria:**
* The BC agent beats the silent reference (−0.5 on the closed-suite mix; `2·p_clean − 1` on research
  sets) and simple reconciliation on `research/val`, with non-overlapping 95 % CIs.
* Training is reproducible: same seed → same checkpoint metrics on CPU (tolerance documented).
* The official image still has a single runtime dependency; the learning extra installs separately.

**Risks:** low demonstration diversity (track action-sequence entropy); BC that only learns the counter
(explained by the audit; mitigated by diverse demonstrators).

## P9 — Reinforcement-learning core

**Deliverables:** in-repo PPO derived from the CleanRL single-file design (attribution, MIT) with masked
factorised heads and GAE; experiments: PPO from scratch (RQ9), BC → PPO (RQ1); a value-based comparator
(DQN/QR-DQN macro head + DRRN-style candidate scorer, RQ2); optional SB3/sb3-contrib MaskablePPO cross-check
on a padded MultiBinary adapter.

**Acceptance criteria:**
* Learning curves, IQM and CIs for every condition, ≥ 5 seeds each, all on identical episodes.
* RQ1, RQ2 and RQ9 answered with the pre-registered criteria (support or reject; a rejection is a valid
  outcome).
* Every RL-trained agent runs unchanged through `run_episode_isolated` with `mode="eval"`.

**Risks:** H-collapse (expected without BC); instability (Engstrom et al. 2020: implementation details
dominate) — mitigated by unit tests of the PPO components against known small tasks.

## P10 — Financial intelligence

**Deliverables:** convention-learning experiments (RQ10); primitive ablations (RQ6); evidence-quality and
near-miss diagnostics; calibration channel and temperature scaling (RQ12); error taxonomy per error type
and per red-herring kind.

**Acceptance criteria:** per-type and per-red-herring results with CIs; the reward-only agent's convention
accuracy reported against the supervised one; no change to the official schema.

**Risks:** trivialisation through primitives — every result must report the matching ablation.

## P11 — Generalisation and benchmark research

**Deliverables:** OOD suites (profile, combination, size, distractor, presentation), research-only scarcity
regimes (RQ8), curriculum study (RQ5), memory study (RQ3), representation study (RQ4), invariance study
(RQ11), optional Decision Transformer study if a diverse corpus exists.

**Acceptance criteria:** every OOD result reported as a paired gap with CI; metamorphic agreement measured
for every learned agent; one consolidated research report.

**Risks:** overfitting the curriculum order (mixture schedules, held-out evaluation); test-set reuse
(each final model is evaluated once).

## P12 — Autonomous auditor

**Deliverables:** the best agent packaged as an `agent_runtime` policy; evaluation on the official closed
suite (as an additional row; baselines unchanged); optional LLM tool-agent research track through the same
JSON protocol, run outside the official setting when it needs network or exceeds 60 s.

**Acceptance criteria:** the closed evaluation still passes 20/20/20 (data, metamorphic, reproducibility);
the agent's row reports reward, P/R/F1, steps and runtime with the same report code; LLM results are
labelled non-official, with model id and decoding settings recorded.

**Risks:** results on 20 episodes are noisy (−0.599 vs −0.662 across two suites for the same baseline);
headline claims use the research test sets.

## P13 — Research-grade platform

**Deliverables:** experiment registry (config + code hash + data namespace + seeds → result), leaderboard
format separating official reward from research metrics, documentation for external agents, CI running
the official suite and the leakage tests, packaging of the learning extra.

**Acceptance criteria:** a third party can reproduce one P9 result and the official evaluation from a clean
checkout with documented commands; the leaderboard never mixes research-shaped rewards with the official
reward.

## Suggested order and first step after approval

1. P7 `RevealedStore` + primitives + candidate generator + finding builder, validated by the P7 scripted
   agent (largest risk reduction: proves the adapter is lossless and leak-free).
2. P7 research metrics and namespaces (needed by every later comparison).
3. P8 BC on the submission heads (cheapest learning signal, highest headroom), then acquisition.
4. P9 PPO with the RQ9 control first (fast, informative), then BC → PPO.

## Open questions

* Which research budget regimes make acquisition non-trivial without changing the official setting
  (step caps, larger research-only sizes)? To be decided with RQ8 pilots.
* Whether a fully pointer-based agent (Approach 2) can reach non-trivial F1 at all under exact-match
  scoring — RQ6 will tell.
* Whether local LLMs can operate within 60 s per episode — needs measurement in P12.
