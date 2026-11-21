# P6.5–P6.7 — Experiment protocol

The official reward and the official closed suite are **unchanged and evaluation-only**. Everything else
in this document is research infrastructure that sits beside them.

## 1. Data separation

| set | source | seeds | use | never used for |
|---|---|---|---|---|
| Official closed suite | `configs/eval/official_suite.json` + hidden seed base + secret | derived at run time, secret-keyed | milestone reporting only | training, tuning, model selection, early stopping |
| Open published data | `data/train`, `data/dev` (20 episodes) | 1001–1010, 2001–2010 | debugging, demos, smoke tests | headline results (too small) |
| `research/train` | procedural, sampled configs | namespace `research-train` | training, demonstrations | evaluation |
| `research/val` | fixed 200 episodes | namespace `research-val` | hyper-parameters, early stopping | final claims |
| `research/test-iid` | fixed 500 episodes | namespace `research-test` | final in-distribution results | anything before the final run |
| `research/test-ood-*` | fixed 200 each (below) | own namespaces | generalisation results | training or tuning |
| demonstrations | scripted demonstrators on `research/train` only | inherited | BC / DAgger | — |

Seeds come from `derive_seed(namespace, split, i)` (the existing function, `evaluator/evaluation.py` L45),
so namespaces cannot collide with each other or with the official derivation. Every trajectory and
dataset record carries its namespace and config fingerprint, and a P7 test asserts disjointness.
Procedural generation gives effectively unlimited training episodes (21–43 ms each, measured), so small
fixed training sets are unnecessary.

**OOD test sets** (the training sampler excludes the held-out factor):

| set | held-out factor |
|---|---|
| `ood-profile` | 2 of 6 company profiles (e.g. logistics, consulting) never seen in training |
| `ood-combination` | type co-occurrences never seen together in training (e.g. `fx_rate`+`period_attribution`; scenario S2) |
| `ood-size` | train small/medium, test large |
| `ood-distractor` | train low/normal, test high red-herring density |
| `presentation` | metamorphic variants of `test-iid` (shuffled order, new ids/names, company-offset timestamps) |
| `scarcity` (research regime) | agent-side self-imposed budgets (e.g. ≤ 8 or ≤ 12 steps); official reward still computed by the official judge |

## 2. Reference points (all on identical episodes)

| reference | why it is reported |
|---|---|
| silent (submit `[]` immediately) | the degenerate optimum for weak agents; **−0.500** on the current closed suite (measured), `2·p_clean − 1` in general |
| random explorer, simple reconciliation, mark-everything | official baselines |
| reference auditor | scripted, implements the published rules exactly; an *upper public-data reference*, not a learning baseline |
| oracle | ceiling (evaluator-only); says nothing about difficulty |

A learned agent can exceed the reference auditor on the official reward only by reading less (≤ ≈0.044 per
medium episode). Learning claims are therefore made against the silent and simple-reconciliation
references, as a gap to the reference auditor, and on OOD sets.

## 3. Metrics

**Official (unchanged):** reward; P, R, F1, TP, FP, FN (judge).

**Research metrics** (computed from public trajectories plus the judge log, never shown to the agent):

| group | metric | definition |
|---|---|---|
| audit quality | per-type TP / FP / FN | judge verdicts (`claimed_type`, unmatched issues) |
| efficiency | steps; inspection steps; tool-call histogram | trajectory |
| efficiency | records revealed, documents revealed, coverage per table | distinct ids returned in observations |
| efficiency | redundant reads; invalid-action count; runtime | trajectory |
| learning | return and F1 vs environment steps and episodes; area under the curve; episodes to reach val F1 ≥ 0.8 | training logs |
| reliability | mean ± std across training seeds; IQM and 95 % interval estimates as recommended by Agarwal et al. (2021) — computed here with a percentile bootstrap (our choice); failure rate (R = −1), invalid-submission rate, truncation rate | evaluation |
| generalisation | gap = metric(test-iid) − metric(test-ood-*), with paired bootstrap CI | evaluation |
| evidence quality | valid-evidence rate (no unknown ids); unsupported-finding rate (`evidence_unknown_id` or `evidence_insufficient` as the best-candidate reason); evidence completeness among otherwise-correct findings | judge reasons |
| near-miss profile | distribution of best-candidate rejection reasons (type / ids / amount / currency / evidence) | judge reasons |
| calibration | expected calibration error and reliability diagrams of per-candidate confidences (Guo et al. 2017) | agent-side log + labels on research sets |
| invariance | metamorphic agreement: identical decisions up to id mapping | paired runs |

Calibration uses an agent-side channel only. Confidences are never placed in the official findings: the
current schema rejects extra fields (−1, covered by an adversarial test), and their treatment under the
official definitions is an open interpretation question (`p6_architecture_constraints.md`, O1).

## 4. Statistical procedure

* **Paired design:** every condition is evaluated on the same episode lists, the same `ENV_VERSION`, the
  same hardware class and the same evaluation budget.
* **Seeds:** at least 5 independent training seeds per condition (minimum chosen for cost; report every
  seed). Report per-seed curves, mean ± std, and IQM with 95 % bootstrap CIs over seeds × episodes.
* **Episode-sampling variance is real.** Simple reconciliation scored −0.599 and −0.662 on two different
  hidden 20-episode suites (`runs/verify`, `runs/official-evaluation`). Headline research numbers
  therefore use ≥ 200-episode research test sets, with the 20-episode official suite as a secondary report.
* **Tuning budget:** equal hyper-parameter search budget per method, on `research/val` only.
* **Pre-registration:** hypotheses, primary metrics and decision thresholds below are fixed before running.
  Test sets are evaluated once per final model.
* **Reproducibility of training:** seeded environment, policy and data order; CPU deterministic
  algorithms where available; library versions recorded; evaluation episodes replayed and compared
  (the existing replay check).
* **Reporting:** following Henderson et al. (2018) and Agarwal et al. (2021): curves with variability,
  interval estimates rather than point estimates, all seeds, and all failures.

## 5. Research questions

Format: **H** hypothesis · **IV** independent variable · **DV** dependent variables · **C** conditions ·
**B** baselines · **L** limitations · **S/R** support / reject criterion. Unless stated otherwise, the
primary DV is mean official reward on `research/test-iid`.

**RQ1 — Does BC improve RL sample efficiency?**
H: PPO initialised from BC reaches val F1 ≥ 0.8 in fewer environment steps than PPO from scratch.
IV: initialisation (BC vs random). DV: episodes-to-target, AUC, final reward. C: same architecture, budget,
seeds. B: BC alone, silent. L: depends on demonstration diversity.
S/R: supported if the 95 % CI of the step ratio is entirely below 1; rejected if it includes 1.

**RQ2 — PPO vs a value-based learner.**
H: masked PPO outperforms DQN/QR-DQN (macro acquisition) + DRRN-style candidate scoring at equal sample
budgets. IV: algorithm. DV: final reward, F1, stability across seeds. C: same adapter, features and budget.
B: silent, reference auditor. L: the set-valued submission is unfavourable to factorised Q-values by design.
S/R: supported if the paired IQM difference CI excludes 0 in PPO's favour.

**RQ3 — Does recurrent memory help?**
H: with an explicit `RevealedStore`, an LSTM adds no significant benefit; without it, an LSTM helps.
IV: memory type (explicit store / LSTM / both / none). DV: reward, F1, steps. C: 2×2 design.
L: raw-JSON recurrence is expensive. S/R: supported if store-only is not significantly worse than
store+LSTM and LSTM-only is significantly worse than store-only.

**RQ4 — Does hierarchical action representation improve learning?**
H: Approach 1+3 learns faster and generalises better than the flat factorised Approach 2.
IV: action representation. DV: AUC, final reward, `ood-*` gaps. C: equal budgets and demos.
L: Approach 3 receives more symbolic help, which is confounded with hierarchy; mitigated by RQ6.
S/R: CI on the AUC difference.

**RQ5 — Does curriculum learning improve generalisation?**
H: a mixture curriculum (clean → single → multiple → interacting → heavy distractors, all levels kept at
non-zero probability) improves `ood-combination` and `ood-distractor` results over uniform sampling, while
a strictly sequential curriculum suffers from forgetting (Bengio et al. 2009 frame curricula as
easy-to-hard ordering).
IV: sampling schedule. DV: OOD rewards, clean-episode false-positive rate. L: curriculum order can shift
the learned prior p(clean); report the clean-episode FP rate separately.
S/R: OOD reward CI for mixture > uniform.

**RQ6 — Neuro-symbolic vs purely learned validation.**
H: removing symbolic primitives (amounts and dates computed by the network, ids by pointer heads) sharply
reduces exact TPs, especially for `fx_rate` and `payment_allocation`.
IV: primitive set (full / no FX conversion / no date conversion / none). DV: per-type TP rate, near-miss
profile (amount vs ids). L: the full-primitive agent risks trivialisation; reported as a gap to the
reference auditor. S/R: per-type TP-rate CIs.

**RQ7 — Generalisation to unseen anomaly combinations.**
H: agents trained without `fx_rate`+`period_attribution` co-occurrence and without S2 keep ≥ 90 % of their
in-distribution F1 on `ood-combination`.
IV: train/test combination split. DV: F1 gap, per-type FN. L: types themselves are always seen; only
combinations are held out. S/R: the lower CI bound of the F1 ratio is ≥ 0.9.

**RQ8 — Accuracy under reduced inspection.**
H: under self-imposed budgets (≤ 12, ≤ 8 steps), a learned acquisition policy keeps higher F1 than (i) a
truncated fixed-order scan and (ii) a random-order scan with the same budget.
IV: acquisition policy × budget. DV: F1, official reward, coverage. L: the official reward gives
acquisition little headroom; this is a research regime. S/R: paired F1 CI at each budget.

**RQ9 — Does PPO from scratch collapse to silence?**
H (H-collapse): from random initialisation PPO converges to immediate empty submission (reward ≈ 2·p_clean − 1).
IV: training steps. DV: fraction of episodes with an empty first-step submission; reward vs silent.
L: depends on exploration settings; report several entropy coefficients. S/R: supported if ≥ 4/5 seeds
end within 0.05 of the silent reward with ≥ 90 % immediate empty submissions.

**RQ10 — Can the policy rules be learned from the official reward?**
H: an agent that must choose the valuation convention (local / UTC / as-written; issue / due) learns the
policy-correct one from terminal reward alone, though more slowly than with supervised labels.
IV: training signal (official reward vs supervised labels). DV: convention accuracy, per-type TP rate,
sample count. L: the reward is shared by all findings in an episode. S/R: convention accuracy ≥ 95 % on
`test-iid` for the reward-only agent.

**RQ11 — Robustness to presentation and red herrings.**
H: agents with set encoders are invariant to record order and ids (metamorphic agreement ≥ 99 %) and lose
≤ 10 % F1 on `ood-distractor`. IV: encoder type (set vs sequence). DV: metamorphic agreement, F1 gap.
S/R: CI thresholds as stated.

**RQ12 — Calibration.**
H: per-candidate confidences are miscalibrated after RL fine-tuning; temperature scaling on `research/val`
(Guo et al. 2017) reduces ECE without changing official reward. DV: ECE, reliability diagram, official
reward. L: confidences live outside the official schema. S/R: ECE CI before vs after scaling.

## 6. Ablations

| ablation | removes | tests |
|---|---|---|
| no explicit memory | `RevealedStore` (observation-only policy) | RQ3 |
| primitive ablations | FX conversion, timezone conversion, grouping | RQ6 |
| single-convention features | multi-convention alternatives | trivialisation risk, RQ10 |
| demonstration diversity | randomised demonstrators → single fixed demonstrator | RQ1 |
| auxiliary supervised loss | label-based candidate loss during RL | RQ1, RQ10 |
| research-only shaping | potential-based shaping over agent-visible coverage (Ng, Harada & Russell 1999) | sparse-reward handling; **never** reported as official reward |
| sequence vs set encoder | permutation invariance | RQ11 |
