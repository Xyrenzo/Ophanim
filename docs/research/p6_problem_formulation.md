# P6.2 — Formal problem definition

## 1. Candidate formulations

| formulation | fits? | why |
|---|---|---|
| POMDP (Kaelbling, Littman & Cassandra 1998) | **yes, as the base model** | hidden episode state, observations revealed by actions, terminal reward |
| Contextual decision problem (one context, one payoff) | partly | the episode is a context and the payoff is paid once, but decisions are sequential |
| Sequential information acquisition | **yes, for the inspection phase** | every non-submit action buys information at a fixed cost and never changes the world |
| Tool-using agent environment (cf. ReAct, WebShop) | yes, descriptively | actions are typed tool calls with arguments; outputs are structured documents |
| Hierarchical problem (options; Sutton, Precup & Singh 1999) | **yes, for policy design** | "scan a table" is a natural multi-step option; submission is a distinct structured decision |

Conclusion: model Ophanim as a **finite-horizon POMDP with a static hidden state, deterministic
transitions and observations, and a single terminal, set-valued structured action**, and solve it
hierarchically as (i) an information-acquisition process over the agent's revealed knowledge followed by
(ii) a structured prediction at submission.

## 2. The POMDP M = (S, A, O, T, Z, R, γ)

| element | definition | explicit in code? |
|---|---|---|
| **S** | `s_t = (W, D, t, τ, done)`: hidden world `W` (truth `Y*`, provenance, secret-keyed generation), public dataset `D` (manifest, policy, four tables), step counter `t`, elapsed time `τ`, termination flag | `W`/`D` = `SealedEpisode`/`PublicEpisode` (`generator/episode.py` L53, L77); `t`, `τ`, `done` = `_EpisodeState` (`env/environment.py` L54) |
| **s₀ ~ ρ** | `ρ(seed, config, secret)` = the generator | `generate_episode` (`generator/episode.py` L170) |
| **A** | `A = A_list ∪ A_get ∪ A_doc ∪ A_calc ∪ A_submit ∪ A_invalid`, each a parameterized family (see §4) | `schemas.py` L123–L152 |
| **T** | deterministic: `t ← t+1`; `done ← true` on submit or `t = 100` or `τ > 60 s`; `W, D` never change | `step` L109 |
| **O, Z** | `o_t = Z(D, a_t, t)`: the tool's output on `D`, or an error code, plus `100 − t`; deterministic | `Toolbox` (`env/tools.py`); observation dict L126 |
| **R** | `r_t = 0` before termination; `r_T = clip(2·F1(F, Y*) − 1 − 0.002·k, −1, 1)`; malformed `F` → −1; truncation → `F = ∅` | `evaluator/reward.py` L44, `judge.py` |
| **γ** | 1 (finite horizon H = 100; episode return = terminal reward) | conceptual |

Conceptual abstractions (not objects in the code): the belief state, the information-acquisition value,
and the decomposition in §3. The wall clock is outside the MDP (it is a truncation condition, matching
Gymnasium's definition of `truncated`).

## 3. Structural properties (with evidence)

**P1 — Static state, deterministic observations ⇒ the revealed set is a sufficient statistic.** Because
`D` is fixed and `Z` is deterministic, the posterior over `D` given the history `h_t` depends only on the
set of records revealed so far, `K_t ⊆ D`. Repeating an action reveals nothing new. An agent that stores
`K_t` explicitly (a keyed record store) loses no information relative to the full history; recurrence is
not *required* for optimality, only for agents without explicit memory.

**P2 — The answer is a function of the public data.** For every generated episode the independent
auditor (`audit/reconcile.py`, which imports no generator code) reproduces the truth exactly:
108 episodes in the test suite and 20/20 in the closed suite (`runs/verify/report.json`, data checks).
So `Y* = g(D)` with `g` = the published policy: the uncertainty is purely **epistemic** (which records
have not been read), never aleatoric. Once `D` is revealed, the optimal submission is determined.

**P3 — Decomposition and headroom.** Let `C(D)` be the number of steps a strategy spends revealing
enough of `D` to determine `Y*`. An agent that reads until `Y*` is determined and then submits `g(K)`
earns `E[1 − 0.002·C(D)]`. Because the reward never exceeds 1, any acquisition strategy can improve on
a full scan by at most the full scan's own cost.
A full scan reveals everything; measured full-scan cost is 12–22 steps on medium episodes
(`p6_repository_audit.md` §9). Hence **the maximum gain from smarter acquisition over a full scan is at
most 0.002 × (full-scan steps) ≈ 0.024–0.044 per medium episode**, while errors in the submission move
the reward on a scale of 2.0.

**P4 — Certifying absence requires (near-)exhaustive reading.** To submit "no duplicate / no misallocation"
the agent must have read every relevant posting and document; negative evidence cannot be sampled.
Clean episodes therefore also require near-full scans for a correct *and justified* empty answer.

**P5 — Flat failure plateau.** If F1 = 0 then `2·0 − 1 − 0.002k ≤ −1`, so the reward is exactly −1 for
*every* behaviour that yields no true positive. Measured: the random explorer scored exactly −1.0 on all
15 erroneous closed episodes. For a policy-gradient learner this means zero return variance, hence zero
advantage signal, on erroneous episodes until a first true positive is found.

**P6 — A degenerate attractor.** Among policies that cannot find errors, "submit nothing immediately"
earns `2·p_clean − 1` (−0.5 on the closed suite, measured). This is the predicted local optimum for any
learner whose findings are not yet precise; it must be reported as a reference point.

**P7 — Partial credit.** With k issues, m true positives and f false positives:
`F1 = 2m / (m + k + f)`. Examples (0 inspection steps): k=3: m=1,f=0 → 0.00; m=2 → 0.60; m=3 → 1.00;
m=3,f=1 → 0.71. A finding is either fully correct (type, exact id set, amount within τ, currency, complete
evidence) or worth nothing; there is no partial credit *within* a finding. Under the official check
definitions τ = 0 by default, and ids are compared exactly (currently τ = 1 with normalised ids; see
`p6_official_compliance_audit.md`).

## 4. Action space

`A = ⋃_κ {κ} × Θ_κ(h_t)`, κ ∈ {list, get, doc, calc, submit}. Argument domains depend on the history:

* `Θ_list = Tables(4) × Cursor(h_t) × {1..50}` — cursors are tokens returned by earlier pages.
* `Θ_get = Tables × Ids(h_t) ∪ FxKeys` — ids must have been seen; FX keys are constructible from public
  dates and currencies.
* `Θ_doc = DocIds(h_t)`.
* `Θ_calc = L(grammar)` — any arithmetic string.
* `Θ_submit` = sets of ≤ 30 findings, each `(type, S_aff ⊆ Ids, amount ∈ ℕ, currency, S_ev ⊆ Ids ∪ FxKeys,
  text)`.

Order-of-magnitude estimate (not a measurement): in a medium episode with ~950 citable ids, a uniformly
random duplicate finding must pick the right pair among ~10³–10⁴ invoice pairs, the right amount (±1)
and a complete 3-id evidence set among ~10⁸ triples — success probability far below 10⁻¹². Undirected
exploration of `Θ_submit` cannot discover reward; this is the central obstacle for RL from scratch.

## 5. Research problems

| # | problem | how it appears in Ophanim | consequence |
|---|---|---|---|
| 1 | Sequential information acquisition | each step reveals ≤ 50 records for 0.002 | cheap full scans dominate under the official reward (P3); studying acquisition needs scarcity regimes (research-only, agent-side) |
| 2 | Partial observability | unread records | resolvable; explicit memory makes the belief exact (P1) |
| 3 | Sparse terminal reward | one reward per episode | long horizon to the only signal |
| 4 | Credit assignment | reward depends on the whole submitted *set* and on earlier reads | per-finding credit is not given by the official reward; needs factorisation or supervised auxiliary signals in training |
| 5 | Variable-length episodes | 2–100 steps; table sizes vary per episode | masks and set encoders, not fixed-length vectors |
| 6 | Structured, parameterized actions | §4 | requires an action adapter (pointer / candidate selection) |
| 7 | Evidence-constrained prediction | TP needs a complete evidence set of existing ids | evidence must be assembled from *revealed* records, never generated |
| 8 | Limited budget | 100 steps, 60 s, 0.002/step | budget is rarely binding today (P3) |
| 9 | Generalisation | unseen seeds, profiles, combinations, presentation | test on held-out profiles/combinations and metamorphic variants; procedural generation gives unlimited training data |

## 6. Formal task statement (for research documents)

Given an episode drawn from `ρ(seed, config, secret)`, an agent interacts for at most H = 100 steps with
a deterministic, read-only toolset over a static public dataset `D`, maintaining its own memory of the
revealed records `K_t`. It must terminate with a set `F` of structured findings whose ids and evidence are
drawn from revealed records. It is scored once by the fixed one-to-one matcher against the hidden
`Y* = g(D)` with `R = clip(2·F1 − 1 − 0.002·k, −1, 1)`. The learning objective is to maximise
`E_ρ[R]` on held-out episode distributions, while research metrics (`p6_experiment_protocol.md`) separate
**acquisition efficiency** from **finding-construction accuracy**.
