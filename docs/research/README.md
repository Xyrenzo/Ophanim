# P6 — Research foundation (index)

Read in this order. Binding constraints come first; the research documents build on them.

| # | document | content |
|---|---|---|
| 1 | [p6_official_compliance_audit.md](p6_official_compliance_audit.md) | audit against the official check definitions (2026-11-20): blocking gaps, non-compliant conventions, fix order |
| 2 | [p6_traceability_matrix.md](p6_traceability_matrix.md) | every official requirement (adapter, C01–C20, D01–D20, tests 1–20, M01–M12, P01–P20, engineering) → file, status, evidence, required change, priority |
| 3 | [p6_architecture_constraints.md](p6_architecture_constraints.md) | binding interface, isolation, matcher and data constraints for all future work |
| 4 | [p6_repository_audit.md](p6_repository_audit.md) | what the code actually does: lifecycle, observations, the five tools, reward, baselines, measurements, discrepancies |
| 5 | [p6_problem_formulation.md](p6_problem_formulation.md) | POMDP formulation, structural properties, action space, research problems |
| 6 | [p6_algorithm_review.md](p6_algorithm_review.md) | BC/DAgger, PPO, DQN family, recurrent PPO, Decision Transformer, offline RL, neuro-symbolic, LLM agents; frameworks |
| 7 | [p6_agent_architecture.md](p6_agent_architecture.md) | proposed agent architecture: information boundary, action/observation representation, memory, interfaces |
| 8 | [p6_experiment_protocol.md](p6_experiment_protocol.md) | data separation, metrics, statistics, 12 research questions, ablations |
| 9 | [p6_implementation_roadmap.md](p6_implementation_roadmap.md) | P6-C compliance fixes, then P7–P13 with acceptance criteria |
| 10 | [p6_references.md](p6_references.md) | verified references and documentation pages |

Evidence (re-runnable, read-only): [`evidence/p6_official_checks.py`](evidence/p6_official_checks.py)
→ [`evidence/p6_official_checks.out.txt`](evidence/p6_official_checks.out.txt);
[`evidence/p6_measure.py`](evidence/p6_measure.py) → [`evidence/p6_measure.out.json`](evidence/p6_measure.out.json).
Run from the repository root with `PYTHONPATH=src python docs/research/evidence/<script>.py`.

Nothing in `src/`, `tests/`, `configs/` or `data/` was modified during P6.
