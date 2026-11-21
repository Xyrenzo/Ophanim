# P6.3 — Algorithm review

Citations refer to `p6_references.md`; every cited item was checked against its primary page during P6.
"Measured" means measured on this repository (`p6_repository_audit.md` §9). Statements marked
**hypothesis** are predictions to be tested in P8–P11, not results.

All recommendations are subject to `p6_architecture_constraints.md`, which records the binding contract
from the official check definitions:
* the agent interface is the `judge_adapter` envelope;
* ids are exact and amounts use τ = 0;
* learning happens in train mode only;
* Gymnasium is not required.

No framework is selected before that interface; the frameworks below are judged as optional wrappers
around it.

The review is driven by four measured properties of Ophanim (`p6_problem_formulation.md` §3):
(1) acquisition has little headroom under the official reward (full scan = 12–22 steps on medium);
(2) the terminal action is a set of exact structured findings (pointer arguments, ±1 minor unit);
(3) the reward is sparse, clipped and flat at −1 for every policy without a true positive;
(4) "submit nothing" earns −0.5 on the closed suite.

## A. Behaviour cloning (BC) and DAgger

**Mechanism.** Supervised learning of `π(a | o)` from expert demonstrations (ALVINN, Pomerleau 1988).
Ross & Bagnell (2010) show that i.i.d. imitation "leads to compounding errors and a regret bound that
grows quadratically in the time horizon"; DAgger (Ross, Gordon & Bagnell 2011) iteratively aggregates
states visited by the learner, labelled by the expert, with no-regret guarantees under the learner's own
state distribution.

**Ophanim.**
* *Reference auditor as demonstrator.* Its acquisition actions are a deterministic function of table
  sizes (`policies/reference_auditor.py` L34–L47): imitating them teaches a counter, not a strategy. Its
  submission is a correct, observation-consistent label for finding construction. → Use it for the
  **submission** sub-policy only.
* *Teaching tool selection without fixed patterns* requires **diverse demonstrators**: randomised table
  order, targeted FX lookups via constructible keys, early-stop variants, partial scans — all
  observation-consistent. Diversity must be measured (action-sequence entropy), not assumed.
* *Queryable expert (DAgger).* The published rules can label any learner state: for submission, apply
  the rules to the learner's revealed records `K_t`; for acquisition, a rule such as "next unread page /
  next needed FX key". So DAgger is implementable without privileged information.
* *Privileged teachers.* A teacher that knows where the errors are acts on information the student
  cannot see — the problem analysed by Warrington et al. (2021) ("the expert does not know what the
  trainee cannot see"; their A2D trains the expert for the student) and named the *imitation gap* by
  Weihs et al. (2021, ADVISOR). Learning by Cheating (Chen et al. 2019) works when the student can observe
  what it needs; in Ophanim a privileged teacher is admissible **only** if it first reads every record it
  relies on. The **oracle never qualifies** (it submits ids it never revealed).
* *Incorrect demonstrations.* Score every demonstration on the training split; filter or weight by
  outcome; use simple-reconciliation outputs as labelled hard negatives (225 FP measured on the closed
  suite show exactly which red herrings fool shallow rules).

**Verdict.** First learning stage (P8), on a factorised policy (§G): BC for submission decisions,
BC+DAgger for acquisition with diverse demonstrators.

## B. PPO

**Mechanism.** Clipped surrogate objective allowing several minibatch epochs per batch of on-policy data
(Schulman et al. 2017), usually with GAE advantages (Schulman et al. 2015). Results depend strongly on
implementation choices (Engstrom et al. 2020; Andrychowicz et al. 2020); Huang et al. (2022) catalogue 37
implementation details including MultiDiscrete and LSTM specifics. Masking invalid actions in policy
gradients is theoretically justified and matters more as the invalid set grows (Huang & Ontañón 2020).

**Ophanim.** Compatible once actions are factorised: categorical heads for tool/table, pointer or
per-candidate Bernoulli heads with masks for ids, a categorical "valuation convention" head (§G).
On-policy sample cost is affordable: an episode is generated in 21–43 ms (measured, P5).
Main risk: property (3). **Hypothesis H-collapse:** PPO from a random initialisation converges to
immediate empty submission (−0.5 on the closed mix), because only the clean/erroneous split produces
return variance. Mitigations: BC initialisation, curriculum, research-only auxiliary losses.

**Verdict.** Primary RL algorithm (P9), initialised from BC; PPO-from-scratch is a required control.

## C. DQN / QR-DQN and parameterised-action variants

**Mechanism.** DQN learns Q-values with replay and target networks for discrete actions (Mnih et al. 2015);
QR-DQN learns return quantiles (Dabney et al. 2017). For discrete actions with *continuous* parameters:
PAMDP methods (Hausknecht & Stone 2015), P-DQN (Xiong et al. 2018), MP-DQN (Bester et al. 2019). For
variable action sets described by text, DRRN scores (state, action) embedding pairs (He et al. 2016).
DRQN adds recurrence for partial observability (Hausknecht & Stone 2015).

**Ophanim.** SB3's DQN supports Discrete actions only (verified). Ophanim's parameters are pointers into a
growing id set, not continuous vectors, so P-DQN/MP-DQN do not apply directly; the DRRN pattern (score each
admissible candidate) does. The terminal action is a *set*: per-candidate Q-values factorise a joint,
non-additive F1 reward, which value-based methods do not represent without further assumptions.

**Verdict.** Comparator, not first: (i) DQN/QR-DQN on a small discrete macro-action acquisition head;
(ii) a DRRN-style candidate scorer for submission. Addresses RQ2.

## D. Recurrent PPO

**Mechanism.** LSTM/GRU policies carry a hidden state across steps; DRQN shows recurrence helps under
partial observability (Hausknecht & Stone 2015). sb3-contrib provides RecurrentPPO (MlpLstmPolicy,
CnnLstmPolicy, MultiInputLstmPolicy; Dict actions not supported — verified). Hidden state must be reset at
every episode boundary.

**Ophanim.** Property P1: the revealed-record set is a sufficient statistic, so an explicit record store
removes the need for recurrence for *optimality*. Recurrence is still a legitimate design to compare
(learned vs explicit memory). Long sequences (≤100 steps, ~150 KB observations) make purely recurrent
encodings of raw JSON expensive.

**Verdict.** Ablation (RQ3), not first.

## E. Decision Transformer

**Mechanism.** Return-conditioned, causally masked Transformer over (return-to-go, state, action)
sequences (Chen et al. 2021). Paster, McIlraith & Ba (2022) show that such return-conditioned methods fail
when returns are driven by luck rather than actions. Hugging Face provides `DecisionTransformerModel` for
vector states (verified).

**Ophanim.** Dynamics are deterministic per episode, but achievable return varies across episodes, and
returns are bimodal (≈ −1 or ≈ 0.96 for scripted policies), giving little coverage of intermediate
returns. Scripted data has one dominant acquisition pattern. Observations are large JSON records that
need a learned encoder before any sequence model.

**Verdict.** Not first; optional P11 study once a diverse trajectory corpus exists.

## F. Offline RL (CQL, IQL) and off-policy evaluation

**Mechanism.** CQL regularises Q so it lower-bounds the policy's value (Kumar et al. 2020); IQL avoids
querying out-of-distribution actions by expectile regression on dataset actions and extracts a policy by
advantage-weighted BC (Kostrikov, Nair & Levine 2021). D4RL (Fu et al. 2020) and the OPE benchmarks
(Fu et al. 2021) standardise datasets and evaluation.

**Ophanim.** Offline RL is motivated by expensive or unsafe interaction. Ophanim's simulator is cheap and
exact, so online RL and exact on-simulator evaluation are available; OPE adds estimation error without
need. Offline RL becomes relevant only to reuse expensive logs (e.g. LLM-agent trajectories).

**Verdict.** Low priority; revisit only with an LLM-trajectory corpus (P12).

## G. Neuro-symbolic agents

**Mechanism.** Combining learned components with symbolic reasoning (survey: d'Avila Garcez & Lamb 2020).

**Ophanim.** The task demands exact arithmetic (±1 minor unit), exact id sets and exact evidence; neural
regression cannot guarantee these. The natural split:

| keep deterministic (symbolic primitives) | learn |
|---|---|
| parsing timestamps, converting to an offset, local date | which date convention defines correctness (local vs UTC vs date-as-written; issue vs due) |
| money conversion with exponents and the published rounding | which documents/postings to compare (candidate selection) |
| FX lookup by (date, currency); posting-group extraction by id | which discrepancy type, if any, a candidate represents |
| grouping/summing rows by key; structural links (refs, ids) | when to stop reading; which records to fetch |
| assembling the evidence set the published task text specifies for a type | whether to submit a candidate (precision/recall trade-off) |
| schema-valid finding serialisation | — |

**Trivialisation risk.** If the symbolic layer contains the end-to-end published procedure
(`audit.reconcile`), nothing is left to learn. Rule: **primitives, not procedures** — enforced by import
rules (agents may not import `ophanim.audit.reconcile`) and by ablations that remove primitives.

**Verdict.** Recommended agent architecture family (details in `p6_agent_architecture.md`).

## H. LLM tool-using agents

**Mechanism.** ReAct interleaves reasoning traces and tool actions (Yao et al. 2022); Toolformer teaches
an LM which API to call and with which arguments (Schick et al. 2023); WebShop is an analogous
tool/web environment where the best agent reached 29 % success vs 59 % for humans (Yao et al. 2022).

**Ophanim.** LLM agents can use the existing JSON-lines agent protocol (`agent_runtime.py`) with exactly
the same tools — no new privilege. Constraints: a medium full scan is ≈150 KB of JSON (measured; order
10⁴–10⁵ tokens by a rough bytes-per-token heuristic, not measured); the 60 s episode budget limits the
number of model calls; the official evaluation forbids network and paid APIs, so hosted LLMs can only run
in a **non-official research track** (local models are allowed if they meet the limits); sampling
non-determinism must be controlled and recorded (model id, decoding parameters). Contamination: the
published rules and code may be known to a model (legitimate public knowledge), but secret-keyed episodes
cannot be.

**Verdict.** Research track in P12, reported separately from the official benchmark.

## Comparison

| family | action-space fit | sparse-reward handling | data / compute | complexity | role |
|---|---|---|---|---|---|
| BC / DAgger | good (any factorised policy) | not needed (supervised) | cheap demos | low | **first (P8)** |
| PPO (+masks, factorised) | good with adapter | weak from scratch (H-collapse); good from BC | cheap simulator | medium | **primary RL (P9)** |
| DQN / QR-DQN / DRRN | macro actions or candidate scoring | replay helps; set reward awkward | cheap | medium | comparator (RQ2) |
| Recurrent PPO | as PPO | as PPO | higher | medium-high | ablation (RQ3) |
| Decision Transformer | needs encoders | needs return coverage | diverse corpus | high | optional (P11) |
| Offline RL (CQL/IQL) | as DQN/actor-critic | dataset-limited | logs | high | low priority |
| Neuro-symbolic | best: exact fields by construction | combines with BC/PPO | cheap | medium | **architecture family** |
| LLM tool agents | native (JSON tools) | in-context | expensive, slow | low code / high cost | research track (P12) |

## Frameworks (verified facts, then recommendation)

| framework | verified facts relevant here | assessment |
|---|---|---|
| PyTorch | Windows and Linux supported; `torch` 2.15.0 on PyPI requires Python ≥ 3.11 | needed for neural policies; large; **optional extra only** |
| Gymnasium | 1.4.0, Python ≥ 3.10, MIT; spaces include Text, Dict, Tuple, Sequence, Graph, OneOf | optional thin wrapper for library interoperability; not required by our own learners |
| Stable-Baselines3 | 2.9.2, Python ≥ 3.10, requires PyTorch ≥ 2.8; PPO actions: Box/Discrete/MultiDiscrete/MultiBinary; DQN: Discrete only; single-level Dict observations | good for sanity baselines on fixed adapters; cannot express pointer or set actions natively |
| sb3-contrib | "Experimental code"; MaskablePPO masks Discrete/MultiDiscrete/MultiBinary, no recurrent policies; RecurrentPPO has no Dict actions; QR-DQN available | MaskablePPO + MultiBinary over a padded candidate list is a cheap cross-check |
| RLlib (Ray) | "Ray on Windows is currently in beta"; install with PyTorch | distributed machinery unnecessary at this scale; Windows beta → **not selected** |
| CleanRL | "not a modular library and therefore it is not meant to be imported"; MIT; README lists Python < 3.11 | **adapt** its single-file PPO design (with attribution), do not depend on the package |
| HF Transformers | provides `DecisionTransformerModel` for vector states | only if the DT or local-LLM tracks are pursued |

**Recommendation:** a minimal stack — PyTorch as an optional `[learning]` extra, an in-repo PPO derived
from the CleanRL single-file design, optional SB3/sb3-contrib for cross-checks, Gymnasium only for an
optional wrapper. The official evaluation image keeps its current single runtime dependency (Pydantic).
