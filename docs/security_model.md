# Security and isolation model

Goal: the agent must not be able to obtain the hidden answer (truth, provenance, seed, evaluator
diagnostics) or to influence the evaluator, other than by submitting findings.

## Boundaries

| layer | what the agent can reach | what it cannot |
|---|---|---|
| Tools (`env/tools.py`) | read-only copies of the public tables and documents | truth, provenance, seed, generator, judge (the toolbox is built from public tables only) |
| Observations | requested records, result or error code, remaining steps | issue ids, expected amounts, match details, reward (closed mode) |
| Errors | fixed code + fixed message (input never echoed, no stack traces, no paths) | internal state |
| Process | in closed evaluation the agent is a separate OS process speaking JSON lines (`agent_runtime.py`) | the environment object, the judge, the truth in memory |
| Environment variables | a sanitised environment without any `OPHANIM_*` variable | the evaluation secret |
| Working directory | an empty temporary directory | evaluator output (written only after all agents finished) |

## Specific threats and defences

* **Seed brute force.** The generator is open source. With small hidden seeds an agent could regenerate
  candidate episodes and read the answer. Closed runs key all generation with
  `HMAC-SHA256(OPHANIM_EVAL_SECRET, seed)`; `episode_id` is derived from that key, never from the raw seed.
  Tested: without the exact secret, neither ids nor data match (`test_secret_defeats_seed_brute_force`).
* **Structural tells.** Public ids are random tokens from a presentation stream independent of content
  and errors; ordering is applied after injection; every error signature (Suspense rows, UTC-shifted dates,
  equal amounts, equal vendor refs, FX gain/loss rows) also occurs legitimately in clean books.
  Tested: injected copies have uniformly spread id ranks; clean books contain all red-herring kinds.
* **Calculator abuse.** Hand-written tokenizer/parser; only ASCII digits, `+ - * / ( )`; no `eval`, `exec`,
  `ast`, names, calls, powers, exponents or Unicode digits; length, depth, digit and magnitude limits.
  An AST scan of the whole code base forbids `eval/exec/compile/__import__`.
* **Hostile agent processes.** Malformed JSON, non-dict messages and lines > 1 MB become invalid actions;
  a crash or an unresponsive agent is aborted at the time budget and scored as an empty answer; writes to
  the agent happen on a separate thread so a non-reading agent cannot block the evaluator.
* **Reward tampering / evaluator writes.** No tool writes anything; submit is the only scoring input; the
  first submit ends the episode; repeated submits are ignored.
* **Leaks through logs.** Public trajectories contain only what the agent saw; judge logs, the oracle
  trajectory and reports are evaluator-only and written after agent runs. A leak scan of every published
  trajectory runs in `ophanim verify`.

## Oracle

`evaluator/oracle.py` reads the sealed truth and lives only in the evaluator package. It is never
registered as an agent policy (`policies/` cannot import evaluator code — enforced by an AST test) and is
never run as an agent process.

## Residual risks (honest limitations)

* Process isolation is an OS process boundary, not a sandbox: an agent process shares the filesystem and
  could read files the user account can read. Closed-run truth exists only in evaluator memory during the
  run; the *open* train/dev truth files are on disk by design. A container-per-agent setup would remove
  this residual risk.
* The in-process `OphanimEnv` (used for training and tests) holds the judge in the same Python process;
  it is meant for open training, not for adversarial closed evaluation.
* The 60-second wall-clock limit is the only non-deterministic element of an episode.
