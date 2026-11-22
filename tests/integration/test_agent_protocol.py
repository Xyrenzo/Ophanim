"""Integration ergonomics: the stdlib-only external agent, the agent image contents, the protocol
documentation and the new CLI commands."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

from ophanim import cli
from ophanim.env import OphanimEnv
from ophanim.env.tools import ERROR_MESSAGES
from ophanim.evaluator.oracle import oracle_submission
from ophanim.evaluator.process_runner import run_episode_isolated
from ophanim.generator.episode import generate_episode

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = [sys.executable, str(ROOT / "examples" / "external_agent.py")]


def _strip(rec) -> dict:
    return {k: v for k, v in rec.to_dict().items() if k != "runtime_seconds"}


def test_external_example_agent_finds_duplicates_and_nothing_else():
    cfg = {"errors": {"duplicate_invoice": 2, "fx_rate": 1}, "distractors": "high"}
    rec = run_episode_isolated(OphanimEnv(mode="eval"), EXAMPLE, 21, cfg, policy_name="example")
    assert rec.terminated and (rec.tp, rec.fp, rec.fn) == (2, 0, 1)
    again = run_episode_isolated(OphanimEnv(mode="eval"), EXAMPLE, 21, cfg, policy_name="example")
    assert _strip(again) == _strip(rec)                                   # deterministic


@pytest.mark.parametrize("seed", [22, 23, 24])
def test_external_example_agent_is_not_fooled_by_red_herrings(seed):
    rec = run_episode_isolated(OphanimEnv(mode="eval"), EXAMPLE, seed, {"distractors": "high"}, policy_name="example")
    assert rec.terminated and rec.fp == 0 and rec.reward > 0.9


def test_external_example_imports_only_the_standard_library():
    tree = ast.parse((ROOT / "examples" / "external_agent.py").read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert names <= set(sys.stdlib_module_names) | {"__future__"}


def test_every_public_error_code_is_documented():
    doc = (ROOT / "docs" / "agent_protocol.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", doc, re.M))
    assert set(ERROR_MESSAGES) <= documented


def _module_file(name: str) -> Path:
    base = ROOT / "src" / Path(*name.split("."))
    return base / "__init__.py" if base.is_dir() else base.with_suffix(".py")


def test_agent_image_contains_exactly_the_agent_side_code():
    copies = [line.split()[1:-1] for line in (ROOT / "docker" / "agent.Dockerfile").read_text(encoding="utf-8").splitlines()
              if line.startswith("COPY ")]
    sources = [ROOT / s for group in copies for s in group]
    assert all(s.exists() for s in sources)
    assert not any(part in s.as_posix() for s in sources for part in ("data", "configs", "tests", "evaluator", "generator", "/env"))

    def included(path: Path) -> bool:
        return any(path == s or s in path.parents for s in sources)

    todo, seen = ["ophanim.agent_runtime", "ophanim.policies"], set()
    while todo:                                                           # transitive ophanim imports
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        path = _module_file(name)
        assert included(path), f"{name} is imported by the agent runtime but not copied into the image"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            todo += [m for m in mods if m.startswith("ophanim")]
            todo += [".".join(m.split(".")[:i]) for m in mods if m.startswith("ophanim") for i in range(1, m.count(".") + 1)]


# ----------------------------------------------------------------------------- CLI commands
def test_cli_run_agent_with_a_builtin_policy(capsys):
    assert cli.main(["run-agent", "--policy", "reference_auditor", "--seed", "7"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["isolation"] == "process" and out["record"]["fp"] == 0 and out["record"]["terminated"]
    assert cli.main(["run-agent", "--seed", "7"]) == 2                    # neither --cmd nor --policy


def test_cli_stress_smoke_writes_a_passing_summary(tmp_path, capsys):
    out = tmp_path / "stress.json"
    assert cli.main(["stress", "--level", "smoke", "--out", str(out)]) == 0
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["ok"] and summary["level"] == "smoke"
    assert "OPHANIM STRESS: PASS" in capsys.readouterr().out


def test_cli_trace_validates_provenance_and_traces_a_submission(tmp_path, capsys):
    ep = generate_episode(25, {"errors": {"fx_rate": 1, "period_attribution": 1}})
    ep.write(tmp_path / "ep")
    sub = tmp_path / "sub.json"
    sub.write_text(json.dumps(oracle_submission(ep.sealed)), encoding="utf-8")
    assert cli.main(["trace", str(tmp_path / "ep"), "--submission", str(sub)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["provenance_problems"] == [] and all(f["matched_issue"] for f in out["findings"])
