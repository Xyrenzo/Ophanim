# OPHANIM — design note

## What it is

A reinforcement-learning environment in which an agent audits the accounts-payable books of a fictional
company for one month and submits evidence-backed findings. The environment produces the data, hides the
answer, exposes narrow read-only tools, and scores the answer with one deterministic matcher and the
official reward. It never trains a model; it provides the interactions a policy could learn from.

## How an episode is made

1. **Financial DNA.** A seed picks one of six business profiles (retail, trading, software,
   manufacturing, logistics, consulting), a base currency (ten currencies, including 0- and 3-decimal
   ones), a fixed company UTC offset and a month.
2. **Consistent hidden history.** Suppliers, invoices (this month and open ones from last month),
   payments (full, split, partial, batch, unidentified) and daily FX rates, plus legitimate red herrings.
3. **Correct books.** A posting engine turns documents into balanced base-currency ledger rows; a
   self-check asserts the accounting equalities. The clean books are snapshotted into provenance.
4. **Causal errors.** Each error is a realistic mistake applied as a transformation of the correct books:
   a supplier invoice captured twice; a remittance line parked in Suspense; a document converted at the
   rate of the wrong date; a document from the adjacent month assigned to this period because the system
   used the UTC date. Every injected issue records its exact misstatement (base-currency minor units), the
   affected documents, the allowed evidence sets and a before/after provenance entry. Two interacting
   scenarios combine FX and allocation errors on linked documents so that one error changes the correct
   amount of the other.
5. **Presentation.** Random public ids, names, record order and timestamp representation come from a
   separate random stream, which is what makes metamorphic variants possible.

## Why the answer can be trusted

An **independent auditor** (`ophanim.audit`) — standard library only, no generator code, AST-enforced —
re-implements the published policy from `policy.json`. For every generated episode the verifier requires:
zero discrepancies in the clean books, exactly the declared issues after mutation (nothing missing,
nothing extra, no anomalies), and that each allowed evidence set alone proves its issue and amount.
A scripted agent built on the same auditor solves every episode through the tools in ~20 steps, which
shows the truth is recoverable from accessible records and that no unavailable fact is ever required.

## Why the reward is hard to game

Findings are matched one-to-one on exact type, exact id set, exact amount (τ = 0 by default), exact currency and a
complete evidence set of existing ids; explanations are ignored; repeats are false positives; malformed
input is −1. The tests in `tests/adversarial` reproduce each attack from the case (silence, false
accusations, duplicates, mark-everything, guessed ids, fabricated evidence, wrong currency, invalid input,
repeated submission, time-outs, inspection cost, persuasive text) against the real environment.

## Why the hidden data stays hidden

Tools see only public tables; errors are fixed strings; in closed mode rewards are withheld; agents run as
separate processes with a scrubbed environment and an empty working directory; closed-run generation is
keyed with a secret so the open-source generator cannot be used to brute-force hidden seeds; evaluator
outputs are written only after all agents have finished.

## Reproducibility

A SHA-256 counter-mode RNG with named sub-streams replaces Python's `random` module (whose helpers may
change between versions). Golden values are pinned and the suite runs on Python 3.11 and 3.14; complete
episodes hash identically on both. Published train/dev data regenerates byte-for-byte from `configs/`.

## Key trade-offs

* **Accounts payable only** — enough for all four mandatory types; keeps the model small and verifiable.
* **Fixed UTC offsets, no DST** — removes OS tz-database differences; period errors still require
  UTC-vs-local reasoning (half-hour and negative offsets included).
* **Strict schema** — a lowercase currency code or a string amount is −1. Strictness is predictable and
  closes parsing loopholes, at the cost of being unforgiving to sloppy agents.
* **Evidence must cite row_id / doc_id / FX key** — invoice_id is not accepted as evidence. One clear rule,
  no alias table to exploit.
* **Pydantic only at run time** — no NumPy/NetworkX; the "investigation graph" is the explicit
  invoice ↔ posting ↔ payment ↔ FX linkage inside the injector and the auditor, never exposed to the agent.

## Limitations (honest)

* Process isolation is not an OS sandbox; a hostile agent shares the filesystem (closed-run truth is never
  on disk during the run; open train/dev truth is, by design).
* The official formula scores silence and wild accusations equally (−1) on erroneous books; with many
  issues, saving steps can outweigh one missed issue (see `reward_design.md`).
* A rule-based auditor with the published policy solves the episodes: difficulty is reasoning under a step
  budget and red herrings, not hidden information. LLM-agent difficulty was not measured.
* Ledger sizes are at the lower end of the suggested range (≈150–430 rows); the largest episodes slightly
  exceed 200 documents.
* No model was trained; no learning improvement is claimed.
* Reward and environment are a software exercise, not a professional audit opinion.
