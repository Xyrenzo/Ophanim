"""Reproducible ablation and comparison study (evaluator side).

Runs every policy on the same fixed open episodes (``configs/ablation/suite.json``: explicit seeds, no
secret) and reports, per policy: precision, recall, F1, TP/FP/FN, mean reward and inspection steps; the same
metrics per error type; behaviour on clean episodes; and false positives that name a legitimate
red-herring document (one that is not itself the subject of an injected error).

Policy kinds are kept apart in the report:

  * baseline           - the official baselines (random explorer, simple reconciliation, mark everything);
  * scripted reference - the reference auditor, a hand-written procedure over public data;
  * scripted ablation  - the reference auditor with one ingredient removed (``policies/ablations.py``);
  * oracle             - evaluator-only, submits the sealed truth; a ceiling, not an agent.

No learned model is part of this study. Nothing is tuned on these episodes: the policies are fixed code.

Every episode is generated once, independently verified, and served to each policy through the closed-mode
environment (rewards withheld from the policy); the score comes from the shared judge afterwards. Policies
run in-process here because this is a measurement of scripted code, not an adversarial evaluation; the
official closed evaluation (``ophanim evaluate``) runs agents in separate processes.
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from ophanim.env.environment import OphanimEnv
from ophanim.evaluator.evaluation import load_suite
from ophanim.evaluator.oracle import OraclePolicy
from ophanim.evaluator.verifier import verify_generated
from ophanim.generator.episode import generate_episode
from ophanim.policies import ABLATION_POLICIES, POLICY_KINDS, make_policy
from ophanim.schemas import ERROR_TYPES
from ophanim.version import ENV_VERSION

DEFAULT_SUITE = Path(__file__).resolve().parents[3] / "configs" / "ablation" / "suite.json"
POLICIES: tuple[str, ...] = ("reference_auditor", *ABLATION_POLICIES, "simple_reconciliation", "random_explorer",
                             "mark_everything", "oracle")


def _kind(name: str) -> str:
    return "oracle (evaluator-only, reads truth)" if name == "oracle" else POLICY_KINDS[name]


def _prf(tp: int, fp: int, fn: int) -> dict:
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
            "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
            "f1": round(2 * tp / (2 * tp + fp + fn), 4) if 2 * tp + fp + fn else 1.0}


def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 4) if xs else 0.0


def _play(policy, ep) -> tuple[object, list[dict], list[dict]]:
    env = OphanimEnv(mode="eval")
    obs, info = env.reset_loaded(ep.public, ep.sealed)
    policy.reset(obs, info)
    submitted: list[dict] = []
    terminated = truncated = False
    while not (terminated or truncated):
        action = policy.act(obs)
        if isinstance(action, dict) and action.get("action") == "submit":
            submitted = list((action.get("findings") or {}).get("findings") or [])
        obs, _, terminated, truncated, _ = env.step(action)
    return env.evaluator_outcome(), env.evaluator_log(), submitted


def run_ablation(suite_path: str | Path = DEFAULT_SUITE, out_dir: str | Path | None = None,
                 policies: tuple[str, ...] = POLICIES) -> dict:
    started = time.perf_counter()
    suite = load_suite(suite_path)
    prepared = []
    data_problems: list[str] = []
    for e in suite["episodes"]:
        ep = generate_episode(e["seed"], e["config"])
        rep = verify_generated(ep)
        data_problems += [f"{e['id']}: {p}" for p in rep.problems[:3]]
        prov = ep.sealed.provenance
        # Red-herring documents that are still legitimate (not themselves the subject of an injected error).
        subjects = {i["details"][k] for i in prov["injections"] for k in ("original", "copy", "invoice", "payment")
                    if i["details"].get(k)}
        red = {prov["id_map"][k]: d["kind"] for d in prov["distractors"]
               for k in d.get("invoices", []) + d.get("payments", []) if k not in subjects}
        prepared.append({"meta": e, "ep": ep, "red": red,
                         "types": {t.issue_id: t.type for t in ep.sealed.truth.issues}})

    issues_by_type = Counter(t for p in prepared for t in p["types"].values())
    report: dict = {
        "study": "ophanim-ablation", "env_version": ENV_VERSION, "suite": str(Path(suite_path).name),
        "episodes": len(prepared), "categories": dict(Counter(p["meta"]["category"] for p in prepared)),
        "issues_by_type": dict(sorted(issues_by_type.items())), "data_problems": data_problems,
        "learned_models": "none - every policy below is fixed code or the evaluator-only oracle",
        "policies": {},
    }
    for name in policies:
        rows = []
        per_type = {t: Counter() for t in ERROR_TYPES}
        red_fp: Counter = Counter()
        for p in prepared:
            policy = OraclePolicy(p["ep"].sealed) if name == "oracle" else make_policy(name, 0)
            out, log, submitted = _play(policy, p["ep"])
            scored = next((x for x in log if x.get("event") == "scored"), None)
            if scored:
                for v in scored["verdicts"]:
                    if v["matched_issue"] is not None:
                        per_type[p["types"][v["matched_issue"]]]["tp"] += 1
                    else:
                        if v["claimed_type"] in per_type:
                            per_type[v["claimed_type"]]["fp"] += 1
                        kinds = {p["red"][a] for a in submitted[v["finding"]].get("affected_ids", []) if a in p["red"]}
                        red_fp.update(kinds)
                for iid in scored["unmatched_issues"]:
                    per_type[p["types"][iid]]["fn"] += 1
            rows.append({"episode": p["meta"]["id"], "category": p["meta"]["category"], "reward": out.reward,
                         "inspection_steps": out.inspection_steps, "tp": out.tp, "fp": out.fp, "fn": out.fn,
                         "f1": out.f1, "findings": out.findings_submitted, "reason": out.reason})
        tp, fp, fn = (sum(r[k] for r in rows) for k in ("tp", "fp", "fn"))
        clean = [r for r in rows if r["category"] == "clean"]
        report["policies"][name] = {
            "kind": _kind(name),
            "overall": _prf(tp, fp, fn) | {"mean_reward": _mean([r["reward"] for r in rows]),
                                           "mean_f1": _mean([r["f1"] for r in rows]),
                                           "mean_inspection_steps": _mean([r["inspection_steps"] for r in rows])},
            "per_type": {t: _prf(c["tp"], c["fp"], c["fn"]) for t, c in per_type.items()},
            "by_category": {cat: {"episodes": len(rs), "mean_reward": _mean([r["reward"] for r in rs]),
                                  **_prf(sum(r["tp"] for r in rs), sum(r["fp"] for r in rs), sum(r["fn"] for r in rs))}
                            for cat in report["categories"] for rs in [[r for r in rows if r["category"] == cat]]},
            "clean_episodes": {"episodes": len(clean), "mean_reward": _mean([r["reward"] for r in clean]),
                               "false_positives": sum(r["fp"] for r in clean),
                               "empty_answers": sum(1 for r in clean if r["findings"] == 0)},
            "red_herring_false_positives": {"total": sum(red_fp.values()), "by_kind": dict(sorted(red_fp.items()))},
            "episodes": rows,
        }
    report["duration_seconds"] = round(time.perf_counter() - started, 2)
    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        (out / "report.md").write_text(render_markdown(report), encoding="utf-8", newline="\n")
    return report


def render_markdown(report: dict) -> str:
    lines = [f"# OPHANIM ablation study (env {report['env_version']})", "",
             f"{report['episodes']} fixed open episodes ({', '.join(f'{k} {v}' for k, v in report['categories'].items())}); "
             f"issues by type: {report['issues_by_type']}. Learned models: {report['learned_models']}.", "",
             "| policy | kind | mean reward | precision | recall | F1 (micro) | TP | FP | FN | mean inspection steps |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, s in report["policies"].items():
        o = s["overall"]
        lines.append(f"| {name} | {s['kind']} | {o['mean_reward']:+.4f} | {o['precision']:.3f} | {o['recall']:.3f} | "
                     f"{o['f1']:.3f} | {o['tp']} | {o['fp']} | {o['fn']} | {o['mean_inspection_steps']:.2f} |")
    lines += ["", "## F1 per error type (TP/FP/FN)", "",
              "| policy | " + " | ".join(ERROR_TYPES) + " |", "|---|" + "---:|" * len(ERROR_TYPES)]
    for name, s in report["policies"].items():
        cells = [f"{v['f1']:.3f} ({v['tp']}/{v['fp']}/{v['fn']})" for v in s["per_type"].values()]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "## Clean episodes and red herrings", "",
              "| policy | clean: mean reward | clean: FP | clean: empty answers | FP on red-herring documents | by kind |",
              "|---|---:|---:|---:|---:|---|"]
    for name, s in report["policies"].items():
        c, r = s["clean_episodes"], s["red_herring_false_positives"]
        lines.append(f"| {name} | {c['mean_reward']:+.4f} | {c['false_positives']} | {c['empty_answers']}/{c['episodes']} | "
                     f"{r['total']} | {r['by_kind'] or '-'} |")
    lines += ["", "Precision, recall and F1 in the first table are micro-averaged over all findings and issues. "
              "The oracle reads the sealed truth: it shows the ceiling of the scorer, not an agent capability.", ""]
    return "\n".join(lines)
