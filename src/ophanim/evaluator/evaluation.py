"""Closed evaluation of the environment (evaluator side).

One call runs the official structure from configs/eval/official_suite.json:

  1. data      - generate the 20 episodes from hidden seeds (seed base + secret) and
                 independently verify truth and evidence for each;
  2. baselines - run the same four policies on the same 20 episodes: random explorer
                 (fixed seed), simple reconciliation, mark-everything (each in a separate
                 agent PROCESS, closed mode), and the evaluator-side oracle. The scripted
                 reference auditor is reported as an extra row;
  3. metamorphic - 20 paired checks (order + ids + names/timestamps changed);
  4. reproducibility - every episode is replayed with the same seed and actions and
                 compared byte for byte;
  5. report    - report.json + report.md (P, R, F1, return, steps, time per policy,
                 failure analysis), public trajectories, evaluator-only judge log.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from ophanim.analytics import TrajectoryLogger
from ophanim.env.environment import OphanimEnv
from ophanim.evaluator.metamorphic import check_pair
from ophanim.evaluator.oracle import OraclePolicy
from ophanim.evaluator.process_runner import agent_command, run_episode_isolated
from ophanim.evaluator.runner import run_episode
from ophanim.evaluator.verifier import verify_generated
from ophanim.generator.episode import generate_episode
from ophanim.policies import make_policy
from ophanim.version import ENV_VERSION

BASELINES = ("random_explorer", "simple_reconciliation", "mark_everything")
DEFAULT_SEED_BASE = "ophanim-public-demo-2026"


def derive_seed(seed_base: str, split: str, index: int) -> int:
    return int(hashlib.sha256(f"{seed_base}|{split}|{index}".encode("utf-8")).hexdigest()[:15], 16)


def load_suite(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def secret_from_environment() -> bytes | None:
    value = os.environ.get("OPHANIM_EVAL_SECRET")
    return value.encode("utf-8") if value else None


def _mean(xs) -> float:
    xs = list(xs)
    return round(statistics.mean(xs), 4) if xs else 0.0


def _summarise(records: list[dict]) -> dict:
    tp, fp, fn = (sum(r[k] for r in records) for k in ("tp", "fp", "fn"))
    return {
        "episodes": len(records),
        "mean_return": _mean(r["reward"] for r in records),
        # Micro-averages over all findings/issues (clean episodes contribute nothing).
        "micro_precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
        "micro_recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
        "micro_f1": round(2 * tp / (2 * tp + fp + fn), 4) if 2 * tp + fp + fn else 1.0,
        "mean_precision": _mean(r["precision"] for r in records),
        "mean_recall": _mean(r["recall"] for r in records),
        "mean_f1": _mean(r["f1"] for r in records),
        "mean_steps": _mean(r["steps"] for r in records),
        "mean_inspection_steps": _mean(r["inspection_steps"] for r in records),
        "mean_runtime_seconds": _mean(r["runtime_seconds"] for r in records),
        "tp": sum(r["tp"] for r in records), "fp": sum(r["fp"] for r in records), "fn": sum(r["fn"] for r in records),
        "truncated": sum(1 for r in records if r["truncated"]),
        "invalid_submissions": sum(1 for r in records if r["outcome_reason"] == "invalid_submission"),
    }


def _trace_hash(seed: int, config: dict, policy_name: str, secret: bytes | None) -> str:
    logger = TrajectoryLogger()
    run_episode(OphanimEnv(mode="train", secret=secret), make_policy(policy_name), seed, config, logger)
    return hashlib.sha256("\n".join(logger.lines).encode("utf-8")).hexdigest()


def run_evaluation(suite_path: str | Path, out_dir: str | Path, seed_base: str = DEFAULT_SEED_BASE,
                   secret: bytes | None = None, isolate: bool = True) -> dict:
    suite = load_suite(suite_path)
    out = Path(out_dir)
    (out / "trajectories").mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    episodes = [{"id": e["id"], "category": e["category"], "config": e["config"],
                 "seed": derive_seed(seed_base, "eval", i)} for i, e in enumerate(suite["episodes"])]

    # 1. data and ground truth -------------------------------------------------------------
    data_checks = []
    sealed_by_id = {}
    for e in episodes:
        ep = generate_episode(e["seed"], e["config"], secret=secret)
        sealed_by_id[e["id"]] = ep.sealed
        rep = verify_generated(ep)
        e["episode_id"] = ep.public.episode_id
        e["issues"] = len(ep.sealed.truth.issues)
        e["issue_types"] = dict(Counter(t.type for t in ep.sealed.truth.issues))
        data_checks.append({"id": e["id"], "ok": rep.ok, "issues_declared": rep.issues_declared,
                            "issues_found_independently": rep.issues_found_independently,
                            "evidence_sets_checked": rep.evidence_sets_checked, "problems": rep.problems[:10],
                            "ledger_rows": ep.public.manifest["record_counts"]["ledger"],
                            "documents": ep.public.manifest["document_count"]})

    # 2. the same four baselines on the same 20 episodes -------------------------------------
    # Nothing evaluator-only touches the disk while agent processes run: judge logs and the
    # oracle trajectory (whose actions ARE the answers) are buffered and written at the end,
    # and the oracle runs last.
    records: dict[str, list[dict]] = defaultdict(list)
    judge_lines: list[str] = []
    loggers: dict[str, TrajectoryLogger] = {}
    order = (*BASELINES, "reference_auditor", "oracle")
    failure = {name: {"fp_reasons": Counter(), "fp_by_claimed_type": Counter(), "tp_by_type": Counter(),
                      "fn_types": Counter()} for name in order}
    for name in order:
        logger = loggers[name] = TrajectoryLogger()
        for e in episodes:
            env = OphanimEnv(mode="eval", secret=secret)
            if name == "oracle":
                rec = run_episode(env, OraclePolicy(sealed_by_id[e["id"]]), e["seed"], e["config"], logger)
            elif isolate:
                rec = run_episode_isolated(env, agent_command(name, 0), e["seed"], e["config"], logger, policy_name=name)
            else:
                rec = run_episode(env, make_policy(name, 0), e["seed"], e["config"], logger)
            row = rec.to_dict() | {"episode": e["id"], "category": e["category"]}
            records[name].append(row)
            log = env.evaluator_log()
            judge_lines.append(json.dumps({"policy": name, "episode": e["id"], "judge": log}))
            types_by_issue = {t.issue_id: t.type for t in sealed_by_id[e["id"]].truth.issues}
            for entry in log:
                if entry.get("event") == "scored":
                    for v in entry["verdicts"]:
                        if v["matched_issue"] is None:
                            failure[name]["fp_reasons"].update(v["reasons"])
                            failure[name]["fp_by_claimed_type"][v["claimed_type"]] += 1
                        else:
                            failure[name]["tp_by_type"][v["claimed_type"]] += 1
                    for iid in entry["unmatched_issues"]:
                        failure[name]["fn_types"][types_by_issue[iid]] += 1

    # All agent processes have finished: only now write evaluator-side artefacts.
    for name, logger in loggers.items():
        (out / "trajectories" / f"{name}.jsonl").write_text("".join(l + "\n" for l in logger.lines), encoding="utf-8")
    (out / "evaluator_log.jsonl").write_text("".join(l + "\n" for l in judge_lines), encoding="utf-8")

    summaries = {name: {"overall": _summarise(rs),
                        "by_category": {c: _summarise([r for r in rs if r["category"] == c]) for c in ("clean", "interacting", "mixed")}}
                 for name, rs in records.items()}

    # 3. metamorphic pairs --------------------------------------------------------------------
    variants = suite["metamorphic"]["variants"]
    pairs = []
    for i, e in enumerate(suite["episodes"]):
        seed = derive_seed(seed_base, "metamorphic", i)
        res = check_pair(seed, e["config"], variants[i % len(variants)], secret=secret)
        pairs.append({"id": e["id"], "ok": res.ok, "checks": res.checks})

    # 4. exact reproducibility -------------------------------------------------------------------
    repro = []
    for e in episodes:
        same = all(_trace_hash(e["seed"], e["config"], p, secret) == _trace_hash(e["seed"], e["config"], p, secret)
                   for p in ("random_explorer", "reference_auditor"))
        repro.append({"id": e["id"], "identical": same})

    report = {
        "env_version": ENV_VERSION,
        "suite": str(suite_path),
        "seed_base_sha256": hashlib.sha256(seed_base.encode()).hexdigest()[:16],
        "secret_used": bool(secret),
        "isolated_agent_processes": isolate,
        "platform": {"python": sys.version.split()[0], "system": platform.system(), "machine": platform.machine(),
                     "cpus": os.cpu_count()},
        "episodes": [{k: e[k] for k in ("id", "category", "episode_id", "issues", "issue_types")} for e in episodes],
        "data_checks": {"passed": sum(d["ok"] for d in data_checks), "total": len(data_checks), "details": data_checks},
        "policies": summaries,
        "failure_analysis": {n: {k: dict(v) for k, v in f.items()} for n, f in failure.items()},
        "metamorphic": {"passed": sum(p["ok"] for p in pairs), "total": len(pairs), "details": pairs},
        "reproducibility": {"passed": sum(r["identical"] for r in repro), "total": len(repro)},
        "episode_records": records,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(rep: dict) -> str:
    lines = [f"# OPHANIM evaluation report (env {rep['env_version']})", "",
             f"Python {rep['platform']['python']} on {rep['platform']['system']} {rep['platform']['machine']}, "
             f"{rep['platform']['cpus']} CPUs. Secret used: {rep['secret_used']}. "
             f"Agents in separate processes: {rep['isolated_agent_processes']}. Elapsed: {rep['elapsed_seconds']} s.", "",
             "## Checks", "",
             f"- Data and ground truth (independent verification): **{rep['data_checks']['passed']}/{rep['data_checks']['total']}**",
             f"- Metamorphic pairs (order + ids + names/timestamps): **{rep['metamorphic']['passed']}/{rep['metamorphic']['total']}**",
             f"- Exact reproducibility (same seed + actions): **{rep['reproducibility']['passed']}/{rep['reproducibility']['total']}**", "",
             "## Baselines on the same 20 episodes (diagnostics)", "",
             "Precision/recall are micro-averaged over all findings; F1 is the mean per-episode F1 used by the reward "
             "(clean episodes: F1 = 1 for an empty answer).", "",
             "| policy | mean return | precision | recall | mean F1 | mean steps | runtime s | TP | FP | FN |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, s in rep["policies"].items():
        o = s["overall"]
        lines.append(f"| {name} | {o['mean_return']:+.3f} | {o['micro_precision']:.3f} | {o['micro_recall']:.3f} | {o['mean_f1']:.3f} | "
                     f"{o['mean_steps']:.1f} | {o['mean_runtime_seconds']:.3f} | {o['tp']} | {o['fp']} | {o['fn']} |")
    lines += ["", "### Mean return by category", "", "| policy | clean | interacting | mixed |", "|---|---:|---:|---:|"]
    for name, s in rep["policies"].items():
        b = s["by_category"]
        lines.append(f"| {name} | {b['clean']['mean_return']:+.3f} | {b['interacting']['mean_return']:+.3f} | {b['mixed']['mean_return']:+.3f} |")
    lines += ["", "## Failure analysis", "",
              "| policy | TP by type | FP by claimed type | missed (FN) by type | rejection reasons (best candidate) |",
              "|---|---|---|---|---|"]
    for name, f in rep["failure_analysis"].items():
        lines.append(f"| {name} | {f['tp_by_type'] or '-'} | {f['fp_by_claimed_type'] or '-'} | {f['fn_types'] or '-'} | "
                     f"{f['fp_reasons'] or '-'} |")
    lines += ["", "The oracle reads the hidden truth and only shows that the evaluator can award the maximum; "
              "its score says nothing about difficulty. The reference auditor is a scripted public-data solver.", ""]
    return "\n".join(lines)
