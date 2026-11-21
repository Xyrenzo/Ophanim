# P6 — Binding architecture constraints (from the official check definitions)

Every future component (P7–P13) and every compliance fix must satisfy these constraints. They take
precedence over convenience, framework conventions and the earlier P6 proposals; where
`p6_agent_architecture.md` differs, this document wins.

## 1. Integration surface (official)

| entry point | contract | consequence for our design |
|---|---|---|
| `generate_episode(seed, config, output_dir)` | wraps the team generator; writes manifest, ledger, invoices, payments, fx, policy and closed truth/provenance | the existing generator stays the single source of episodes; the directory layout is documented and stable |
| `make_env()` | returns an object with `reset`, `step` | thin adapter over `OphanimEnv`; **no Gymnasium inheritance** |
| `reset(seed, config)` | `config = {"mode": "closed"\|"train", "episode_dir"?, "team_config"?}`; with `episode_dir` the given episode is **loaded as-is** (no regeneration, no id change); repeated reset restarts it | the environment must support *load from directory* as a first-class path; records are served **in file order**, so a jury permutation is visible |
| `step({"name", "args"})` | five names; unknown names are ordinary invalid actions that consume a step | the envelope is translated in the adapter; validation stays inside the environment |
| observations | first: `{task, manifest, policy, remaining_steps}`; then `{result, error, remaining_steps}`; results: `{records, next_cursor}`, record object, document object, decimal string, `{"accepted": true}` | the adapter shapes outputs; the native environment may keep its richer format |
| `score_episode(episode_dir, findings, inspection_steps)` | closed evaluator call → `{tp, fp, fn, precision, recall, f1, return}`; invalid → `return = -1`, others `null` | scoring is a pure function of the episode directory, the findings and the step count, reusing the shared judge and matcher |

## 2. Isolation

1. The policy runs in a separate, restricted process. It receives only observations and the step result,
   never imports the evaluator, and never sees `episode_dir`, paths, seeds or configs.
2. "Hiding fields in a Python object is not isolation." In closed mode the environment object built by
   `make_env` **does not load truth or provenance**: scoring happens only in `score_episode`, in the
   jury's evaluator process.
3. Closed mode: reward 0 at every step, **including termination**; `info` contains nothing derived from
   truth; submit returns only `{"accepted": true}` or a bounded structure error.
4. Train mode may return the terminal reward. Learning is therefore possible **only in train mode**;
   closed mode carries no learning signal by design.
5. The oracle stays evaluator-side and submits through an ordinary submit; its existence grants nothing
   to other policies.
6. Error messages contain a public code and a short fixed text; no paths, seeds or hidden data.

## 3. Exact matcher semantics (shared by evaluator, tests and any research metric)

* ids: exact string comparison (case and whitespace significant); no normalisation, prefix stripping or
  fuzzy matching; tool lookups are exact as well;
* `affected_ids`, `evidence_ids`: sets of exact ids, formed **after** the raw structural limits;
* evidence: at least one complete allowed set; any non-existent or inaccessible id → the finding is not
  matched (FP);
* `type`: exact string; unknown strings are unmatched (FP), not structure errors;
* currency: exact string; no conversion, case folding or trimming; no ISO requirement;
* amount: a JSON integer (not bool, string or float); `|claimed − expected| ≤ τ` with **τ = 0 by default**,
  or a fixed, pre-published per-type τ justified by documented rounding;
* structure errors (→ −1) are only: wrong value types, missing required fields, more than 30 findings,
  more than 10 evidence ids in a finding, explanation longer than 1000 Unicode code points.
  **Open interpretation (O1):** the definitions do not mention *unknown extra fields*. The current code
  rejects them (−1). The proposal is to keep rejecting them, because the case calls a wrong structure
  "неверная структура" and no published test relies on extra fields. The team should confirm this, and
  agents must never add fields to findings;
* maximum-cardinality bipartite matching; ties broken lexicographically over (issue_id by code point,
  finding index); duplicate findings remain separate vertices;
* numeric results compared to 1e-9; money and steps compared exactly as integers.

## 4. Episode data and paired checks

* The jury transforms **files** (record permutation, bijective id replacement in all data and
  references, matching edits in truth/provenance) and loads each copy through `reset(episode_dir)`.
  The team does not provide a transform switch.
* Our data must therefore be transformable by documentation alone. Every id-bearing field per file must be
  listed: `row_id`, `doc_id`, `invoice_id`, `payment_id`, `entity_id`, `invoice_refs[].invoice_id`,
  `affected_ids`, `evidence_ids`, provenance `id_map` values and `pre_mutation.tables`.
* FX keys `date:SRC:TGT` are natural keys and are not replaced.
* `line_items` order is not assumed harmless; nothing may depend on file order except the order in which
  `list_records` returns records.
* Replay of the same (episode, actions) must reproduce records, transitions and rewards exactly
  (JSON-value equality).

## 5. Episode-time and budget rules

* 100 actions including submit; submit is not an inspection step; invalid actions are inspection steps;
  99 inspection actions + submit is accepted; 100 inspection actions truncate with empty findings.
* 60 s from the start of reset to the end of the episode, **including policy compute**. This sets a
  latency budget for learned agents: about 0.6 s per action at the full 100 actions, about 3 s per action
  for a ~20-step full scan (derived from the rule, not measured).

## 6. Consequences for the research architecture

1. **The agent interface is the adapter envelope.** Research action adapters emit
   `{"name", "args"}` actions (or native actions translated 1:1). No research component may require a
   different environment API.
2. **No framework drives the design.** Gymnasium, SB3 and others may wrap the adapter for experiments, but
   the official path never depends on them.
3. **Exact ids ⇒ copy, never generate.** Learned components must select ids from observed records
   (pointer or candidate selection) and copy them byte-for-byte; any normalisation inside an agent is a
   bug.
4. **τ = 0 ⇒ symbolic arithmetic is mandatory** for amounts, which reinforces the neuro-symbolic split
   (learned decisions, exact computation).
5. **Unknown types are FP, not −1** (after the fix): a malformed *field value* is cheap; a malformed
   *structure* is catastrophic. Agents must validate structure before submit (the finding builder's
   schema check).
6. **Training data can be stored as episode directories.** The same loader serves research datasets,
   fixtures and jury copies. Research splits stay in their own seed namespaces, and the official
   directories are never used for training.
7. **Evaluation of any learned agent** uses the same two-process setup (policy process + evaluator
   process with `score_episode`) as the official checks.
