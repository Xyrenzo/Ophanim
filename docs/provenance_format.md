# `provenance.json` format (ENV_VERSION 0.3.0)

**Purpose.** Provenance is the evaluator-only record of *how* an episode was made: the generation inputs, the
mapping from internal keys to public ids, the legitimate red herrings, the documents planted for scenarios,
every injected error as a before/after transformation, and the complete clean books before any mutation.
It makes every truth issue independently checkable (official check block 2, condition 1: "before the
error is injected the books are consistent; the provenance history and the source documents allow
independent verification").

**Location and ownership.** `<episode_dir>/evaluator/provenance.json`, written by
`ophanim.generator.episode.generate_episode` (through `judge_adapter.generate_episode`) together with
`evaluator/truth.json`. It belongs to the evaluator/jury.

**Never exposed to the agent.**
* The closed-mode environment never reads the `evaluator/` folder, and no tool can access files.
* The seed, the configuration, the red-herring labels and the before/after rows would reveal or allow
  reconstruction of the answer.
* Tests enforce this: leak scans of every observation and trajectory, a closed episode run with
  `evaluator/` deleted, and AST rules that keep agent code from importing the generator or evaluator.

## Top-level fields

| field | type | content |
|---|---|---|
| `schema_version` | string | public data schema version (`"1.0"`) |
| `env_version` | string | `ENV_VERSION` of the code that generated the episode (`"0.3.0"`) |
| `episode_id` | string | same as `manifest.json` / `truth.json` |
| `generation` | object | `seed` (int), `secret_used` (bool: generation keyed with `OPHANIM_EVAL_SECRET`), `config` (the fully expanded `EpisodeConfig`, including defaults such as `allocation_mode`) |
| `company` | object | `profile` (Financial-DNA profile name), `base_currency`, `offset_minutes` (company UTC offset), `period` (`[start, end]` ISO dates, inclusive) |
| `id_map` | object | internal key → public id. Keys: `S..` supplier → `entity_id`; `I....` invoice → `invoice_id`; `P....` payment → `payment_id`; `R.....` ledger row → `row_id`; `doc:I....` / `doc:P....` → `doc_id`. Covers the union of the clean and the mutated books |
| `distractors` | list | legitimate red herrings (see below); internal keys only |
| `scenario_carriers` | list | correct documents planted *before* the clean snapshot so that a scenario has a guaranteed carrier: `{"scenario", "payment", "invoices"}`. `scenario` ∈ `fx_partial_payment_boundary`, `fx_invoice_unapplied_payment`, `allocation_missing`, `allocation_partial` |
| `injections` | list | one entry per truth issue (see below) |
| `pre_mutation` | object | `validation_problems` (list; always empty for a generated episode, because the clean books must satisfy every accounting equality) and `tables` (`ledger`, `invoices`, `payments`, `fx`: the complete clean public tables, in public ids, before any error was injected) |

### `distractors[]`

Each entry is `{"kind", "note", "invoices"?, "payments"?}` with internal keys:

| kind | meaning |
|---|---|
| `recurring_same_amount` | monthly recurring invoices with the same amount (different vendor_ref) |
| `repeat_order_same_amount` | same supplier and amount, different vendor_ref and date |
| `vendor_ref_collision` | two different suppliers use the same invoice number |
| `reversed_duplicate` | a duplicate capture fully reversed in the period (net zero) |
| `split_payment` | one invoice settled by two payments, both applied (D02; guaranteed at distractors normal/high) |
| `partial_payment` | an invoice partly paid; the payment fully applied |
| `batch_payment` | one payment settling several invoices |
| `unidentified_payment` | a payment without remittance, correctly parked in Suspense |
| `correct_refund` | `payments = [refunded payment, refund]`: the supplier returned an unidentified payment in full (D03; guaranteed at distractors normal/high) |
| `boundary_utc_date` | a foreign-currency in-period invoice whose UTC date lies in the adjacent month (D05) |

### `injections[]`

`{"issue_id", "type", "scenario", "cause", "details"}`:
* `issue_id` equals the `issue_id` in `truth.json`.
* `type` is one of the four error types.
* `scenario` is `"single"` or the interacting-scenario name.
* `cause` is a human-readable causal explanation with internal keys.
* `details` depends on the type; all keys in it are internal:

| type | `details` keys |
|---|---|
| `duplicate_invoice` | `original`, `copy`, `rows_added` (the copy's posting) |
| `payment_allocation` | `payment`, `invoice`, `allocation_kind` (`missing` \| `partial`), `rows_before`, `rows_after` (the payment's posting) |
| `fx_rate` (invoice) | `invoice`, `wrong_rate_date`, `wrong_rate_cause`, `rows_before`, `rows_after` |
| `fx_rate` (payment) | `payment`, `wrong_rate_date`, `wrong_rate_cause`, `rows_before`, `rows_after` |
| `period_attribution` (invoice) | `invoice`, `local_date`, `utc_date`, `rows_added` |
| `period_attribution` (payment) | `payment`, `invoice`, `local_date`, `utc_date`, `rows_added` |

Row snapshots are `{"row", "account", "debit_minor", "credit_minor", "invoice", "payment", "role"}`.
`row`, `invoice` and `payment` hold internal keys; use `id_map` to translate them. `role` is the internal
posting role, one of:
* `expense`, `ap`, `ap_clear`, `bank`, `suspense`, `suspense_refund`, `fx`;
* `reversal_ap`, `reversal_expense`.

## Relationship to `truth.json`

`truth.json` states *what* is wrong in public terms: `issue_id`, `type`, `affected_ids`,
`expected_amount_minor`, `currency`, `allowed_evidence_sets`, `scenario`, plus the file-level
`tolerance_minor`.

Provenance states *how* each issue arose. Every `truth.issues[*].issue_id` appears exactly once in
`provenance.injections`. A clean episode has an empty truth and empty `injections`, and still carries its
red herrings.

## How evaluator code consumes it

* `evaluator/verifier.py` reconciles `pre_mutation.tables` with the independent auditor and requires zero
  discrepancies and zero anomalies. It then reconciles the published tables and requires exactly the
  truth issues.
* `evaluator/metamorphic.py` uses `id_map` to map ids between two presentations of the same episode.
* `adapter.load_sealed_episode` loads it alongside `truth.json`; scoring itself uses only `truth.json`.
* Tests read `distractors`, `scenario_carriers` and `injections` to check red herrings and causal details.

## Paired checks (jury id replacement)

When ids are replaced in a jury copy, these provenance values must be replaced consistently:
* the **values** of `id_map`;
* every id inside `pre_mutation.tables`.

All other references in provenance are internal keys, which are not public ids and need no replacement.

## Versioning and compatibility

The file is regenerated byte-identically from (seed, config, secret, `ENV_VERSION`). A change to its fields
or meaning requires an `ENV_VERSION` bump. The `scenario_carriers` field was added in 0.3.0. Consumers
should ignore unknown keys, and must not depend on the order of `distractors`, which follows generation
order.
