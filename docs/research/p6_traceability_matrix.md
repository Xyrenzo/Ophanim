# Traceability matrix — official Genesis FinTech check definitions (published 2026-11-20)

Source of requirements: `fintech-checks.txt` ("Genesis FinTech: определения проверок"). Audited against the
working tree on 2026-11-21. **No status is based on documentation alone.**

**Status values:**
* **VERIFIED** — implemented and confirmed by execution: an existing test, or the P6 harness
  `docs/research/evidence/p6_official_checks.py` with output in `p6_official_checks.out.txt`.
* **PARTIAL** — the logic exists but is incomplete, or is not reachable through the official interface.
* **MISSING** — not implemented.
* **NON-COMPLIANT** — implemented, but contradicts the definition.

Two status columns are given because the jury runs everything through `judge_adapter.py`:

* **Core** — whether the behaviour exists in our code.
* **Adapter** — whether the jury can reach it through the official interface. The adapter does not exist,
  so every requirement that needs it is MISSING today.

**Priority:**
* **P0** — blocking: the jury cannot run the check at all.
* **P1** — a specific published test fails.
* **P2** — alignment or robustness.
* **P3** — documentation.

## A. Adapter interface (§ "Единый способ подключения")

| ID | official requirement | implementation | status | evidence | required change | prio |
|---|---|---|---|---|---|---|
| A1 | `judge_adapter.py` in the container | — | MISSING | file absent | create `judge_adapter.py` (thin wrapper over existing modules) | P0 |
| A2 | `generate_episode(seed, config, output_dir)` writes manifest, ledger, invoices, payments, fx, policy + truth, provenance | `generator/episode.py` L170 (`generate_episode`), `GeneratedEpisode.write` L95 (layout `public/`, `evaluator/`) | PARTIAL | writer exists, signature differs | wrapper with the official signature; document the directory layout | P0 |
| A3 | `make_env()` returns an object with `reset`/`step` | `OphanimEnv` (`env/environment.py` L66) | PARTIAL | class exists | factory returning an adapter env | P0 |
| A4 | `reset(seed, config)` with `{"mode":"closed","episode_dir":…,"team_config":…}` **loads that episode as-is** (no regeneration, no id change); repeated reset restarts it | `reset` L80 generates only | MISSING | harness: config with `mode/episode_dir/team_config` → `ValidationError` | episode loader from `episode_dir` (reuse `audit/dataset.py` `PublicDataset.from_directory`, which already reads our files); serve tables **in file order** | P0 |
| A5 | `mode="train"` without `episode_dir` → team generator with `seed` + `team_config` | `reset(seed, config)` | PARTIAL | works with native config | map `team_config` → `EpisodeConfig`; `mode` → env mode | P0 |
| A6 | `step({"name": …, "args": {…}})`; names `list_records`, `get_record`, `get_document`, `calculator`, `submit`; submit args `{"findings": …}` | native flat `{"action": …, …}` (`schemas.py` L123–L152) | MISSING | harness: envelope → not accepted | translate envelope → native action; unknown names must still reach `step` (so they consume a step) | P0 |
| A7 | first observation `{task, manifest, policy, remaining_steps: 100}`; then `{result, error, remaining_steps}` | native adds `tools`, `time_budget_seconds`; step obs adds `ok` | PARTIAL | harness: first-observation keys | adapter emits the documented shapes | P0 |
| A8 | `list_records` → `{records, next_cursor}`; `get_record`/`get_document` → the object itself; `calculator` → decimal string | native wraps: `{table, records, next_cursor, total}`, `{table, record}`, `{doc_type, document}`, `{result}` | PARTIAL | harness C05/C07/C09 lines | adapter unwraps results | P0 |
| A9 | submit returns only `{"accepted": true}` or a bounded structure error; no correctness | native `{"status": "submitted"}` / `invalid_submission` | PARTIAL | `env/environment.py` L179–L191 | adapter maps result | P0 |
| A10 | `score_episode(episode_dir, findings, inspection_steps)` → `{tp, fp, fn, precision, recall, f1, return}`; invalid → `return=-1`, others `null`, error logged | `Judge` (`evaluator/judge.py`) works on in-memory objects only | MISSING (logic VERIFIED) | harness Block 3: 20/20 with in-memory truth | load `evaluator/truth.json` + public files from `episode_dir`; call the existing judge; map output | P0 |
| A11 | closed mode: policy reward 0 incl. termination; true reward kept separately | eval mode (`_visible_reward` L199) | VERIFIED (core) | `test_eval_mode_withholds_reward_and_diagnostics` | map `mode:"closed"` → `mode="eval"` | P0 |
| A12 | policy in a separate restricted process; no evaluator import; no access to `episode_dir`; hiding fields in a Python object is not isolation | jury runs the policy process; our env lives in the jury process | PARTIAL | `tests/security/*`, AST tests | in closed mode the adapter env should **not load truth at all** (scoring only via `score_episode`) | P1 |
| A13 | canonical table names `ledger`, `invoices`, `payments`, `fx` | `env/tools.py` L19 | VERIFIED | code | — | — |
| A14 | README documents adapter code, result schema, mapping of the four error types, working directory and launch command | README has none of this | MISSING | README | add an "Official judge adapter" section | P0 |

## B. Block 1 — contract tests C01–C20 (25 points)

| ID | requirement | core | adapter | evidence | required change | prio |
|---|---|---|---|---|---|---|
| C01 | reset on C → (observation, info), JSON | VERIFIED | MISSING | `test_reset_returns_observation_and_info` | A3/A4 | P0 |
| C02 | first obs: task, manifest, short policy, budget; no seed/truth | VERIFIED | MISSING | harness keys; `test_observations_never_include_seed_or_config` | A7 | P0 |
| C03 | manifest fields; numbers match the data | VERIFIED | MISSING | verifier format checks; `test_public_formats` | A4 (counts stay correct after jury permutation) | P0 |
| C04 | list_records step → 5-tuple, bool flags, JSON | VERIFIED | MISSING | `test_step_returns_five_tuple_of_json_values` | A6 | P0 |
| C05 | L (≥ 101 rows), limit 50, cursor walk: no gaps/repeats | VERIFIED | MISSING | `test_pagination_covers_every_row_once_with_max_50` (ledger ≥ 149 rows always) | A8 | P0 |
| C06 | same cursor twice → same records, same order | VERIFIED | MISSING | `test_cursors_are_stable_and_validated` | A8 | P0 |
| C07 | get_record R1 → that record | VERIFIED | MISSING | harness (shape `{table, record}`) | A8 unwrap | P0 |
| C08 | get_document D1 → that document | VERIFIED | MISSING | `test_get_record_and_get_document` | A8 unwrap | P0 |
| C09 | calculator `0.1+0.2` → decimal 0.3 | VERIFIED | MISSING | harness `'0.3'`; `test_arithmetic` | A8 | P0 |
| C10 | calculator outside grammar → controlled error, nothing executed | VERIFIED | MISSING | `test_rejects_anything_but_arithmetic`; AST scan (no eval/exec) | — | P0 |
| C11 | get_record U (absent string) → bounded error, step used | **NON-COMPLIANT** | MISSING | harness: a case-variant of an existing id returns a record | **exact id lookup** in `env/tools.py` (`_norm` L51 upper-cases and strips) | P1 |
| C12 | get_document U → bounded error, nothing disclosed | **NON-COMPLIANT** | MISSING | same mechanism | exact `doc_id` lookup | P1 |
| C13 | unknown action name → bounded error, step used | VERIFIED | MISSING | `test_invalid_actions_are_bounded_and_consume_a_step` | A6 must pass unknown names through | P0 |
| C14 | each request (valid or not) costs one step | VERIFIED | MISSING | same test (`remaining_steps == 99`) | — | P0 |
| C15 | submit → terminated; later actions change nothing | VERIFIED | MISSING | `test_repeated_submission_cannot_change_the_reward` | A9 | P0 |
| C16 | 99 inspection actions + submit as action 100 → accepted, terminated | VERIFIED | MISSING | `test_submit_on_the_last_step_terminates_not_truncates` | — | P0 |
| C17 | 100 inspection actions → truncated, empty findings | VERIFIED | MISSING | `test_step_limit_truncates_with_empty_answer` | — | P0 |
| C18 | 60 s from reset incl. policy time → truncated, empty findings | VERIFIED (injected clock) | MISSING | `test_time_limit_truncates`, `test_timeouts_truncate_with_empty_answer` | adapter uses the real monotonic clock; loading counts as fixture preparation | P0 |
| C19 | closed: reward 0 at every step incl. end; no diagnostics in info/final answer | VERIFIED | MISSING | eval-mode tests; `test_agent_process_receives_no_hidden_data_and_no_secret` | A11 | P0 |
| C20 | no truth/provenance/seed/answers anywhere the policy sees; no shell/SQL/FS/network | VERIFIED | MISSING | leak scans, process-isolation tests, calculator grammar | A12 (no truth in the closed-mode env object) | P1 |

## C. Block 2 — closed episodes D01–D20 (25 points)

| ID | scenario | core | adapter | evidence | required change | prio |
|---|---|---|---|---|---|---|
| D01 | clean, ordinary | VERIFIED | MISSING (A2) | clean configs verify, truth empty | A2 | P0 |
| D02 | clean, correctly split payment | PARTIAL | MISSING | split payment present in 60/60 default episodes (measured), but not guaranteed by a documented setting | document and test the guarantee at `distractors ≥ normal` | P1 |
| D03 | clean, **correct refund** | **MISSING** | MISSING | no refund concept anywhere in `src/` (grep: 0 files) | implement a legitimate refund red herring + auditor support (proposal: supplier returns an unidentified payment: `Dr Bank / Cr Suspense`, documented `direction` field) | P1 |
| D04 | clean, legitimate repeated amounts | VERIFIED | MISSING | repeat order 60/60, recurring 51/60 (measured) | — | P0 (A2) |
| D05 | clean, correct FX/period boundary | PARTIAL | MISSING | boundary-UTC document 60/60 (measured); FX-boundary document not guaranteed | document/guarantee a foreign-currency boundary document | P2 |
| D06–D08 | duplicate invoice (varied); repeated amounts not duplicates | VERIFIED | MISSING | generator + verifier tests; red herrings | — | P0 (A2) |
| D09–D11 | allocation; ≥ 1 **missing** and ≥ 1 **partial** | **PARTIAL** | MISSING | one requested allocation error → *missing* in 40/40 seeds (measured); partial only inside scenario S1 | documented setting to request partial vs missing allocation (multi-line carrier, as for S1) | P1 |
| D12–D13 | wrong FX date/rate per policy | VERIFIED | MISSING | `test_fx_errors_recompute_from_the_cited_rate` | — | P0 (A2) |
| D14–D15 | period error; timezone per manifest/policy | VERIFIED | MISSING | `test_period_attribution_is_a_utc_versus_local_date_error` | — | P0 (A2) |
| D16–D18 | first interaction scenario, varied parameters | VERIFIED (S1) | MISSING | `test_s1_partial_foreign_payment_at_boundary` (15 seeds) | — | P0 (A2) |
| D19–D20 | second interaction scenario | VERIFIED (S2) | MISSING | `test_s2_wrong_rate_invoice_with_unapplied_payment_line` | — | P0 (A2) |
| DC1 | clean before injection; provenance documented and sufficient | VERIFIED / PARTIAL docs | — | verifier pre-mutation check (`provenance.pre_mutation.tables`) | document the provenance format field by field | P2 |
| DC2 | injection = declared discrepancy, checkable independently of our matcher | VERIFIED | — | independent auditor (`audit/`, stdlib only), 20/20 closed + 108 test episodes | — | — |
| DC3 | truth type/ids/amount/currency match the change | VERIFIED | — | verifier amount/id comparison | — | — |
| DC4 | a complete evidence set is reachable through the tools | VERIFIED | — | evidence-sufficiency check; reference auditor solves through tools | — | — |
| DC5 | §03 formats (offsets, minor units, decimal FX strings, explicit nulls) | VERIFIED | — | `audit/formats.py`; `test_public_formats` | — | — |
| DC6 | no contradictory/unsolvable data | VERIFIED | — | zero anomalies in reconciliation | — | — |

## D. Block 3 — matcher and reward tests 1–20 (25 points) and examples M01–M12

Logic was executed against the existing judge with in-memory fixtures built from real episode ids (τ = 0
where the definitions fix it). Through the official interface every row is **MISSING** until A10 exists.

| ID | expectation | core result | required change | prio |
|---|---|---|---|---|
| 1–17 | TP/FP/FN and reward values (incl. 47/150, −871/1050, −0.02, 1/0.90/0.80) | **VERIFIED 17/17** | A10 | P0 |
| 18–20 | 31 findings / 11 evidence ids / 1001-char explanation → structure error, −1 | **VERIFIED 3/3** | A10 | P0 |
| M01–M05 | multiset ids, extra ids, extra/unknown evidence, raw-limit before dedup | VERIFIED 5/5 | — | — |
| M06 | currency differing by case or space → **FP** (not a structure error) | **NON-COMPLIANT** | drop the `^[A-Z]{3}$` pattern; compare exactly | P1 |
| M07–M09 | τ boundary; string/bool amount → structure error | VERIFIED | — | — |
| M10 | maximum matching (F1→A, F0→B) | VERIFIED | — | — |
| M11 | tie-break A→F0, B→F1 | **NON-COMPLIANT (pairs only)**: got F0→B, F1→A; TP/FP/FN/reward identical | lexicographic tie-break over (issue_id, finding index) | P2 |
| M12 | duplicates stay separate (TP=1, FP=1) | VERIFIED | — | — |

### Matcher conventions (§ "Точные соглашения matcher")

| ID | rule | status | evidence | required change | prio |
|---|---|---|---|---|---|
| N1 | ids compared **exactly** (case and whitespace significant) | **NON-COMPLIANT** | harness: lowercase and space-padded ids still matched | remove `normalize_id` upper/strip (`evaluator/matcher.py` L30) | P1 |
| N2 | `affected_ids` = exact set; no extra limits | **NON-COMPLIANT** | empty list and 21 ids → −1 (should be FP) | remove `min_length=1`/`max_length=20` (`schemas.py` L110) | P1 |
| N3 | evidence set after raw limit; complete inclusion; unknown/inaccessible id → FP | PARTIAL | universe excludes `invoice_id`/`payment_id`, although `get_record` can retrieve them | add retrievable ids to the evidence universe (`generator/episode.py` L64) | P1 |
| N4 | type exact; unknown string → not matched (FP) | **NON-COMPLIANT** | `"fraud"` → −1 (`Literal` type) | accept any string; unknown → FP | P1 |
| N5 | currency exact; no ISO requirement | **NON-COMPLIANT** | M06 | see M06 | P1 |
| N6 | amount: JSON integer, not bool/string/float | VERIFIED (types) / **NON-COMPLIANT** (bounds) | negative integer → −1 (`ge=0`, `le=10**15`) | remove numeric bounds; any int structurally valid | P1 |
| N7 | limits checked before normalisation; 30 / 10 / 1000 code points | VERIFIED | tests 18–20, M05, 1000 non-ASCII chars accepted | — | — |
| N8 | wrong values → FP; only type errors/missing fields/limits → structure error | PARTIAL | ids > 64 chars → −1 (`IdStr max_length=64`) | remove id length bound | P1 |
| N9 | default τ = 0; any τ fixed in advance per type, documented | **NON-COMPLIANT (default)** | `TOLERANCE_MINOR = 1` (`generator/presentation.py`) | set τ = 0 (our amounts are exact by the published rounding rule); regenerate data; bump `ENV_VERSION` | P1 |
| N10 | maximum-cardinality matching | VERIFIED | M10 | — | — |
| N11 | deterministic lexicographic tie-break | NON-COMPLIANT (pairs only) | M11 | see M11 | P2 |
| N12 | numeric results within 1e-9 | VERIFIED | exact fractions → float | — | — |

## E. Block 4 — paired checks P01–P20 (15 points)

The jury transforms **files** in a copy of the episode directory and loads both copies with `reset`. Our
own metamorphic machinery (`evaluator/metamorphic.py`) is evidence that the logic is invariant, but it is
not the mechanism the jury uses.

| ID | requirement | core | adapter | evidence | required change | prio |
|---|---|---|---|---|---|---|
| P01–P05 | permuted record order (D01–D05) | VERIFIED (own transforms) | MISSING | 60 metamorphic tests; closed-suite 20/20 | A4 loader must serve **file order** | P0 |
| P06–P10 | bijective id replacement (D06–D10) | VERIFIED (own transforms) | MISSING | same | A4 + N1 (exact ids) + A10 | P0 |
| P11–P20 | order + ids (D11–D20) | VERIFIED (own transforms) | MISSING | same | as above | P0 |
| PC1 | exact replay of records, transitions, rewards; reset keeps no state | VERIFIED | MISSING | replay tests, reset isolation | loader must be deterministic | P0 |
| PC2 | oracle with remapped ids correct after inverse mapping | VERIFIED (own) | MISSING | `check_pair` oracle reward 1.0 | A10 on transformed truth | P0 |
| PC3 | TP/FP/FN/P/R/F1/reward identical at equal inspection steps | VERIFIED (own) | MISSING | `check_pair` | — | P0 |
| PC4 | no new leak; evidence still reachable | VERIFIED (own) | MISSING | leak tests | — | P0 |
| T1 | every id field and reference documented for consistent replacement (row_id, doc_id, invoice_id, payment_id, entity_id, affected_ids, evidence_ids **and our extras**) | PARTIAL | — | `invoice_refs[].invoice_id`, provenance `id_map` values and `pre_mutation.tables` are not listed as id-bearing | document the complete id-field list per file | P1 |
| T2 | FX keys are natural keys, not surrogate ids | VERIFIED | — | `date:SRC:BASE` derived from content | state it in the README | P3 |
| T3 | `line_items` order is not treated as harmless | VERIFIED | — | nothing depends on it | — | — |

## F. Boundary conventions and engineering

| ID | requirement | status | evidence | required change | prio |
|---|---|---|---|---|---|
| B1 | submit counts toward 100 actions, not toward inspection_steps; all earlier steps (incl. errors) count | VERIFIED | `_submit` L181; C16/C17 tests | — | — |
| B2 | 60 s from reset to completion, incl. policy | VERIFIED (core) | time-limit tests | adapter: real clock | P0 |
| B3 | JSON compared by value; list order significant except sets | VERIFIED | determinism tests | — | — |
| E1 | one documented command | VERIFIED (`ophanim verify`, Docker) / MISSING (adapter run command) | Docker run PASS | README: adapter working dir and command | P0 |
| E2 | versions of code, dependencies and configs | VERIFIED | `requirements.lock`, `ENV_VERSION`, suite versions | — | — |
| E3 | trajectories.jsonl with the §09 fields, no truth in observations | VERIFIED | `data/trajectories.jsonl`, 0 leaks | — | — |
| E4 | measured failure, cause, re-check | VERIFIED | `docs/results.md` (4 measured failures fixed and re-tested) | — | — |
| E5 | honest limitations tied to scenarios | VERIFIED | `docs/design_note.md`, `docs/results.md` | add the adapter/compliance limitations once fixed | P3 |

## Summary

| block | points | jury-runnable today | after P0 (adapter) | after P0 + P1 |
|---|---:|---|---|---|
| 1 Contract C01–C20 | 25 | 0/20 (no adapter) | 18/20 expected (C11, C12 fail) | 20/20 expected |
| 2 Data D01–D20 | 25 | 0/20 (no `generate_episode` entry point) | 17–18/20 expected (D03 refund missing; D09–D11 partial case not requestable) | 20/20 expected |
| 3 Matcher/reward 1–20 | 25 | 0/20 (no `score_episode`) | 20/20 expected (logic verified 20/20) | 20/20 |
| 4 Pairs P01–P20 | 15 | 0/20 (no `episode_dir` loading) | 20/20 expected if jury ids differ only as tokens; exact-id fix (N1) removes case-collision risk | 20/20 expected |

"Expected" values are predictions from the verified core behaviour, not results of an official run.

## Phase status updates

The tables above record the **P6 audit baseline (2026-11-21)** and are kept unchanged as history.

### P6-C Phase 1 — jury adapter (commit `6dadbed`)

A1–A14 implemented (`judge_adapter.py`, `src/ophanim/adapter.py`): `generate_episode`, `make_env`,
closed loading from `episode_dir` without truth, the `{"name","args"}` envelope, the official observation
and result shapes, and `score_episode`. The "Adapter" column of rows C01–C20, D01–D20, tests 1–20 and
P01–P20 is now reachable. Report: `p6c_phase1_adapter_report.md`.

### P6-C Phase 2 — exact matcher and lookups (working tree, ENV_VERSION 0.2.0)

| ID | new status | evidence |
|---|---|---|
| C11, C12 | VERIFIED | `tests/integration/test_exact_semantics.py::test_c11_c12_variants_of_real_ids_are_unknown` |
| M06 | VERIFIED (FP) | `test_published_examples_m01_to_m09_and_m12` |
| M11 / N11 | VERIFIED (A→F0, B→F1) | `test_published_examples_m10_m11_through_the_episode_files`; exhaustive cross-check on 300 random graphs |
| N1 exact ids | VERIFIED | `tests/unit/test_matcher_exact.py` (id variants, numeric ids) |
| N2 affected ids without extra limits | VERIFIED | `test_semantic_mismatches_are_structurally_valid` |
| N3 evidence = tool-accessible ids | VERIFIED | `test_tool_accessible_ids_are_valid_extra_evidence_entity_ids_are_not` |
| N4 type exact, unknown → FP | VERIFIED | `test_type_is_compared_exactly_without_aliases` |
| N5 currency exact | VERIFIED | `test_currency_is_compared_exactly_and_never_a_structure_error` |
| N6 amount = JSON int, no bounds | VERIFIED | `test_amount_must_be_a_json_integer`, `test_amount_semantics` |
| N8 structure vs semantics | VERIFIED | `test_structure_errors_return_minus_one_and_nulls`, `test_semantic_mismatch_counts_as_fp_fn` |
| N9 τ = 0 default, validated | VERIFIED | `test_default_tolerance_is_zero`, `test_invalid_tolerance_configuration_is_rejected`, `test_generated_episodes_use_exact_amounts_by_default` |
| Block 3 test 8 / M07 with our own default | VERIFIED | same |

Unmodified P6 harness: 34 PASS / 10 FAIL → 44 PASS / 0 FAIL
(`evidence/p6c_phase2_official_checks.out.txt`). Still open (Phase 3): D02, D03, D05, D09–D11, DC1, T1.
Report: `p6c_phase2_matcher_report.md`.
