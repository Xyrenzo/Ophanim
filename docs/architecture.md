# Architecture

```
                       EVALUATOR PROCESS (trusted)                                AGENT PROCESS (untrusted)
 ┌──────────────────────────────────────────────────────────────────────┐        ┌──────────────────────────┐
 │ generator/                                                            │        │ agent_runtime.py          │
 │   history ─► posting ─► self-check ─► [clean snapshot] ─► injectors   │        │   policies/ (baselines)   │
 │   ─► presentation ─► PublicEpisode  +  SealedEpisode(truth, provenance)│        │   or any program speaking │
 │                                                                        │ JSON  │   the JSON-lines protocol │
 │ env/  OphanimEnv(reset/step) ── Toolbox(public tables only) ◄─────────┼─lines─►│                          │
 │        └─ Judge(sealed truth) ── matcher ── reward                    │ stdio  └──────────────────────────┘
 │ evaluator/ verifier (uses audit/), runner, process_runner, evaluation │
 │ audit/  independent stdlib-only auditor (public files + policy only)  │
 └──────────────────────────────────────────────────────────────────────┘
```

| package | role | may import |
|---|---|---|
| `ophanim.rng` | SHA-256 counter-mode RNG, named sub-streams, optional secret key | stdlib |
| `ophanim.money`, `timeutil` | integer minor units, Decimal conversion, fixed UTC offsets | stdlib |
| `ophanim.schemas` | strict Pydantic models: config, actions, findings, truth | pydantic |
| `ophanim.generator` | hidden history, postings, causal error injection, presentation | everything except `audit` |
| `ophanim.audit` | independent reconciliation of the public records, evidence sufficiency, format checks | **stdlib + itself only** (AST-enforced) |
| `ophanim.env` | reset/step contract, tools, calculator, task text | generator (at reset), evaluator.judge |
| `ophanim.evaluator` | matcher, reward, judge, verifier, oracle, runners, metamorphic checks, evaluation report | everything |
| `ophanim.policies` | agent-side baselines | **never evaluator or generator** (AST-enforced) |
| `ophanim.agent_runtime` | agent-side stdio loop for closed evaluation | policies |

## Reproducibility design

* No use of Python's `random` module (only `random.random()` is version-stable). All randomness comes from
  `DeterministicRng`: block *i* = SHA-256(key ‖ i). Golden values are pinned in tests and the suite runs
  on Python 3.11 and 3.14; a hash of 10 complete episodes is identical on both.
* Independent named streams: `content` (economics), `carriers` (scenario documents), `errors` (which
  documents get errors), `presentation` (ids, names, order; keyed by the config hash and salts). The same
  seed with and without errors is the same company; presentation-only changes give metamorphic variants.
* Files are written with `\n` line endings and fixed key order → byte-identical on Windows and Linux.
* Identical `(seed, config, ENV_VERSION, secret, actions)` reproduce identical records, observations and
  rewards (tested at step level and for whole trajectories).

## Why an independent auditor?

The generator could be wrong in ways its own checks would not catch. `ophanim.audit` re-implements the
published policy from `policy.json` without importing any generator code, and the verifier requires that:

* the clean pre-mutation books show **zero** discrepancies and zero anomalies;
* the mutated books show **exactly** the declared issues (type, ids, amount, currency);
* each allowed evidence set, on its own, proves its issue and amount.

The same auditor drives the scripted reference auditor policy, which solves every episode through the
agent tools in ~20 steps — evidence that the hidden truth is always recoverable from accessible records.

## Environment contract

* `reset(seed, config) -> (observation, info)`; `options=` is accepted as a Gymnasium alias.
  Observation: task text, public manifest, policy, tool specs, `remaining_steps`, time budget.
  Info: env/schema version and mode only.
* `step(action) -> (observation, reward, terminated, truncated, info)`. Actions are flat JSON objects:
  `list_records(table, cursor, limit≤50)`, `get_record(table, id)`, `get_document(doc_id)`,
  `calculator(expression)`, `submit(findings)`. Observation: `{ok, result, error{code,message}, remaining_steps}`.
* 100 steps including submit; 60 s; unknown actions/ids give a bounded error and consume a step;
  stepping after the end returns `episode_finished` with reward 0.
* The class does not inherit `gymnasium.Env` (allowed by the case); it follows the same semantics:
  `terminated` = submit (MDP end), `truncated` = step/time limit.
