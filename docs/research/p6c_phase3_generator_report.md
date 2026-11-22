# P6-C Phase 3 — Generator compliance: report

Branch `feat/p6-c-compliance` (Phase 2 committed as `60b9f8d`); nothing committed in this phase.

## 1. Baseline (re-run before editing)

Working tree clean; `git log`: `60b9f8d p6-c p2`, `6dadbed p6-c p1`, `f16b130`.
**619 passed** on Python 3.11.15 and **619 passed** on Python 3.14.3.

## 2. Requirement interpretation (official definitions take precedence)

The official D-matrix makes **D01–D05 clean episodes with an empty truth**:
"D01-D05 | Пять чистых компаний | … D03: корректный возврат … Во всех truth пуст". A *correct* refund is
therefore a legitimate red herring that must **not** be reported. The phase brief asked for the refund's
truth to "describe the actual causal error"; that would contradict the official D03, so it was not done.
Instead, the refund's correctness is verified *independently* by the public-data auditor, and a negative
control proves that an inconsistent refund is detected. No new error type was introduced.

## 3. Plan → implementation

| requirement | implementation | tests |
|---|---|---|
| **D03** correct refund | `Payment.direction` (`outbound`/`inbound`) and `Payment.refund_of`. `HistoryBuilder._plant_refund` uses its own random stream. The supplier returns, in full, an earlier unidentified payment (no remittance, parked in Suspense). `posting.post_refund`: `Dr 1000 Bank` = convert(amount, rate(refund date)) / `Cr 2090 Suspense` = the amount the refunded payment parked / difference to `7900`. Guaranteed at `distractors` normal/high, absent at low. Refund and refunded payment are protected from error injection. Payments render `direction` and `refund_of` (explicit null unless a refund). `policy.json` gains the `refund` posting rule. `validate_world`, `audit/reconcile.py` and `audit/formats.py` verify refunds independently | 13 tests incl. 4 tamper controls |
| **D09–D11** allocation mode | `EpisodeConfig.allocation_mode: "auto" \| "missing" \| "partial"` (default `auto` = previous behaviour). Explicit modes plant one correct carrier per requested error before the clean snapshot: a 1-line payment (missing) or a 2-line payment (partial). The injector enforces the shape (`required_kind`) and raises `GenerationError` otherwise; there is no fallback | 20 tests |
| **D02** split payment | `_guarantee_split_payment`: at normal/high, if no split occurred, plant an invoice settled by two applied payments (sum = total). Measured: splits already occurred naturally in 60/60 default episodes | 17 tests |
| **D05** FX/period boundary | the boundary red-herring invoice (in period in company time, UTC date in the adjacent month) now always comes from a **foreign-currency** supplier, so its correct FX rate is the company-time date's rate | 8 tests |
| provenance | `scenario_carriers` added to provenance (smallest change, so planted carriers are traceable); `docs/provenance_format.md` written from real output; a test pins every documented key | 1 test |
| tooling | `build-data` wrote `index.json` with platform line endings, which led to a stale-index mistake during this phase (§6); it now writes LF | regeneration check |

## 4. Designs

**Refund accounting (D03).** The refund participates in the existing model:
* currency equals the refunded payment's currency;
* amount equals the full refunded amount, in exact minor units;
* the refund date is strictly after the original, both inside the period in company time;
* the Bank side uses the refund date's policy rate, and the Suspense side clears the historical parked
  amount, with any FX difference posted to 7900;
* `invoice_refs` is null, there is no AP effect, and the posting balances.

Evidence reachable through the tools:
* the refund document (`get_document`);
* the refunded payment (`get_record payments refund_of`);
* every ledger row of both;
* the FX rate of the refund date.

The independent auditor checks:
* that the refunded payment exists and is outbound without remittance;
* the same entity, currency and amount;
* the chronological order;
* that the Suspense cleared equals the Suspense parked.

Any violation is an anomaly. Tamper tests (Suspense amount, unknown `refund_of`, amount mismatch,
refund dated earlier) are all detected.

**Allocation modes (D09–D11).**
* `missing` → the only remittance line is unapplied: applied = 0, unapplied = payment amount.
* `partial` → one of two lines is unapplied: 0 < applied < amount and applied + unapplied = amount,
  exactly, in the payment currency's minor units. The other line's AP row stays in the ledger.

Truth, provenance (`allocation_kind`) and evidence come from the actual mutation. Measured over 30 seeds:
explicit `missing` produced missing 90/90 times; explicit `partial` produced partial 210/210 times.

## 5. Verification results (executed)

| check | result |
|---|---|
| ad-hoc sweep: 300 episodes (30 seeds × 10 configs incl. both modes, 12-issue mixes, low/high distractors) | 0 independent-verification failures; 270 refunds (exactly 1 per normal/high episode, 0 at low) |
| new tests `tests/integration/test_generator_compliance.py` | **68 passed** |
| full suite, Python 3.11.15 | **687 passed** (619 + 68) |
| full suite, Python 3.14.3 | **687 passed** |
| existing tests | all 619 unchanged and passing (no test weakened) |
| D03 (clean + refund, 8 seeds + tool access + scoring) | pass: truth empty, 0 findings, 0 anomalies, `score_episode([])` F1 = 1 |
| D09 / D10 / D11 (missing, partial, end-to-end through the adapter with tool-fetched evidence) | pass |
| D02 (16 seed × config combinations + guarantee path) | pass |
| D05 (8 seeds through the tools) | pass: foreign boundary invoice; AP = conversion at the company-time date's rate ≠ conversion at the UTC date's rate; pair direction SRC→BASE; clean scoring |
| `ophanim verify` | PASS: 20/20 episodes verified, 20/20 byte-identical regeneration, 727 trajectory lines, 0 leaks; closed evaluation 20/20 data, 20/20 metamorphic, 20/20 reproducibility |
| Docker offline, Linux, Python 3.11.15, `--network none --cpus 2 --memory 4g` | full `ophanim verify` PASS (**687 passed** inside the container; data 20/20 verified and regenerated identically; 0 leaks; 20/20/20 closed evaluation); `judge_adapter.py --smoke` ok |

Baseline returns on the closed suite changed because the episodes changed (ENV 0.3.0):

| policy | mean return |
|---|---:|
| random explorer | −0.709 |
| simple reconciliation | −0.650 (it also falls for the foreign-currency refund red herring) |
| mark-everything | −1.000 |
| reference auditor | +0.961 |
| oracle | 1.000 |

`docs/results.md` is explicitly labelled ENV 0.1.0 and was not rewritten.

## 6. Data regeneration and versioning

`ENV_VERSION` 0.2.0 → **0.3.0**. Data was regenerated with `ophanim build-data` from unchanged seeds and
suites. The diff is broad by construction:
* new documents (refunds, guaranteed splits, foreign boundary invoices) shift the sequential public-id
  stream, so ids are re-drawn;
* the configuration gained `allocation_mode`, so the config digest changes and with it every `episode_id`;
* all 20 `payments.jsonl` files gain `direction`/`refund_of`;
* 19 of 20 episodes gain a refund (the exception is `dev-01`, distractors `low`);
* trajectories grew from 698 to 727 lines.

Integrity is established by regeneration, not by diff size: `ophanim verify` regenerates every published
episode byte-identically and independently verifies all 20.

**A mistake made and fixed during this phase.** After the first regeneration I restored the two
`index.json` files from git to remove line-ending noise, as in Phase 2. This time their `episode_id`
values *had* changed, so the restored files were stale (20/20 entries). A consistency check caught it.
The root cause, CRLF output from `build-data` on Windows, was fixed (`index.json` is now written with LF)
and the data regenerated. Final check: 0 stale entries, 0 CR bytes, and the `index.json` diff is exactly
the 20 new `episode_id` lines.

The official 20-episode suite configuration (`configs/eval/official_suite.json`) is unchanged.

## 7. Remaining gaps / notes

* All D-matrix generator items identified by the P6 audit (D02, D03, D05, D09–D11, DC1/T1 provenance
  documentation) are now addressed and tested.
* Still interpretations (unchanged): O1 (unknown extra fields → −1), O2 (`episode_id` mismatch → −1).
* `docs/results.md` reports ENV 0.1.0 measurements; refresh it from `ophanim evaluate` before submission if
  current numbers are wanted.
* No official run by the jury has happened. "Pass" above means the intended behaviour was verified by
  our own tests and the independent auditor. It is not a jury verdict. Full Blocks 1–4 compliance is not
  claimed.

## 8. Commands

```bash
python -m pytest tests                                            # full suite (PYTHONPATH=src via pyproject)
python -m pytest tests/integration/test_generator_compliance.py   # Phase 3 tests
PYTHONPATH=src python -m ophanim build-data                       # regenerate data/ (deterministic)
PYTHONPATH=src python -m ophanim verify                           # one-command verification
docker build -t ophanim . && docker run --rm --network none --cpus 2 --memory 4g ophanim
docker run --rm --network none --entrypoint python ophanim judge_adapter.py --smoke
```
