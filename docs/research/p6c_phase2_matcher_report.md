# P6-C Phase 2 — Exact matcher and lookup compliance: report

Branch `feat/p6-c-compliance` (Phase 1 committed as `6dadbed`); nothing committed in this phase. Scope:
the matcher and lookup conventions of the official check definitions (`fintech-checks.txt`, section
"Точные соглашения matcher"), plus tolerance and tie-break. The episode generator logic, refunds and
partial allocations are **out of scope** and still open (§8).

## 1. Baseline (re-run before editing)

* `git status` clean, branch `feat/p6-c-compliance`, `git log`: `6dadbed p6-c p1`, `f16b130`, `1a7ac33`.
* Tests: **525 passed** on Python 3.11.15, **525 passed** on Python 3.14.3.

## 2. Official requirements addressed

| requirement (official) | old behaviour | new behaviour |
|---|---|---|
| ids compared exactly (matcher) | `strip().upper()` on affected/evidence ids and on the evidence universe | exact strings; sets only for order/repeats |
| ids exact (tool lookups; C11/C12) | case- and whitespace-insensitive index (`_norm`) | exact dict lookups; a case/space variant of a real id → `unknown_id` / `unknown_document`, step consumed |
| `episode_id` | normalised comparison | exact comparison (still a structure error when different, O2) |
| type exact, unknown string → FP | `Literal` type → unknown/cased type = structure error (−1) | any string; non-matching type → FP |
| currency exact, no ISO requirement | `^[A-Z]{3}$` → `kzt` / ` KZT` = structure error (−1) | any string, exact comparison → FP (M06) |
| amount = JSON integer | strict int **and** `0 ≤ amount ≤ 10^15` → negative = −1 | strict int only (bool, string, float, null rejected); negative/huge ints valid → FP |
| affected ids: set of exact ids, no extra limits | 1–20 ids, ids ≤ 64 chars → else −1 | any list of strings (non-strings = type error) |
| evidence: complete allowed set; unknown/inaccessible → FP | universe = row_id, doc_id, FX key | universe = every id a tool returns: row_id, doc_id, **invoice_id, payment_id**, FX key; `entity_id` (no tool returns it) stays inaccessible |
| limits before normalisation; 30 / 10 / 1000 code points | already correct | unchanged, now tested with 1–4-byte characters |
| τ = 0 by default; explicit, non-negative, never inferred | τ = 1 for every generated episode; no validation | `TOLERANCE_MINOR = 0`; `TruthFile.tolerance_minor` defaults to 0 and must be a non-negative int; the matcher rejects invalid τ |
| maximum matching + official tie-break | maximum matching, augmenting-path order (M11 → F0→B, F1→A) | maximum matching, then issue-by-issue lexicographic tie-break (M11 → A→F0, B→F1) |

Unchanged by design: the reward formula `clip(2·F1 − 1 − 0.002·k, −1, 1)` and its fractions-based
evaluation; inspection-step accounting; O1 (unknown extra fields → structure error) and O2
(`episode_id` mismatch → structure error), as proposed in the compliance audit.

## 3. Files changed

| file | change |
|---|---|
| `src/ophanim/schemas.py` | `Finding`: `type`/`currency` plain strings; `affected_ids`/`evidence_ids` lists of strings; amount strict int without bounds; limits 30/10/1000 kept; `TruthFile.tolerance_minor = Field(0, ge=0)`; removed `MAX_AFFECTED_IDS` |
| `src/ophanim/evaluator/matcher.py` | exact eligibility; `check_tolerance`; maximum matching + official tie-break; `normalize_id` removed |
| `src/ophanim/evaluator/judge.py` | exact `episode_id` in the shared `validate_submission` |
| `src/ophanim/env/tools.py` | exact lookups (`_norm` removed) |
| `src/ophanim/generator/episode.py` | `PublicEpisode.evidence_universe` adds `invoice_id`, `payment_id` (scoring helper; generation output unchanged) |
| `src/ophanim/generator/presentation.py` | `TOLERANCE_MINOR = 0` (written into `policy.json`/`truth.json`) |
| `src/ophanim/generator/injectors.py` | comment only |
| `src/ophanim/env/task.py` | task text: exact ids/types/currency; structure vs value errors |
| `src/ophanim/version.py` | `ENV_VERSION` 0.1.0 → **0.2.0** (same actions can now earn different rewards) |
| `data/**` | regenerated with `ophanim build-data` (see §6) |
| `docs/reward_design.md`, `docs/design_note.md` | published matcher rules updated |
| `tests/unit/test_matcher_exact.py` (new, 69) | ids, currency/type, amount, evidence, limits, structure, tolerance, matching, brute-force cross-check |
| `tests/integration/test_exact_semantics.py` (new, 22) | C11/C12 through the adapter, M01–M12 on episode files, structure vs semantics through `score_episode`, evidence universe, tolerance on files |
| `tests/adversarial/test_reward_attacks.py`, `tests/integration/test_env_contract.py`, `tests/unit/test_matcher_reward.py` | 10 assertions that encoded the old semantics updated (see §5) |
| `docs/research/evidence/p6c_phase2_official_checks.out.txt` (new) | the unmodified P6 harness re-run on Phase 2 code |

## 4. Matching algorithm and tie-break

1. Build edges: finding *i* — issue *j* iff every eligibility condition holds (exact).
2. K = size of a maximum matching (augmenting paths over all findings and issues).
3. Sort issues by `issue_id` (Python string order = Unicode code points). For each issue in that order,
   take the lowest finding index *i* such that the issues already fixed + (issue, *i*) + a maximum
   matching of the remaining issues on the remaining findings still reaches K. If none exists, the issue
   stays unmatched.
4. This produces the lexicographically smallest sorted sequence of (issue_id, finding index) pairs
   among all maximum matchings. TP = K always; FP = findings − K; FN = issues − K.

Correctness evidence: `test_matching_equals_exhaustive_search_on_random_graphs` compares K and the exact
pair sequence with brute-force enumeration on 300 random graphs (≤ 5 findings × ≤ 4 issues): all equal.
M10 (greedy would lose a TP) and M11 (tie-break) pass on synthetic issues and on episode files.

## 5. Structural versus semantic decisions

* **Structural (−1, all metrics null):** missing field; wrong JSON type (bool/string/float/null amount,
  numeric id, non-string type/currency/explanation, non-list ids); unknown field (O1); wrong
  `episode_id` (O2); 31 findings; 11 evidence ids (raw, even if repeated); 1001 code points.
* **Semantic (normal FP/FN):** unknown or differently-cased type; currency differing in case or space;
  wrong, negative or huge amount; empty, long, unknown or case-variant ids; missing, incomplete or
  inaccessible evidence.
* Updated old tests (intent kept): the ±1 tolerance test became `..._is_exactly_zero_by_default`; four
  former "structure error" cases (negative amount, lowercase currency, unknown type, empty affected ids)
  moved to `test_semantic_mismatch_is_a_false_positive_not_a_structure_error` (with three more variants);
  the env contract test now asserts that case/space variants are unknown ids; the matcher unit test now
  asserts exactness.

## 6. Data regeneration (required, explained)

`tolerance_minor` is written into every `policy.json` and `truth.json`, and `env_version` into every
manifest and provenance. Keeping τ = 1 in published truth would contradict the matcher default, and
`ophanim verify` requires the published data to regenerate byte-identically. The data was therefore
regenerated with the established command `ophanim build-data`. Seeds and configs are unchanged, so ids
and content are unchanged. `git diff` shows exactly:

* 40 `tolerance_minor` lines (1 → 0) in the 20 `policy.json` and 20 `truth.json` files;
* 40 `env_version` lines in the 20 manifests and 20 provenance files;
* the 40 reset observations in `trajectories.jsonl` (version and task text), still 698 lines.

The two `index.json` files were rewritten with CRLF by `build-data` on Windows. Their content was
unchanged, so they were restored. Minor pre-existing tooling issue, see §8.

## 7. Results (executed)

| check | result |
|---|---|
| full suite, Python 3.11.15 | **619 passed** (525 baseline − 4 moved + 7 semantic cases + 69 unit + 22 integration) |
| full suite, Python 3.14.3 | **619 passed** |
| published Block-3 tests 1–20 | 20/20 (in-memory and through `score_episode` on episode files) |
| M01–M12 | all pass, including M06 (FP), M11 pairs (A→F0, B→F1), M10 (F1→A, F0→B) |
| C11 / C12 | case, leading/trailing whitespace, newline and numeric variants → bounded errors, step consumed |
| P6 harness (unmodified) | before 34 PASS / 10 FAIL → after **44 PASS / 0 FAIL** |
| existing adapter tests | 49/49 still pass |
| `ophanim verify` | PASS: 20/20 episodes verified, 20/20 byte-identical regeneration, 0 trajectory leaks; closed evaluation 20/20 data, 20/20 metamorphic, 20/20 reproducibility; baseline returns unchanged (−0.8065, −0.5987, −1.0, 0.961, 1.0) |
| Docker offline, Linux, Python 3.11.15, `--network none --cpus 2 --memory 4g` | full `ophanim verify` PASS (**619 passed** inside the container; data 20/20 verified and regenerated identically; 0 leaks; 20/20/20 closed evaluation); `judge_adapter.py --smoke` ok |

## 8. Remaining gaps and notes

* **Generator (Phase 3):** refund red herring (D03); requestable partial vs missing allocation (D09–D11);
  documented guarantees for split payments and FX-boundary documents (D02, D05); provenance format
  documentation (DC1, T1).
* **Interpretations kept:** O1 (unknown extra fields → −1) and O2 (`episode_id` mismatch → −1). Neither
  is used by any published test. Both are documented in the compliance audit.
* **Evidence universe interpretation:** "accessible" = returned by a tool. `entity_id` values appear
  inside records but no tool retrieves an entity, so citing one makes a finding unmatched.
* **Tooling:** `build-data` writes `index.json` with platform line endings (CRLF on Windows). It is
  harmless because `.gitattributes` normalises to LF, but it creates working-tree noise on Windows. A
  one-line fix (`newline="\n"`) is proposed for a later phase.
* This phase does not claim full compliance of Blocks 1–4. Block 2 still depends on the generator gaps
  above.
