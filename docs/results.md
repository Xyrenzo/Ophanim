# Measured results

All numbers below were produced by running the code in this repository on 2026-11-21
(`ENV_VERSION 0.1.0`). Re-run them with `python -m ophanim verify` (or the Docker command in the README).

## Tests

**476 passed, 0 failed** on each of:

| platform | Python | runtime |
|---|---|---|
| Windows 11, 12 CPUs | 3.11.15 | ~75 s |
| Windows 11, 12 CPUs | 3.14.3 | ~75 s |
| Linux container (`python:3.11.15-slim`, `--network none --cpus 2 --memory 4g`) | 3.11.15 | ~45 s |

| area | tests | what they cover |
|---|---:|---|
| unit | 63 | RNG golden values, money/rounding, calculator safety, matcher & metrics, code-independence AST scans |
| integration | 264 | generator correctness across 108 episodes, all error types and scenarios, env contract, tools, limits, solvability, trajectory leak scans |
| adversarial | 62 | every reward property required by the case (12) + extra attacks |
| metamorphic | 62 | 60 (episode, variant) pairs + 2 sanity checks |
| reproducibility | 16 | versioned suites, split separation, exact trajectory replay for every policy |
| security | 9 | hostile agent processes, secret isolation, seed brute force |

## Data and ground truth

* Closed evaluation suite: **20/20** episodes pass independent verification (clean before mutation,
  exactly the declared issues after, every allowed evidence set sufficient).
* Published train/dev: **20/20** verified; **20/20** regenerate byte-identically from `configs/` — including
  inside the Linux container from data generated on Windows.
* Development sweep: 320 episodes mixing every type, both scenarios, up to 12 issues and all sizes;
  1,840 injected issues; 0 undeclared discrepancies; 0 anomalies; 0 generation errors.
* Generation speed: 21 / 31 / 43 ms per small / medium / large episode.

## Baselines on the same 20 closed episodes

Secret-keyed generation, derived hidden seeds, agents in separate processes. Precision and recall are
micro-averaged; F1 is the mean per-episode F1 that the reward uses.

| policy | mean return | precision | recall | mean F1 | mean steps | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| random explorer (seed 0) | −0.806 | 0.000 | 0.000 | 0.100 | 23.4 | 0 | 29 | 61 |
| simple reconciliation | −0.599 | 0.141 | 0.607 | 0.213 | 20.5 | 37 | 225 | 24 |
| mark everything | −1.000 | 0.000 | 0.000 | 0.000 | 5.3 | 0 | 600 | 61 |
| oracle (evaluator-only) | +1.000 | 1.000 | 1.000 | 1.000 | 1.0 | 61 | 0 | 0 |
| reference auditor (scripted, extra) | +0.961 | 1.000 | 1.000 | 1.000 | 20.5 | 61 | 0 | 0 |

Mean return by category (clean / interacting / mixed): random −0.23 / −1.00 / −1.00; simple reconciliation
−1.00 / −0.67 / −0.36; mark-everything −1.00 everywhere; oracle 1.00; reference auditor 0.96.

The oracle only shows that the evaluator can award the maximum. The reference auditor shows that every
episode is solvable from accessible records within ~20 of the 100 steps.

## Failure analysis (measured)

**Simple reconciliation** — where the naive procedure breaks:

| claimed type | TP | FP | missed | cause of the false positives |
|---|---:|---:|---:|---|
| fx_rate | 16 | 146 | 4 | takes the date as written (supplier offset / UTC) instead of the company accounting date → wrong rate on every boundary-shifted document |
| duplicate_invoice | 11 | 41 | 0 | "same supplier + same total" also matches repeat orders, recurring invoices and the reversed duplicate |
| period_attribution | 1 | 28 | 10 | compares UTC date strings: flags legitimate boundary documents, misses documents that are outside the period only in company time |
| payment_allocation | 9 | 10 | 10 | claims the Suspense amount and only the first remittance line: wrong for foreign and multi-line payments; also misses S1/S2 amounts |

So the red herrings and the UTC-vs-local mechanics are exactly what separates a shallow reconciliation
from a correct one. **Random explorer**: its few findings never match (wrong ids/amounts/evidence); it scores
well only on clean books when it happens to submit nothing. **Mark-everything**: 600 false positives, −1.

**Environment failures found and fixed during development** (each now covered by a test):

1. *Hung agent could stall the evaluator* — on Windows an agent that never reads stdin blocked the
   evaluator's ~10 KB write. Fix: writes on a dedicated thread; hung agents are cut off at the time budget
   (`test_hanging_agent_is_cut_off_by_the_time_budget`).
2. *Oracle answers on disk during a closed run* — the oracle trajectory was written while later agent
   processes still ran. Fix: oracle runs last; all evaluator-only artefacts are written after every agent
   finished.
3. *Episode record flags* — an invalid submission was recorded as not terminated in isolated runs. Fix:
   use the flags returned by the environment.
4. *Random explorer replayed one action sequence in every episode*. Fix: stream keyed by policy seed and
   episode id.
5. A guessed-id test did not actually change single-id findings (test bug, not an environment bug); fixed.

## Reproducibility and generalisation

* Same seed + config + version + actions → byte-identical trajectories: **20/20** (closed suite) and for
  every policy in the test suite.
* RNG golden values identical on 3.11 and 3.14; a SHA-256 over 10 full episodes is identical on both.
* Metamorphic pairs (new order + every id + names/timestamp text): **20/20** in the closed suite, 60/60 in
  tests — oracle answer (id-mapped) and reward preserved, reference auditor reward and steps identical.
* Evaluation parameter combinations never occur in train/dev (test-enforced); seeds are derived at run time.
