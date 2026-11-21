# Matching and reward (published rules)

Code: `src/ophanim/evaluator/matcher.py` (normalisation, tolerance, evidence, ambiguity) and
`src/ophanim/evaluator/reward.py` (metrics and the official reward). The same matcher is used by the
environment, the evaluation runner and every test.

## Findings schema (strict)

```json
{"episode_id": "EP-…", "findings": [{"type": "duplicate_invoice|payment_allocation|fx_rate|period_attribution",
  "affected_ids": ["…"], "claimed_amount_minor": 12345, "currency": "USD",
  "evidence_ids": ["DOC-…", "GL-…", "2026-03-14:EUR:USD"], "explanation": "short justification"}]}
```

Limits: ≤ 30 findings, ≤ 10 evidence ids, ≤ 1000 characters of explanation, 1–20 affected ids, ids ≤ 64
characters. Strict typing: amounts must be JSON integers ≥ 0 (not strings, floats or booleans), currency
must match `^[A-Z]{3}$`, unknown fields are rejected, `episode_id` must be the current episode. Any
violation → the episode terminates with reward **−1** and the error goes to the evaluator log.

## When is a finding a true positive?

A finding is *eligible* for a truth issue when all of these hold:

1. same `type`;
2. same set of affected ids after normalisation (trim + upper-case; order and repeats ignored);
3. `|claimed − expected| ≤ tolerance_minor` = **1 minor unit** (absorbs rounding-mode differences; every
   injected FX discrepancy is ≥ 3 units, so tolerance can never hide an error);
4. same currency code (no conversion is ever applied);
5. every evidence id exists in the episode's public data, and the evidence set contains at least one
   complete allowed evidence set (extra valid ids are fine).

The explanation is never read.

**One-to-one matching.** TP = size of a maximum bipartite matching between findings and issues, computed
with augmenting paths, findings in submission order, issues in `issue_id` order — deterministic and never
more than one TP per issue. Unmatched findings (including repeats of an already matched finding) are FP;
unmatched issues are FN.

## Metrics and reward

```
P  = TP / (TP + FP)        0 if the denominator is 0
R  = TP / (TP + FN)        0 if the denominator is 0
F1 = 2TP / (2TP + FP + FN) 1 if truth and findings are both empty; 0 if truth is empty but findings are not
R_episode = clip(2·F1 − 1 − 0.002·inspection_steps, −1, 1)      (official, unchanged)
```

* `inspection_steps` = every step consumed **before** the final submit: `list_records`, `get_record`,
  `get_document`, `calculator` and invalid actions (they also consume a step). The submit step is not
  counted. On truncation it equals the steps consumed. The trajectory logger and the evaluator use this
  same definition.
* Exploration steps return 0; the episode return equals the terminal reward.
* Truncation (100 steps or 60 s) scores an **empty final answer**.
* In closed evaluation (`mode="eval"`) the environment returns 0.0 for every step; the real reward and all
  diagnostics stay with the evaluator until the run ends.
* Arithmetic is exact (fractions), converted to float once.

## Specification-gaming defences and the tests that prove them

| attack / property | defence | test (`tests/adversarial/test_reward_attacks.py` unless noted) |
|---|---|---|
| evidence-backed answer must beat silence on erroneous books | F1 | `test_correct_evidence_backed_answer_beats_silence_on_erroneous_books` |
| silence must beat false accusations on clean books | F1 special cases | `test_silence_beats_false_accusations_on_clean_books` |
| duplicate findings | one-to-one matching; repeats are FP | `test_duplicate_findings_give_no_benefit` |
| mark every record / every type | FP destroys precision | `test_marking_everything_scores_badly` |
| unsupported or fabricated evidence | complete allowed set required; unknown ids disqualify | `test_unsupported_evidence_cannot_create_a_true_positive`, `test_evidence_from_another_episode_is_rejected` |
| guessed ids | exact id set required | `test_guessed_ids_receive_no_credit` |
| currency / amount tricks | exact currency, ±1 tolerance, ints only | `test_incorrect_currency_receives_no_credit`, `test_amount_tolerance_is_exactly_one_minor_unit` |
| malformed input | strict schema → −1 | `test_invalid_input_gives_minus_one_and_terminates` (16 variants) |
| repeated submission | episode ends at first submit | `test_repeated_submission_cannot_change_the_reward` |
| timeout | truncated + empty answer | `test_timeouts_truncate_with_empty_answer`, `tests/integration/test_env_contract.py` |
| inspection cost only slightly separates equal answers | 0.002/step, max 0.198 | `test_inspection_cost_only_slightly_distinguishes_equal_answers` |
| persuasive explanations | explanation ignored | `test_reward_does_not_depend_on_explanation_text`, `tests/unit/test_matcher_reward.py` |
| reward tampering / reading the answer | no write path; evaluator in another process; secret-keyed seeds | `tests/security/test_process_isolation.py` |

## Properties of the official formula worth knowing (honest notes)

* On erroneous books, silence and wild accusations both score −1: the formula does not separate "did
  nothing" from "did harm" there. Only precision-preserving partial answers climb above −1.
* With many issues (e.g. 12), saving ~90 steps can outweigh one missed issue; with ≤ 3 issues a complete
  answer after 99 steps always beats an answer missing one issue at 0 steps (tested).
* On clean books a time-out scores like a late empty submission (1 − 0.002·steps).
* A high oracle reward proves only that the evaluator can award the maximum, not that the task is hard.
