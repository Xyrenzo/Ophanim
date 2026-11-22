"""Command-line interface: ``python -m ophanim <command>``.

    verify          ONE-COMMAND CHECK: tests + published data + trajectories + closed evaluation
    evaluate        closed evaluation of the official suite (4 baselines, 20 episodes, 20 pairs)
    build-data      regenerate data/train, data/dev and data/trajectories.jsonl from configs/
    generate        write one episode (public/ + evaluator/) to disk
    verify-episode  independently verify an episode directory
    demo            run the scripted reference auditor on one episode
    schemas         print the public JSON Schemas
    stress          large-scale stress test of generator, auditor and verifier (smoke / standard / full)
    ablate          ablation and comparison study on fixed open episodes
    trace           evaluator-side trace: finding -> issue -> injection -> rows (needs evaluator/ files)
    run-agent       run one closed episode with an external agent process or container
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRAJECTORY_POLICIES = ("reference_auditor", "simple_reconciliation", "random_explorer", "mark_everything")


def _load_config(path: str | None) -> dict:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_generate(args: argparse.Namespace) -> int:
    from ophanim.generator import generate_episode

    ep = generate_episode(args.seed, _load_config(args.config))
    out = Path(args.out) / ep.public.episode_id
    ep.write(out)
    print(f"wrote {out} ({len(ep.sealed.truth.issues)} issues)")
    return 0


def cmd_verify_episode(args: argparse.Namespace) -> int:
    from ophanim.evaluator.verifier import verify_directory

    rep = verify_directory(args.path)
    print(json.dumps({"ok": rep.ok, "issues_declared": rep.issues_declared,
                      "issues_found_independently": rep.issues_found_independently,
                      "evidence_sets_checked": rep.evidence_sets_checked, "problems": rep.problems[:50]}, indent=2))
    return 0 if rep.ok else 1


def cmd_demo(args: argparse.Namespace) -> int:
    from ophanim.analytics import TrajectoryLogger
    from ophanim.env import OphanimEnv
    from ophanim.evaluator.runner import run_episode
    from ophanim.policies import ReferenceAuditor

    config = _load_config(args.config) or {"errors": {"duplicate_invoice": 1, "payment_allocation": 2}}
    logger = TrajectoryLogger(args.trajectory) if args.trajectory else TrajectoryLogger()
    env = OphanimEnv(mode="train")
    record = run_episode(env, ReferenceAuditor(), args.seed, config, logger)
    logger.close()
    for line in logger.lines:
        row = json.loads(line)
        act = row["action"]
        label = "reset" if act is None else act["action"] + (f" {act.get('table', '')}" if act["action"] == "list_records" else "")
        print(f"step {row['step']:>3}  {label:<26} reward={row['reward']:+.3f} terminated={row['terminated']} truncated={row['truncated']}")
    print(json.dumps(record.to_dict(), indent=2))
    return 0


def build_data(out: Path) -> dict:
    """Generate the open train/dev episodes and the public training trajectories."""
    from ophanim.analytics import TrajectoryLogger
    from ophanim.env import OphanimEnv
    from ophanim.evaluator.runner import run_episode
    from ophanim.generator import generate_episode
    from ophanim.policies import make_policy

    summary = {}
    for split in ("train", "dev"):
        suite = json.loads((ROOT / "configs" / split / "suite.json").read_text(encoding="utf-8"))
        index = []
        for e in suite["episodes"]:
            ep = generate_episode(e["seed"], e["config"])
            ep.write(out / split / e["id"])
            index.append({"id": e["id"], "category": e["category"], "seed": e["seed"], "config": e["config"],
                          "episode_id": ep.public.episode_id, "issues": len(ep.sealed.truth.issues)})
        with open(out / split / "index.json", "w", encoding="utf-8", newline="\n") as fh:  # LF on every OS
            fh.write(json.dumps(index, indent=2) + "\n")
        summary[split] = len(index)
    # Public training trajectories: agent-side policies only (never the oracle), open mode.
    path = out / "trajectories.jsonl"
    path.unlink(missing_ok=True)
    logger = TrajectoryLogger(path)
    suite = json.loads((ROOT / "configs" / "train" / "suite.json").read_text(encoding="utf-8"))
    episodes = 0
    for policy in TRAJECTORY_POLICIES:
        for e in suite["episodes"]:
            run_episode(OphanimEnv(mode="train"), make_policy(policy, 0), e["seed"], e["config"], logger)
            episodes += 1
    logger.close()
    summary["trajectory_episodes"] = episodes
    summary["trajectory_lines"] = len(logger.lines)
    return summary


def cmd_build_data(args: argparse.Namespace) -> int:
    print(json.dumps(build_data(Path(args.out)), indent=2))
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    from ophanim.evaluator.evaluation import DEFAULT_SEED_BASE, run_evaluation, secret_from_environment

    report = run_evaluation(args.suite, args.out, seed_base=args.seed_base or os.environ.get("OPHANIM_SEED_BASE", DEFAULT_SEED_BASE),
                            secret=secret_from_environment(), isolate=not args.in_process)
    print((Path(args.out) / "report.md").read_text(encoding="utf-8"))
    ok = report["data_checks"]["passed"] == report["data_checks"]["total"] and \
        report["metamorphic"]["passed"] == report["metamorphic"]["total"] and \
        report["reproducibility"]["passed"] == report["reproducibility"]["total"]
    return 0 if ok else 1


def _check_published_data(data: Path) -> dict:
    """Verify every published episode and that it regenerates byte-for-byte from configs/."""
    import tempfile

    from ophanim.evaluator.verifier import verify_directory
    from ophanim.generator import generate_episode

    verified = regenerated = total = 0
    problems: list[str] = []
    hidden: set[str] = set()
    for split in ("train", "dev"):
        suite = json.loads((ROOT / "configs" / split / "suite.json").read_text(encoding="utf-8"))
        for e in suite["episodes"]:
            total += 1
            d = data / split / e["id"]
            rep = verify_directory(d)
            verified += rep.ok
            problems += [f"{e['id']}: {p}" for p in rep.problems[:3]]
            truth = json.loads((d / "evaluator" / "truth.json").read_text(encoding="utf-8"))
            hidden.update(i["issue_id"] for i in truth["issues"])
            with tempfile.TemporaryDirectory() as tmp:
                generate_episode(e["seed"], e["config"]).write(Path(tmp))
                same = all((Path(tmp) / sub / f).read_bytes() == (d / sub / f).read_bytes()
                           for sub, files in (("public", ("manifest.json", "policy.json", "ledger.csv", "invoices.jsonl",
                                                          "payments.jsonl", "fx.csv")),
                                              ("evaluator", ("truth.json", "provenance.json")))
                           for f in files)
            regenerated += same
            if not same:
                problems.append(f"{e['id']}: published files differ from regeneration")
    # Trajectories: required fields, and nothing from the evaluator side.
    traj = data / "trajectories.jsonl"
    lines = traj.read_text(encoding="utf-8").splitlines() if traj.exists() else []
    leaks = 0
    for line in lines:
        row = json.loads(line)
        if list(row) != ["episode_id", "step", "action", "observation", "reward", "terminated", "truncated"]:
            problems.append("trajectory line with wrong fields")
            break
        obs = json.dumps(row["observation"])
        if any(h in obs for h in hidden) or any(k in obs for k in ("provenance", "allowed_evidence_sets", "expected_amount_minor")):
            leaks += 1
    return {"episodes_verified": f"{verified}/{total}", "regenerated_identically": f"{regenerated}/{total}",
            "trajectory_lines": len(lines), "trajectory_leaks": leaks, "ok": verified == regenerated == total and leaks == 0
            and bool(lines), "problems": problems[:20]}


def cmd_verify(args: argparse.Namespace) -> int:
    from ophanim.evaluator.evaluation import DEFAULT_SEED_BASE, run_evaluation

    results: dict[str, dict] = {}
    if not args.skip_tests:
        # pyproject already sets -q; a second -q would suppress pytest's "N passed" summary line.
        proc = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", str(ROOT / "tests")],
                              cwd=ROOT, capture_output=True, text=True)
        tail = [l for l in proc.stdout.splitlines() if l.strip()][-1:] or ["no output"]
        results["tests"] = {"ok": proc.returncode == 0, "summary": tail[0]}
    results["published_data"] = _check_published_data(ROOT / "data")
    secret = os.environ.get("OPHANIM_EVAL_SECRET", "ophanim-verify-local-secret").encode("utf-8")
    seed_base = os.environ.get("OPHANIM_SEED_BASE", DEFAULT_SEED_BASE)
    rep = run_evaluation(ROOT / "configs" / "eval" / "official_suite.json", Path(args.out), seed_base=seed_base, secret=secret)
    results["closed_evaluation"] = {
        "ok": all(rep[k]["passed"] == rep[k]["total"] for k in ("data_checks", "metamorphic", "reproducibility")),
        "data_checks": f"{rep['data_checks']['passed']}/{rep['data_checks']['total']}",
        "metamorphic_pairs": f"{rep['metamorphic']['passed']}/{rep['metamorphic']['total']}",
        "reproducibility": f"{rep['reproducibility']['passed']}/{rep['reproducibility']['total']}",
        "mean_return": {k: v["overall"]["mean_return"] for k, v in rep["policies"].items()},
        "report": str(Path(args.out) / "report.md"),
    }
    ok = all(r["ok"] for r in results.values())
    print(json.dumps({"ok": ok, **results}, indent=2))
    print("\nOPHANIM VERIFY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_schemas(_: argparse.Namespace) -> int:
    from ophanim import schemas

    out = {name: getattr(schemas, name).model_json_schema() for name in
           ("EpisodeConfig", "FindingsSubmission", "ListRecordsAction", "GetRecordAction", "GetDocumentAction",
            "CalculatorAction", "SubmitAction", "TruthFile")}
    print(json.dumps(out, indent=2))
    return 0


def cmd_stress(args: argparse.Namespace) -> int:
    from ophanim.evaluator.stress import run_stress

    summary = run_stress(args.level)
    text = json.dumps(summary, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    print(text)
    print("\nOPHANIM STRESS:", "PASS" if summary["ok"] else "FAIL")
    return 0 if summary["ok"] else 1


def cmd_ablate(args: argparse.Namespace) -> int:
    from ophanim.evaluator.ablation import render_markdown, run_ablation

    report = run_ablation(args.suite, args.out)
    print(render_markdown(report))
    if report["data_problems"]:
        print("data problems:", report["data_problems"])
        return 1
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    from ophanim.audit.dataset import PublicDataset
    from ophanim.evaluator.provenance_check import check_provenance, trace_findings
    from ophanim.schemas import TruthFile

    d = Path(args.path)
    ds = PublicDataset.from_directory(d / "public")
    tables = {"ledger": ds.ledger, "invoices": ds.invoices, "payments": ds.payments, "fx": ds.fx}
    truth = TruthFile.model_validate_json((d / "evaluator" / "truth.json").read_text(encoding="utf-8"))
    prov = json.loads((d / "evaluator" / "provenance.json").read_text(encoding="utf-8"))
    out: dict = {"provenance_problems": check_provenance(tables, prov, truth, ds.manifest)}
    if args.submission:
        sub = json.loads(Path(args.submission).read_text(encoding="utf-8"))
        out["findings"] = trace_findings(tables, prov, truth, sub.get("submission", sub))
    print(json.dumps(out, indent=2))
    return 0 if not out["provenance_problems"] else 1


def cmd_run_agent(args: argparse.Namespace) -> int:
    from ophanim.analytics import TrajectoryLogger
    from ophanim.env import OphanimEnv
    from ophanim.evaluator.process_runner import (
        agent_command,
        container_agent_command,
        container_name,
        remove_container,
        run_episode_isolated,
    )

    if bool(args.cmd) == bool(args.policy):
        print("give exactly one of --cmd or --policy", file=sys.stderr)
        return 2
    if args.container:
        inner = ["--policy", args.policy] if args.policy else shlex.split(args.cmd)
        cmd = container_agent_command(args.container, inner)
    else:
        cmd = agent_command(args.policy) if args.policy else shlex.split(args.cmd, posix=os.name != "nt")
        # The agent starts in an empty temporary directory: make paths given relative to here absolute.
        cmd = [str(Path(a).resolve()) if not a.startswith("-") and Path(a).is_file() else a for a in cmd]
    logger = TrajectoryLogger(args.trajectory) if args.trajectory else None
    try:
        rec = run_episode_isolated(OphanimEnv(mode="eval"), cmd, args.seed, _load_config(args.config), logger,
                                   policy_name=args.policy or "external")
    finally:
        if args.container and container_name(cmd):
            remove_container(container_name(cmd))
        if logger is not None:
            logger.close()
    print(json.dumps({"isolation": "container" if args.container else "process", "record": rec.to_dict()}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ophanim", description="OPHANIM - Financial Forensics Lab")
    sub = parser.add_subparsers(dest="command", required=True)

    vf = sub.add_parser("verify", help="one-command check of the whole submission")
    vf.add_argument("--out", default=str(ROOT / "runs" / "verify"))
    vf.add_argument("--skip-tests", action="store_true")
    vf.set_defaults(fn=cmd_verify)

    ev = sub.add_parser("evaluate", help="closed evaluation of a suite")
    ev.add_argument("--suite", default=str(ROOT / "configs" / "eval" / "official_suite.json"))
    ev.add_argument("--out", default=str(ROOT / "runs" / "evaluation"))
    ev.add_argument("--seed-base", help="hidden seed base (or env OPHANIM_SEED_BASE)")
    ev.add_argument("--in-process", action="store_true", help="run agents in-process (debug only)")
    ev.set_defaults(fn=cmd_evaluate)

    bd = sub.add_parser("build-data", help="regenerate data/train, data/dev, data/trajectories.jsonl")
    bd.add_argument("--out", default=str(ROOT / "data"))
    bd.set_defaults(fn=cmd_build_data)

    g = sub.add_parser("generate", help="generate one episode")
    g.add_argument("--seed", type=int, required=True)
    g.add_argument("--config")
    g.add_argument("--out", default="runs/episodes")
    g.set_defaults(fn=cmd_generate)

    v = sub.add_parser("verify-episode", help="independently verify an episode directory")
    v.add_argument("path")
    v.set_defaults(fn=cmd_verify_episode)

    d = sub.add_parser("demo", help="run the scripted reference auditor")
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--config")
    d.add_argument("--trajectory")
    d.set_defaults(fn=cmd_demo)

    s = sub.add_parser("schemas", help="print public JSON Schemas")
    s.set_defaults(fn=cmd_schemas)

    st = sub.add_parser("stress", help="stress test generator, independent auditor and verifier")
    st.add_argument("--level", choices=("smoke", "standard", "full"), default="standard")
    st.add_argument("--out", help="write the JSON summary to this file")
    st.set_defaults(fn=cmd_stress)

    ab = sub.add_parser("ablate", help="ablation and comparison study on fixed open episodes")
    ab.add_argument("--suite", default=str(ROOT / "configs" / "ablation" / "suite.json"))
    ab.add_argument("--out", default=str(ROOT / "runs" / "ablation"))
    ab.set_defaults(fn=cmd_ablate)

    tr = sub.add_parser("trace", help="evaluator side: validate provenance and trace a submission")
    tr.add_argument("path", help="episode directory with public/ and evaluator/")
    tr.add_argument("--submission", help="findings JSON ({episode_id, findings})")
    tr.set_defaults(fn=cmd_trace)

    ra = sub.add_parser("run-agent", help="run one closed episode with an external agent (JSON lines)")
    ra.add_argument("--cmd", help='agent command line, e.g. "python examples/external_agent.py"')
    ra.add_argument("--policy", help="built-in policy, run through ophanim.agent_runtime")
    ra.add_argument("--container", metavar="IMAGE", help="run the agent in a hardened Docker container from IMAGE")
    ra.add_argument("--seed", type=int, default=7)
    ra.add_argument("--config")
    ra.add_argument("--trajectory", help="write the public trajectory (JSONL) here")
    ra.set_defaults(fn=cmd_run_agent)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
