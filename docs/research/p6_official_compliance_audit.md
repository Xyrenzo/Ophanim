# P6 — Official compliance audit (Genesis FinTech check definitions, 2026-11-20)

The official check definitions (`fintech-checks.txt`, "Genesis FinTech: определения проверок") are
binding. They keep the case requirements and fix three things the case left open: **how** the jury
connects (a thin `judge_adapter.py`), **which** episodes and tests make up the four blocks, and the
**exact matcher conventions**. This audit compares them with the working tree. The full row-by-row
mapping is in `p6_traceability_matrix.md`; the evidence script and its output are in
`docs/research/evidence/`.

## 1. Method

* Read the definitions completely (adapter, isolation boundary, paired-check transport, fixtures C/E/L/U,
  Blocks 1–4, engineering anchors, matcher conventions, M01–M12).
* Executed the 20 Block-3 tests and the M01–M12 examples against the existing judge, using in-memory
  fixtures built from real episode ids (`p6_official_checks.py`). Result file:
  `p6_official_checks.out.txt` (34 PASS, 10 FAIL lines).
* Probed the environment for the C-test behaviours, the action envelope and `episode_dir` loading.
* Measured generator properties the D-matrix depends on (red-herring frequencies over 60 episodes;
  allocation sub-kind over 40 seeds).

## 2. Findings

### 2.1 Blocking (P0): the official integration does not exist

The jury calls `generate_episode(seed, config, output_dir)`, `make_env()`,
`env.reset(seed, {"mode", "episode_dir", "team_config"})`, `env.step({"name", "args"})` and
`score_episode(episode_dir, findings, inspection_steps)`. None of these entry points exists:

* the environment can only **generate** an episode from a seed. It cannot **load** an episode
  directory, which is how the jury supplies its own fixtures and the transformed copies for the paired
  checks;
* the action envelope `{"name", "args"}` is not accepted (native format: `{"action": …, …}`);
* there is no file-based scoring entry point; the judge works only on in-memory objects;
* the README does not document an adapter, its result schema, working directory or launch command.

Consequence: today the jury cannot execute Block 1, Block 3 or Block 4, nor generate the Block-2 episodes
through the agreed interface, **even though the underlying behaviour is almost entirely correct**.

### 2.2 The core is largely compliant (verified)

* **Block 3 logic: 20/20.** Every expected TP/FP/FN and reward value matched exactly, including
  47/150 ≈ 0.3133, −871/1050 ≈ −0.8295 and −0.02, plus the structure errors for 31 findings, 11 evidence
  ids and a 1001-character explanation.
* **M01–M05, M07–M10, M12:** sets of affected ids and evidence ids, raw limits before deduplication,
  τ = 0 and τ = 1 boundaries, string/bool amounts, maximum-cardinality matching, and duplicate findings
  kept separate.
* **Contract behaviour:** 18 of the 20 C-tests pass at core level; C11 and C12 are the exceptions. Already
  covered by tests: pagination, stable cursors, the safe calculator, the 99+submit and 100-action
  boundaries, the time limit, closed-mode zero rewards, and the leak scans.
* **Block 2:** all four error types and both interaction scenarios are independently verified (clean
  before mutation, exactly the declared discrepancy after, sufficient evidence, §03 formats).

### 2.3 Non-compliant matcher and tool conventions (P1)

| rule | current behaviour | definition |
|---|---|---|
| ids | upper-cased and stripped before comparison and lookup | exact, case- and whitespace-sensitive |
| unknown `type` string | structure error (−1) | not matchable → FP |
| currency | must match `^[A-Z]{3}$`, else −1 | exact comparison; a case/space difference is an FP (M06) |
| `affected_ids` length, id length, amount sign and bounds | own limits → −1 | only type errors, missing fields and the three published limits are structure errors |
| evidence universe | row_id, doc_id, FX key | every id accessible through the tools (also invoice_id, payment_id) |
| default tolerance | τ = 1 for every type | τ = 0 unless a fixed, documented per-type τ is justified by rounding |
| tie-break | augmenting-path order (F0→B, F1→A in M11) | lexicographic over (issue_id, finding index) → A→F0, B→F1 |
| `get_record` / `get_document` | case-insensitive lookup returns a record for a case variant | an id absent from the data is an error (C11/C12) |

Only the tie-break leaves the scores unchanged; the other rules can turn a false positive into −1, or the
reverse.

### 2.4 Generator gaps against the D-matrix (P1)

* **D03 (correct refund) is missing:** there is no refund concept in the code. The case itself lists
  refunds among the legitimate distractors.
* **D09–D11 need at least one *partial* allocation:** requesting one allocation error produced a
  *missing* allocation in 40/40 seeds, and the partial sub-case exists only inside scenario S1. It must be
  requestable through a documented setting.
* **D02 and D05** are present in practice (split payments 60/60, boundary documents 60/60) but are not
  guaranteed by a documented setting.

### 2.5 Open interpretation questions (decide before the fix)

* **O1: unknown extra fields in a finding.** The definitions list type errors, missing fields and the three
  limits as structure errors; extra fields are not mentioned. The current code rejects them (−1).
  Proposal: keep rejecting them. No published test relies on extra fields.
* **O2: `episode_id` mismatch in findings.** The current judge returns −1. The jury's id replacement list
  does not include `episode_id`, so its paired copies keep it. Proposal: keep −1, and document that
  `episode_id` must equal `manifest.episode_id`.

## 3. What does not need to change

* The official reward formula and its implementation; inspection-step accounting; maximum matching.
* Closed-mode semantics (zero reward, no diagnostics) — only the mode name must be mapped
  (`closed` → `eval`).
* The independent auditor, the verifier and the existing tests (some adversarial tests must be updated
  where they encode the old −1 behaviour, e.g. `unknown_type`, `lowercase_currency`,
  `negative_amount`, `empty_affected`, and the ±1 tolerance test).
* Gymnasium inheritance — not required by the definitions.

## 4. Recommended fix order (requires approval; not started)

1. **P0 adapter (one module + loader):** `judge_adapter.py` with the five entry points;
   episode-directory loader built on the existing `PublicDataset.from_directory` (tables in file order);
   envelope translation; result/observation shaping; `score_episode` reusing the existing judge;
   closed-mode env that holds no truth; README section.
2. **P1 exactness:** exact ids in matcher and tools; any-string type; exact currency; remove extra
   structural limits; extended evidence universe; τ = 0 by default; then update the affected adversarial
   tests, regenerate `data/`, bump `ENV_VERSION`.
3. **P1 generator:** legitimate refund red herring (with auditor support and verification); documented
   setting for partial vs missing allocation; documented guarantees for split payments and boundary
   documents.
4. **P2:** lexicographic tie-break; provenance format documentation; complete id-field list for the
   jury's file transformations.
5. **Verification:** an adapter test suite replaying C01–C20 (fixtures C/E/L/U), the 20 Block-3 tests
   through `score_episode` on episode directories, M01–M12, and file-level paired checks (permutation
   and bijective id replacement performed by a test harness on a copy, exactly as the jury describes).

## 5. Interaction with the research programme

These fixes concern the official benchmark (P0–P5 scope), not P7–P13. The research documents are
updated to treat the adapter interface as the binding agent interface
(`p6_architecture_constraints.md`). Two research conclusions are strengthened:

* exact ids and τ = 0 make symbolic arithmetic and copy-exact id handling mandatory;
* learning runs in train mode only, because closed mode returns no reward by design.
