# P6.4 / P6.8 — Agent architecture (proposal)

This is a design for P7–P10. Nothing here is implemented yet. The official environment, reward, findings
schema, matcher, evaluator and baselines stay unchanged; every new component sits **on the agent side**
of the existing JSON interface or in research-only tooling.

**Binding constraints first.** `p6_architecture_constraints.md` (derived from the official check
definitions) overrides this document where they differ. In particular:
* agents act through the `judge_adapter` envelope `{"name", "args"}`;
* ids are copied exactly, never normalised;
* amounts are exact (τ = 0);
* the closed-mode environment holds no truth;
* learning is possible only in train mode.

## 1. Information boundary

| category | examples | may reach the acting agent? | may reach training code? |
|---|---|---|---|
| Public observations | tool outputs, task text, manifest, policy | yes | yes |
| Agent memory | revealed-record store, candidates, features, drafts | yes (it is the agent) | yes |
| Training labels | truth of **open** train/dev/research episodes | **never at act time** | yes, via `LabelProvider` only, for supervised losses |
| Evaluator-only truth | truth of secret-keyed / official episodes | never | never |
| Provenance | seeds, id maps, injections, clean snapshots | never | never (except offline analysis scripts) |
| Official evaluation outputs | judge logs, reports, oracle trajectories | never | never |

Rules (to be enforced by tests in P7): agent packages may not import `ophanim.generator`,
`ophanim.evaluator` or `ophanim.audit.reconcile`; learning code may read labels only through
`LabelProvider`, which refuses secret-keyed episodes; official evaluation always runs agents through the
existing process boundary (`evaluator/process_runner.py`). The in-process `OphanimEnv` must never be
handed to agent code because it exposes `evaluator_*` accessors and the judge (`env/environment.py`
L134–L160); training uses a `PublicEnv` facade (§6).

## 2. Layers

```
L0  official interface (unchanged): OphanimEnv / agent_runtime JSON-lines protocol
L1  PublicEnv facade (reset/step only)  ── training-time access, open splits only
L2  agent memory: RevealedStore (typed, keyed record store; the sufficient statistic, P1)
L3  action adapter: macro acquisition actions + candidate-selection submission
L4  symbolic primitives (time, money, FX, grouping, structural links)   ── no procedures
L5  candidate generator + feature extractor (built from L4 only)
L6  finding builder (schema-valid findings from decisions, per the public task text)
L7  policy (learned): acquisition head, candidate heads, valuation-convention head, stop head
```

## 3. Action representation — three approaches

**Approach 1 — hierarchical.** A high-level choice among {scan table *t*, fetch FX key, inspect document,
stop-and-submit}, with low-level parameters filled per option. "Scan table *t*" is an option in the sense of
Sutton, Precup & Singh (1999): it advances the cursor of *t* by one page.

**Approach 2 — factorised / autoregressive.** `π(tool, args | o) = π(tool | o) · Π_i π(arg_i | tool, arg_<i, o)`,
with pointer heads (Vinyals, Fortunato & Jaitly 2015) over the revealed ids for id arguments, and an
autoregressive decoder that emits findings one field at a time.

**Approach 3 — learned decisions, deterministic arguments.** The policy chooses *what* to do (which table,
which candidate, which type, which valuation convention); deterministic code fills bookkeeping arguments
(cursor, limit = 50, FX-key string, evidence assembly, JSON serialisation).

| criterion | 1 hierarchical | 2 factorised / autoregressive | 3 learned decisions + deterministic args |
|---|---|---|---|
| PPO compatibility | good (categorical + masks) | good but long autoregressive chains, high variance | good (categorical + Bernoulli heads with masks) |
| DQN compatibility | good for the macro level | poor (huge joint argument space) | good for DRRN-style candidate scoring |
| Imitation learning | good | good but needs many demos per field | good |
| Sample efficiency | high at macro level | low | high |
| Complexity | low | high | medium |
| Leakage risk | low | low | **medium**: deterministic helpers could encode the answer |
| Generalisation | good across sizes (masks) | pointer heads generalise to new ids | good, *if* candidates/features stay generic |
| Task-trivialisation risk | low | lowest | **must be controlled** (primitives, not procedures) |

**Recommendation (hybrid).** Approach 1 for acquisition, with deterministic bookkeeping arguments only
(cursor continuation, limit 50). Approach 3 for submission, through generic candidates and a learned
valuation-convention choice. Approach 2 is retained as the "minimal symbolic help" research variant
(RQ6). To keep Approach 3 honest, every deterministic helper that could encode a decision instead offers
the alternatives as **separate options**. Example: "fetch the FX rate for a document" is offered for the
local accounting date, the UTC date, the date as written, and the due date, and the policy must learn
which one is correct.

## 4. Observation representation and memory

Environment state (owned by the environment, never copied into the agent): the public dataset, the
step counter, the hidden truth. Agent memory (owned by the agent, rebuilt from observations only):

| component | content | source |
|---|---|---|
| `RevealedStore` | every record returned so far, keyed by id, per table; cursor per table; first-seen step | step observations |
| acquisition state | fraction read per table, pages read, steps used, remaining-step fraction, elapsed fraction | store + observation `remaining_steps` |
| candidates | generic structural units (below) | L5 over the store |
| candidate features | primitive outputs under several conventions | L4 over the store |
| draft findings | decisions taken so far (optional, for multi-pass submission) | policy |
| confidences | per-candidate probabilities, logged agent-side only | policy |

There is no observation history from the environment, so memory is not optional. Because the revealed
set is a sufficient statistic (problem formulation P1), the store *is* the belief. Recurrent networks
are an ablation, not a requirement.

**Generic candidates (structural only).** (a) pairs of invoices with the same `entity_id`;
(b) (payment, referenced invoice) pairs from `invoice_refs`; (c) each posted invoice document; (d) each
posted payment document. Candidate generation must not filter by any discrepancy criterion.

**Features (computed by primitives, multi-convention).** Examples: vendor-ref equality, content equality,
presence of a reversal; booked base amount vs conversion at {local, UTC, as-written, due} date;
in-period under {local, UTC, as-written} date; AP applied for (payment, invoice) vs the line converted
under each convention; Suspense rows on the payment. The policy must learn which features define a
discrepancy and which conventions the policy text implies. Features are **inputs**, never labels.

**Set encoders.** Candidates and records are unordered and variable in number. Use permutation-invariant
encoders (Deep Sets, Zaheer et al. 2017) or attention pooling, plus masks for absent or unknown items. This
also gives invariance to record order and ids by construction, which is checked with the existing
metamorphic variants.

## 5. Finding builder and amounts

For a chosen (type, candidate, convention), the builder computes the claimed amount with the chosen
convention (for example |booked − convert(total, rate at the chosen date)|). It assembles evidence by the
rule the **public task text** states for that type, and validates the finding against the official
`FindingsSubmission` schema *before* submitting. Applying public rules is not leakage. Choosing which rule
applies is the agent's decision. The amount is never regressed by a neural network: exactness (±1 minor
unit) comes from symbolic arithmetic.

## 6. Proposed interfaces (Python protocols; P7)

```python
class PublicEnv(Protocol):                       # facade: no evaluator accessors, no _state
    def reset(self, seed: int, config: dict) -> tuple[dict, dict]: ...
    def step(self, action: dict) -> tuple[dict, float, bool, bool, dict]: ...

class RevealedStore:                             # agent memory
    def ingest(self, observation: dict) -> None: ...
    def records(self, table: str) -> list[dict]: ...
    def get(self, record_id: str) -> dict | None: ...
    def coverage(self) -> dict[str, float]: ...

class CandidateGenerator(Protocol):
    def generate(self, store: RevealedStore) -> list["Candidate"]: ...

class FeatureExtractor(Protocol):
    def features(self, c: "Candidate", store: RevealedStore) -> "Features": ...

class ActionAdapter(Protocol):
    def encode(self, store: RevealedStore) -> tuple["PolicyInput", "Masks"]: ...
    def decode(self, decision: "PolicyOutput", store: RevealedStore) -> dict: ...   # official JSON action

class FindingBuilder(Protocol):
    def build(self, c: "Candidate", type_: str, convention: str, store: RevealedStore) -> dict: ...

class LabelProvider(Protocol):                   # training only, open splits only
    def labels(self, episode_ref: "EpisodeRef", candidates: list["Candidate"]) -> list["Label"]: ...
```

Agents keep implementing the existing `Policy` protocol (`policies/base.py`: `reset`, `act`), so every
learned agent runs unchanged in `run_episode`, `run_episode_isolated` and the official evaluation.

## 7. Security review checklist for every adapter (P7 acceptance)

1. Imports: no `ophanim.generator`, `ophanim.evaluator`, `ophanim.audit.reconcile` in agent code (AST test).
2. Inputs: every feature is a function of `RevealedStore` + reset observation (property test: features are
   identical when the hidden truth is altered but the public data is not).
3. No caching across episodes of anything keyed by episode content (reset isolation test).
4. Labels only via `LabelProvider`; it raises for episodes generated with a secret.
5. Logs: agent-side logs contain public data and agent decisions only (leak scan, as for trajectories).
6. Official runs: the agent is launched through `agent_runtime`/`process_runner`; no in-process shortcut.

## 8. Mapping to the repository

| proposed | relationship to existing code | create in |
|---|---|---|
| `src/ophanim/agents/` (memory, adapters, primitives, candidates, builder) | uses `policies/base.py` protocol; pure Python, no new dependency | P7 |
| `src/ophanim/research/` (suites with seed namespaces, research metrics, statistics) | reads public trajectories and judge logs; reuses `derive_seed`; never imported by the official evaluator | P7 / P11 |
| `src/ophanim/learning/` (datasets, BC, DAgger, PPO, checkpoints) | depends on optional `[learning]` extra (PyTorch) | P8 / P9 |
| `experiments/` (research configs, runners, reports) | separate from `configs/` (official suites) | P8 |
| existing `env/`, `evaluator/`, `schemas.py`, `policies/`, `configs/` | **unchanged** | — |

Directories for transformers, offline RL and LLM agents are not created until the corresponding research
question is scheduled (P11/P12).

**Testing requirements per component:** unit tests for primitives (exact arithmetic, offsets, rounding,
agreement with the published policy on the train split); property tests for candidate generation
(complete coverage of the structural units, no filtering); leakage tests (§7); metamorphic invariance
(identical decisions up to id mapping); end-to-end episodes through `run_episode_isolated`; the full
existing suite must still pass unchanged.
