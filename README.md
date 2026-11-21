# OPHANIM — Financial Forensics Lab

**A reproducible reinforcement-learning environment for AI accounts-payable auditing.**
Genesis Hackathon 2026 · FinTech track.

An agent receives the books of a fictional company for one reporting period, investigates them with
narrow read-only tools, and submits structured findings with evidence. The environment generates a
consistent hidden accounting history, injects real accounting errors through causal transformations,
keeps the ground truth sealed, and scores the findings with one shared matcher and the official reward.

OPHANIM is an environment, not a payment app, a chatbot or an audit report. It does not train a model.

## Quick start

### Docker (offline, Python 3.11, CPU only)

```bash
docker build -t ophanim .
docker run --rm --network none --cpus 2 --memory 4g ophanim            # one-command verification
docker run --rm --network none ophanim demo --seed 7                   # scripted demo episode
docker run --rm --network none -e OPHANIM_EVAL_SECRET=<secret> ophanim evaluate --seed-base <hidden>
```

### Local

```bash
python3.11 -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.lock                       # pinned: pydantic 2.14.4, pytest 9.2.0
export PYTHONPATH=src                                  # Windows PowerShell: $env:PYTHONPATH="src"
python -m ophanim verify                               # tests + data + trajectories + closed evaluation
```

`verify` prints `OPHANIM VERIFY: PASS` and exits 0 only if every check passes. Runtime dependency:
Pydantic only. No network, GPU or paid API is used at run time.

## Official judge adapter (Genesis FinTech check definitions)

**Working directory:** the repository root (`/app` in the Docker image). **Entry point:**
`judge_adapter.py`, a thin re-export of `src/ophanim/adapter.py`. Gymnasium is not used.

```python
import judge_adapter as ja

ja.generate_episode(seed, config, output_dir)        # config = team configuration (see below)
env = ja.make_env()
obs, info = env.reset(seed, {"mode": "closed", "episode_dir": output_dir, "team_config": {}})
obs, reward, terminated, truncated, info = env.step({"name": "list_records",
                                                     "args": {"table": "ledger", "cursor": None, "limit": 50}})
scores = ja.score_episode(output_dir, findings, inspection_steps)
```

Self-check: `python judge_adapter.py --smoke`. In Docker:
`docker run --rm --network none --entrypoint python ophanim judge_adapter.py --smoke`.

| entry point | behaviour |
|---|---|
| `generate_episode(seed, config, output_dir)` | Writes `output_dir/public/{manifest.json, policy.json, ledger.csv, invoices.jsonl, payments.jsonl, fx.csv}` and `output_dir/evaluator/{truth.json, provenance.json}`. It is deterministic in (seed, config, version). `config` is the team configuration (keys `profile`, `size`, `errors`, `scenarios`, `distractors`, `presentation`; see `schemas.EpisodeConfig`), given bare or as `{"team_config": {...}}`. |
| `reset(seed, config)` or `reset(seed=…, options=config)` | `{"mode": "closed", "episode_dir": d}` loads `d/public` exactly as stored, with the same ids and record order and no regeneration. No truth is loaded, and every reward is 0.0, including at termination. A repeated reset starts the same episode again. `{"mode": "train", "episode_dir": d}` loads `d/public` and `d/evaluator`, and the terminal reward is returned. `{"mode": "train", "team_config": {...}}` generates from `seed`. |
| `step({"name", "args"})` | Names: `list_records` (`table`, `cursor`, `limit` ≤ 50), `get_record` (`table`, `id`), `get_document` (`doc_id`), `calculator` (`expression`), `submit` (`findings`). Unknown names and malformed envelopes are bounded errors that consume a step. |
| `score_episode(episode_dir, findings, inspection_steps)` | Evaluator side. Returns `{tp, fp, fn, precision, recall, f1, return}`. A structurally invalid submission returns `return = -1` with the other fields `null`; the reason goes to the logger `ophanim.judge_adapter`. |

**Observations:**
* After reset: `{"task", "manifest", "policy", "remaining_steps": 100}`.
* After each step: `{"result", "error", "remaining_steps"}`.
* `error` is `null` or `{"code", "message"}`, with a public code and fixed text.

**Results per action:**

| action | result |
|---|---|
| `list_records` | `{"records": [...], "next_cursor": string or null}` |
| `get_record`, `get_document` | the record or document object |
| `calculator` | a decimal string (`"0.1+0.2"` → `"0.3"`) |
| `submit` | `{"accepted": true}`, or the error `invalid_submission` |

**Tables and identifiers:**
* Tables are `ledger`, `invoices`, `payments`, `fx`.
* Record ids are `row_id` (ledger), `invoice_id`, `payment_id`, and the FX key `"YYYY-MM-DD:SRC:TGT"`, which is a natural key and not a surrogate id.
* Id-bearing fields for consistent replacement: `row_id`, `doc_id`, `invoice_id`, `payment_id`, `entity_id`, `invoice_refs[].invoice_id`, and in `truth.json`: `affected_ids`, `allowed_evidence_sets`.
* In `provenance.json`, the id-bearing fields are `id_map` values and the ids inside `pre_mutation.tables`.

**Limits:**
* 100 actions including submit; submit is not an inspection step.
* 99 inspection actions followed by a submit is accepted; 100 inspection actions truncate with empty findings.
* 60 s per episode from reset.

**Error types (the `type` values):**
* `duplicate_invoice`: duplicate invoices.
* `payment_allocation`: missing or partial payment allocation.
* `fx_rate`: wrong FX date or rate.
* `period_attribution`: reporting-period error.

The amount tolerance τ is read from `evaluator/truth.json` (`tolerance_minor`, mirrored in `policy.json`).
Compliance status against the check definitions is tracked in `docs/research/p6_traceability_matrix.md`;
Phase 1 report: `docs/research/p6c_phase1_adapter_report.md`.

## The environment in 20 lines

```python
from ophanim.env import OphanimEnv

env = OphanimEnv(mode="train")                       # "eval" = closed mode: rewards withheld
obs, info = env.reset(seed=7, config={"errors": {"duplicate_invoice": 1, "fx_rate": 1},
                                      "scenarios": {"fx_partial_payment_boundary": 1}})
episode_id = obs["manifest"]["episode_id"]
print(obs["task"], obs["manifest"], obs["policy"], obs["remaining_steps"])

obs, reward, terminated, truncated, info = env.step(
    {"action": "list_records", "table": "ledger", "cursor": None, "limit": 50})
obs, reward, terminated, truncated, info = env.step(
    {"action": "calculator", "expression": "(1250.00 * 1.083215) - 1354.02"})
obs, reward, terminated, truncated, info = env.step({"action": "submit", "findings": {
    "episode_id": episode_id,
    "findings": [{"type": "fx_rate", "affected_ids": ["INV-…"], "claimed_amount_minor": 1234,
                  "currency": "USD", "evidence_ids": ["DOC-…", "GL-…", "2026-03-14:EUR:USD"],
                  "explanation": "booked at the due-date rate"}]}})
```

* Actions: `list_records(table, cursor, limit≤50)`, `get_record(table, id)`, `get_document(doc_id)`,
  `calculator(expression)`, `submit(findings)` — flat JSON objects.
* 100 steps including submit, 60 s per episode. Invalid actions and unknown ids give a bounded error and
  consume a step. `submit` → `terminated=True`; step/time limit → `truncated=True` with an empty answer.
* Reward: `clip(2·F1 − 1 − 0.002·inspection_steps, −1, 1)` at the end; 0 for every exploration step.

## What is inside

| requirement | where |
|---|---|
| 4 independently configurable error types | `generator/injectors.py`: duplicate invoices, missing/partial payment allocation, wrong FX date/rate, reporting-period attribution |
| 2 interacting scenarios | S1 partial foreign payment at the period boundary (fx + allocation); S2 wrong-rate invoice + unapplied payment line |
| clean companies + red herrings | recurring equal amounts, repeat orders, same vendor_ref across suppliers, reversed duplicate, split / partial / batch payments, unidentified payments, UTC-vs-local boundary documents |
| consistent history → causal errors | `generator/history.py`, `posting.py` (self-check), snapshot kept in provenance |
| hidden truth + provenance | `truth.json`, `provenance.json` — evaluator only |
| independent verification | `audit/` (stdlib only, no generator code) + `evaluator/verifier.py` |
| Gymnasium-style contract | `env/environment.py` |
| shared matcher + official reward | `evaluator/matcher.py`, `evaluator/reward.py` |
| 4 baseline adapters | `policies/` (random explorer, simple reconciliation, mark-everything) + `evaluator/oracle.py` |
| process isolation | `agent_runtime.py` + `evaluator/process_runner.py` |
| metamorphic checks | `evaluator/metamorphic.py` |
| 10 train + 10 dev episodes | `data/train/`, `data/dev/` (from `configs/`) |
| trajectories | `data/trajectories.jsonl` |
| closed evaluation + report | `evaluator/evaluation.py`, `python -m ophanim evaluate` |

Six company profiles ("Financial DNA"): retail, trading, software, manufacturing, logistics, consulting.
Ten currencies including JPY (0 decimals) and KWD (3 decimals); eight fixed company UTC offsets.

## Documentation

* [`docs/design_note.md`](docs/design_note.md) — short design note (start here)
* [`docs/architecture.md`](docs/architecture.md) — components, process model, reproducibility
* [`docs/data_model.md`](docs/data_model.md) — files, formats, accounting rules, error definitions
* [`docs/reward_design.md`](docs/reward_design.md) — matcher rules, reward, spec-gaming tests
* [`docs/security_model.md`](docs/security_model.md) — isolation, threats, residual risks
* [`docs/evaluation_protocol.md`](docs/evaluation_protocol.md) — splits, seeds, official structure, plugging in policies
* [`docs/results.md`](docs/results.md) — measured results and failure analysis

## Results

See [`docs/results.md`](docs/results.md) for the numbers measured on this code (tests, verification,
baselines, metamorphic and reproducibility checks).

## Limitations

See the "Limitations" section of [`docs/design_note.md`](docs/design_note.md). In short: accounts payable
only; fixed UTC offsets (no DST); process isolation rather than a sandbox; the official formula cannot
distinguish silence from wild accusations on erroneous books; the scripted reference auditor shows the
episodes are solvable by a rule-based procedure, so difficulty comes from reasoning under a budget, not
from hidden facts; no model was trained and no learning claim is made.

## Use of AI tools (disclosure)

Per the hackathon rules (section 08), the team discloses that the code and documentation of this
repository were developed with the help of an AI coding assistant (Claude Code) under the team's
direction and review. All design decisions, test results and claims in this repository were checked by
running the code.

## License

MIT — see [`LICENSE`](LICENSE).
