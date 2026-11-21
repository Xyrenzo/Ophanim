# Evaluation protocol

## Splits and seeds

| split | where | seeds | purpose |
|---|---|---|---|
| train | `configs/train/suite.json` → `data/train/` | explicit, 1001–1010 | open training episodes (truth published) |
| dev | `configs/dev/suite.json` → `data/dev/` | explicit, 2001–2010 | open development episodes, different parameter combinations |
| eval | `configs/eval/official_suite.json` | **derived at run time**: `int(sha256(f"{seed_base}|eval|{i}")[:15], 16)` | closed evaluation; seeds never stored in the repo |

Closed runs additionally key generation with `OPHANIM_EVAL_SECRET` (HMAC). Hidden seeds alone are not the
only defence against over-fitting: the evaluation suite uses **parameter combinations that appear in
neither train nor dev** (test-enforced) and **harmless transformations** (shuffled order, company-offset
timestamps). Error types are fixed and public; no new type is ever added.

## Official structure (`ophanim evaluate`)

1. **20 episodes** — 5 clean, 5 with interacting errors (S1, S2, S1+S2, S1+fx+period, S2+dup+alloc),
   10 mixed (every mandatory type appears in ≥ 5 of them; up to 12 issues). Each is independently
   verified (`audit/`): clean before mutation, exactly the declared issues after, sufficient evidence.
2. **The same four baselines on the same 20 episodes**, closed mode, same versions, same machine:
   * random explorer (policy seed 0), simple reconciliation, mark-everything — each run as a separate
     agent process through `agent_runtime.py`;
   * oracle — evaluator-side only, submits the truth with valid evidence and 0 inspection steps.
   * (extra row) reference auditor — scripted public-data solver.
3. **20 metamorphic pairs** — each eval config with an independently derived seed, paired with a variant
   that changes record order and every public id, and names and/or timestamp representation. Checks: ids
   really changed; truth equivalent after id mapping; both variants verify; the mapped oracle answer earns
   1.0 in both; the reference auditor earns the same reward with the same steps/TP/FP.
4. **Exact reproducibility** — every episode replayed with the same seed/config/actions (random explorer
   and reference auditor) must give byte-identical trajectories.
5. **Report** — `report.json`, `report.md`, public trajectories per policy, evaluator-only judge log.

## Plugging in other policies (organisers)

Any executable that speaks the JSON-lines protocol can be evaluated (see `src/ophanim/agent_runtime.py`):

```
evaluator -> agent  {"type": "reset", "observation": {...}, "info": {...}}
agent -> evaluator  {"action": {"action": "list_records", "table": "ledger", "cursor": null, "limit": 50}}
evaluator -> agent  {"type": "step", "observation": {...}, "reward": 0.0, "terminated": false, "truncated": false, "info": {}}
...
evaluator -> agent  {"type": "end"}
```

In Python: `run_episode_isolated(OphanimEnv(mode="eval", secret=...), ["python", "my_agent.py"], seed, config)`
or in-process `run_episode(env, policy, seed, config)` for any object with `reset(obs, info)` and `act(obs)`.

## Commands

```bash
python -m ophanim verify                                   # tests + published data + trajectories + closed evaluation
OPHANIM_EVAL_SECRET=<secret> python -m ophanim evaluate --seed-base <hidden-base>
python -m ophanim verify-episode data/train/train-06-all-four
python -m ophanim build-data                               # regenerate data/ (byte-identical)
```
