# P6.1 — Repository and environment audit

Status: research document, P6. Nothing in the official environment, evaluator, reward, schemas or
baselines was modified to produce it.

> **Read together with `p6_official_compliance_audit.md` and `p6_traceability_matrix.md`.** The official
> check definitions (published 2026-11-20) add an adapter interface and exact matcher conventions. Against
> those, several behaviours described below as implemented are non-compliant:
> * case- and whitespace-insensitive id lookup and matching;
> * τ = 1 by default;
> * extra structural limits that turn false positives into −1.
>
> The official integration entry points are also missing.

## 1. Method

Inspected on 2026-11-21 (working tree, no commits yet): `pyproject.toml`, `requirements.lock`, `README.md`,
`docs/*.md`, `configs/*/suite.json`, every module in `src/ophanim/`, every test module in `tests/`, and the
evaluation outputs in `runs/`. Claims below cite the code line that implements them. Measurements were
taken with a read-only script that imports the package and runs episodes; it writes nothing to the
repository (script kept outside the repo; its outputs are quoted in §9).

## 2. Architecture snapshot

| package / module | lines | role (verified in code) |
|---|---:|---|
| `env/environment.py` | 208 | `OphanimEnv`: `reset` L80, `step` L109, evaluator-only accessors L134–L160 |
| `env/tools.py` | 136 | read-only `Toolbox` over public tables: `list_records` L97, `get_record` L113, `get_document` L123, `calculator` L132 |
| `env/calculator.py` | 139 | hand-written decimal parser, limits L20–L24 |
| `env/task.py` | 79 | task text `TASK_TEXT` L10, tool specs `TOOL_SPECS` L57 |
| `schemas.py` | 177 | strict Pydantic models: actions L123–L152, `Finding` L108, `FindingsSubmission` L117 |
| `evaluator/judge.py` | 84 | scoring: `submit` L65, `empty_answer` L74, `_invalid` L78 |
| `evaluator/matcher.py` | 120 | `eligibility` L53, one-to-one `match` L72 (augmenting paths L91) |
| `evaluator/reward.py` | 48 | `official_reward` L44 (`INSPECTION_COST` L25) |
| `evaluator/oracle.py` | 49 | evaluator-only oracle (`OraclePolicy` L36) |
| `evaluator/process_runner.py` | 148 | agent as child process (`run_episode_isolated` L91, scrubbed env L44) |
| `evaluator/evaluation.py` | 227 | closed evaluation suite (`run_evaluation` L90, `derive_seed` L45) |
| `agent_runtime.py` | 64 | agent-side JSON-lines loop (`serve` L28) |
| `analytics.py` | 48 | `TrajectoryLogger` (7 public fields) |
| `audit/*` | ~600 | independent stdlib-only reconciliation of public data |
| `generator/*` | ~1,500 | hidden history, postings, causal injection, presentation |
| `policies/*` | ~350 | random explorer, simple reconciliation, mark-everything, reference auditor |

Runtime dependency: Pydantic 2.14.4 only (`pyproject.toml`). No Gymnasium, NumPy or PyTorch.

## 3. Episode lifecycle

1. `reset(seed, config, *, options)` (L80): validates `EpisodeConfig`, calls `generate_episode`, builds a
   `Toolbox` from **public tables only** and a `Judge` holding the sealed truth, starts the wall clock.
   `seed=None` draws a random seed (Gymnasium convention) and is therefore not reproducible.
2. `step(action)` (L109): if finished → `episode_finished` error, reward 0, previous flags; if the wall clock
   exceeds 60 s → truncation; otherwise consumes one step, dispatches, and truncates at 100 steps.
3. `submit` (`_submit` L179): `inspection_steps = steps − 1`; the judge validates the findings
   (invalid → −1); the episode terminates. `_truncate` (L193) scores an empty answer with
   `inspection_steps = steps consumed`.
4. Visible reward (`_visible_reward` L199): the true terminal reward in `mode="train"`, 0.0 in `mode="eval"`.

## 4. What the agent observes

**Reset observation** (L97–L104): `task` (≈5 KB text with the four error definitions, evidence rules and
the reward formula), `manifest` (episode id, company name, profile label, base currency, period, offset,
record counts, rounding), `policy` (`policy.json`: accounting-date rule, FX rule, rounding, accounts,
posting rules, tolerance), `tools` (specs + examples), `remaining_steps` (100), `time_budget_seconds`.
**Reset info**: `env_version`, `schema_version`, `mode`.

**Step observation** (L126, L205): exactly `{ok, result, error{code, message}, remaining_steps}`.
`result` is the tool output only. **Step info**: `{}` except at truncation
(`{"truncation_reason", "final_answer": "empty"}`).

Findings for learning research:

* Observations are fully structured JSON, but **contain no history**: no previous actions, no previously
  returned records, no running summary. Memory is entirely the agent's responsibility.
* The environment is **deterministic** given (seed, config, secret, `ENV_VERSION`, action sequence);
  tested at step level (`tests/integration/test_env_contract.py::test_same_seed_config_actions_reproduce_everything`)
  and over whole trajectories (`tests/reproducibility/`). The only non-deterministic element is the
  wall-clock limit.
* The public dataset is **static** during an episode; only the step counter changes.

**Hidden from the agent**: the sealed truth (issues, amounts, allowed evidence sets), provenance
(seed, config, id map, clean snapshot, injections), the generation secret, the judge log and outcome, and
in eval mode the reward. Partially observable: every public record not yet retrieved.

## 5. The five tools

| tool | input (schema) | required / optional | output | errors (fixed codes) | step cost | information value | argument kinds |
|---|---|---|---|---|---|---|---|
| `list_records` | `table: str≤32`, `cursor: str≤128 \| null`, `limit: int` (`ListRecordsAction` L123) | `table` required; `cursor` default null; `limit` default 50 | `{table, records[≤limit], next_cursor, total}` | `unknown_table`, `invalid_limit` (outside 1–50), `invalid_cursor`, `invalid_action` (type errors) | 1 | up to 50 complete records per step; the only way to *discover* ids | categorical (4 tables); opaque token obtained from the previous page; integer, dominated by 50 |
| `get_record` | `table`, `id: str≤64` (L130) | both required | `{table, record}` | `unknown_table`, `unknown_id` | 1 | one record; ledger/invoice/payment ids must be discovered first; **FX keys are constructible** (`date:SRC:BASE`) from public dates and currencies, enabling targeted rate lookups without paging | categorical + pointer/string |
| `get_document` | `doc_id: str≤64` (L136) | required | `{doc_type, document}` | `unknown_document` | 1 | one invoice or payment; identical content to the `invoices`/`payments` rows | pointer |
| `calculator` | `expression: str≤512` (≤256 parsed, L20) | required | `{result}` exact decimal string | `invalid_expression`, `number_too_long`, `expression_too_long`, `expression_too_complex`, `division_by_zero`, `result_out_of_range` | 1 | **none about the hidden state** (pure function of its input); useful only to agents that cannot compute reliably themselves | grammar-constrained text |
| `submit` | `findings` validated as `FindingsSubmission` (L117) | `findings` required, no other keys | `{status: "submitted"}` or `invalid_submission` | malformed → −1 and termination | ends episode (not an inspection step) | — | structured set: ≤30 × {type (4), affected id set (pointers), amount (exact integer), currency, evidence id set ≤10 (pointers + constructible FX keys), explanation (ignored)} |

Invalid action names or non-object actions → `invalid_action`, one step consumed (L163–L177). Agent input
is never echoed in error messages.

**Action-space classification.** A union of five *parameterized* action families whose arguments are
categorical, ordinal, opaque tokens, pointers into a **history-dependent, episode-specific id
vocabulary**, free text (calculator), and a terminal **set-valued structured** action. It is not
Discrete, MultiDiscrete or Box; it is a parameterized/hierarchical action space with pointer arguments
and a combinatorial terminal action. Gymnasium does provide `Dict`, `Tuple`, `Sequence`, `Text`, `Graph`
and `OneOf` spaces (official docs, see references), but Stable-Baselines3 supports only Box, Discrete,
MultiDiscrete and MultiBinary **action** spaces (verified), so any off-the-shelf use requires an adapter.

## 6. Reward

* Computed only in `Judge._score` (L46) via `matcher.match` and `reward.official_reward` (L44); at submit or
  truncation. **No intermediate reward** (every exploration step returns 0.0, environment L131).
* In `mode="eval"` the agent never sees a non-zero reward (L199); diagnostics stay in the judge log.
* Sparse, terminal, set-valued, clipped: `clip(2·F1 − 1 − 0.002·k, −1, 1)`.
* Incentives (derived, then measured in §9):
  * **Premature empty submission** is attractive for weak agents: an empty answer at step 1 earns +1 on
    clean books and −1 otherwise, i.e. `2·p_clean − 1`.
  * **Clipping removes the step cost whenever F1 = 0** (`2·0 − 1 − 0.002k ≤ −1`), so failing agents get no
    signal about exploration cost.
  * A positive reward needs `F1 > 0.5 + 0.001k`; exploration is cheap (≤ 0.198 for 99 steps), so excessive
    exploration is mildly penalised while missing an issue is heavily penalised.

## 7. Baselines and their value as demonstrations

| baseline | actual behaviour (code) | usable as demonstration? |
|---|---|---|
| Random explorer (`policies/random_explorer.py` L54, L73) | 5–40 random actions incl. invalid ones, then 0–3 random findings from seen ids; stream keyed by policy seed + episode id | No (as expert). Useful as exploration noise and as negative examples |
| Simple reconciliation (`policies/simple_reconciliation.py` L55) | full scan, then naive rules (same supplier+total; Suspense present; date-as-written FX; UTC period check) | No (as expert): 225 FP vs 37 TP on the closed suite. Useful as *hard negatives* that expose red herrings |
| Mark everything (`policies/mark_everything.py` L25) | lists invoices+payments, submits 30 findings | No; attack/negative only |
| Reference auditor (`policies/reference_auditor.py` L34–L62) | pages every table in a **fixed order** (ledger, invoices, payments, fx) with limit 50, then runs `audit.reconcile` on what it saw and submits | Partly. Its *acquisition* actions are a deterministic function of table sizes — they contain **no decision content**. Its *submission* is a correct, observation-consistent label for the finding-construction sub-problem |
| Oracle (`evaluator/oracle.py` L36–L49) | submits the sealed truth at step 1, with no inspection | **No.** Its action is not a function of anything the agent can observe (the ids were never revealed); imitating it would teach fabrication of ids. It must stay evaluator-only |

## 8. Isolation and evaluation (verified)

* Closed evaluation runs each agent as a child process with a scrubbed environment (no `OPHANIM_*`), an
  empty working directory, and writes on a separate thread (`process_runner.py` L44, L62, L91).
* Generation is keyed by `HMAC(secret, seed)` in closed runs (`rng.py` L59); evaluator artefacts are written
  only after all agents finish (`evaluation.py`).
* **Relevant to future training code:** the in-process `OphanimEnv` exposes `evaluator_outcome()`,
  `evaluator_log()`, `evaluator_abort()` (L134–L160) and holds the judge (with the truth) in `_state`. Any
  learning code that holds an `OphanimEnv` object can reach evaluator data. This is acceptable for the
  existing open-mode tests but is a **leak path for any future training adapter** (addressed in
  `p6_agent_architecture.md`).

## 9. Measurements (read-only, executed during P6)

| quantity | measured value | how |
|---|---|---|
| Full-scan cost (pages of 50) | small 9–19 (median 14), **medium 12–22 (median 18)**, large 17–26 (median 22) | 60 seeds per size, default config |
| Share of full-scan pages spent on `fx` | small 57 %, medium 44 %, large 38 % | same |
| Ledger rows | small 149–222, medium 235–344, large 357–455 | same |
| Pointer vocabulary (row/doc/invoice/payment ids + FX keys) | medium 659–1,178 (median 948) | same |
| Observation volume of a full scan | reset 7.6 KB; full scan ≈ 150 KB of JSON (medium, seed 7) | serialized JSON bytes |
| Reference auditor steps on the closed suite | 15–26 (median 20.5) | 20 episodes, verify settings |
| **Silent policy** (submit `[]` immediately) on the closed suite | **mean −0.500** (clean +1.000, interacting −1.000, mixed −1.000) | 20 episodes, verify settings |
| Random explorer returns on the 15 erroneous closed episodes | **all exactly −1.0** (zero variance) | `runs/verify/report.json` |
| Issues per closed episode | 0 ×5, then 2–5, one with 12 | truth of the 20 episodes |
| Minimal evidence-set size | duplicate 3; fx 3; period 2; allocation 3–5 | allowed sets in truth |

"Verify settings" = `DEFAULT_SEED_BASE` with secret `ophanim-verify-local-secret`, as used by `ophanim verify`.

## 10. Discrepancies found

1. **Historical results.** −0.662 (simple reconciliation) and −0.805 (random explorer) come from
   `runs/official-evaluation/report.json`, which was produced with a **different hidden seed base**
   (hash `590f98b04d916134`) on Python 3.14.3 — not by any command in the P5 report. The P5/verify runs
   (seed base hash `0fb6941e81197c8d`) give −0.599 and −0.806. Both are correct for their episode sets; the
   gap is **episode-sampling variance across 20-episode suites**, which `docs/results.md` does not discuss.
2. `runs/verify/report.json` was regenerated by a later run on Python 3.14.3 and is numerically identical to
   the 3.11 report — evidence of cross-version evaluation determinism.
3. **Analytics gap.** The original P0 specification (§2.6) asked for records inspected, documents inspected
   and evidence validity. `EpisodeRecord` (`evaluator/runner.py` L17) has none of them; they are recoverable
   from public trajectories and judge verdicts but are not computed.
4. The original "investigation graph" (P0 §2.3) exists only implicitly (links inside the injector and the
   auditor); there is no graph module. `docs/design_note.md` states this.
5. Size ranges in `docs/data_model.md` (e.g. large 336–429 rows) predate the addition of three profiles;
   measured ranges are in §9 (large 357–455).
6. `OphanimEnv` follows Gymnasium semantics but defines no `action_space`/`observation_space` and no
   `render`/`close` (allowed by the case; relevant for library adapters).

## 11. Limitations that matter for learning research

* No observation history → every learned agent needs explicit memory.
* Pointer-valued arguments over an episode-specific vocabulary of ~10³ ids.
* Terminal set-valued action with exact numeric fields (±1 minor unit).
* Sparse, clipped reward with a flat −1 plateau for every policy that gets no true positive.
* A cheap, near-optimal information-acquisition strategy (full scan, 12–22 steps on medium) exists, so the
  official reward leaves little headroom for "smarter investigation" (≤ ≈0.044 on medium).
* The in-process environment object exposes evaluator data; training code must not hold it.
* The 60 s wall-clock budget constrains slow (e.g. LLM) agents; it is enforced in the official setting.
