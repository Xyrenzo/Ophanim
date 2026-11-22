"""Hardening of the evaluator/agent boundary: minimal environment, bounded output, non-dumpable evaluator,
hardened container command. Hostile agents are real child processes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

from ophanim.env import OphanimEnv
from ophanim.evaluator import process_runner
from ophanim.evaluator.process_runner import (
    agent_environment,
    container_agent_command,
    container_name,
    harden_evaluator_process,
    run_episode_isolated,
)

CFG = {"errors": {"duplicate_invoice": 1}}
SUBMIT_EMPTY = 'print(json.dumps({"action": {"action": "submit", "findings": {"episode_id": eid, "findings": []}}}), flush=True)'


def _script(tmp_path, body: str, name: str = "agent.py") -> list[str]:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(path)]


def test_agent_environment_is_allow_listed(tmp_path, monkeypatch):
    for k, v in {"GITHUB_TOKEN": "gh-canary", "AWS_SECRET_ACCESS_KEY": "aws-canary", "OPHANIM_EVAL_SECRET": "s"}.items():
        monkeypatch.setenv(k, v)
    env = agent_environment(str(tmp_path), extra={"MODEL_DIR": "/models", "OPHANIM_SEED_BASE": "x"})
    assert "GITHUB_TOKEN" not in env and "AWS_SECRET_ACCESS_KEY" not in env
    assert not any(k.upper().startswith("OPHANIM_") for k in env)
    assert env["MODEL_DIR"] == "/models" and env["PYTHONHASHSEED"] == "0"
    assert env["HOME"] == env["TMP"] == str(tmp_path)


def test_agent_process_sees_neither_host_tokens_nor_the_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_TOKEN", "do-not-leak")
    monkeypatch.setenv("OPHANIM_EVAL_SECRET", "do-not-leak-either")
    seen = tmp_path / "env.json"
    cmd = _script(tmp_path, f"""
        import json, os, sys
        open({str(seen)!r}, "w").write(json.dumps({{"env": dict(os.environ), "hash": hash("ophanim")}}))
        for line in sys.stdin:
            msg = json.loads(line)
            if msg["type"] == "end":
                break
            if msg["type"] == "reset":
                eid = msg["observation"]["manifest"]["episode_id"]
                {SUBMIT_EMPTY}
    """)
    rec = run_episode_isolated(OphanimEnv(mode="eval"), cmd, 90, CFG)
    assert rec.terminated
    info = json.loads(seen.read_text())
    assert "do-not-leak" not in json.dumps(info["env"]) and info["env"]["PYTHONHASHSEED"] == "0"
    run_episode_isolated(OphanimEnv(mode="eval"), cmd, 90, CFG)
    assert json.loads(seen.read_text())["hash"] == info["hash"]          # deterministic str hashing


def test_an_unterminated_oversized_line_is_drained_into_one_invalid_action(tmp_path):
    cmd = _script(tmp_path, f"""
        import json, sys
        for line in sys.stdin:
            msg = json.loads(line)
            if msg["type"] == "end":
                break
            if msg["type"] == "reset":
                eid = msg["observation"]["manifest"]["episode_id"]
                sys.stdout.write("x" * 3_500_000)          # one 3.5 MB line, written in chunks below the limit
                sys.stdout.write("\\n"); sys.stdout.flush()
            elif not (msg["terminated"] or msg["truncated"]):
                {SUBMIT_EMPTY}
    """)
    from ophanim.analytics import TrajectoryLogger
    logger = TrajectoryLogger()
    rec = run_episode_isolated(OphanimEnv(mode="eval"), cmd, 91, CFG, logger)
    actions = [json.loads(l)["action"] for l in logger.lines[1:]]
    assert rec.terminated and rec.steps == 2
    assert actions[0] == {"action": "__oversized__"} and actions[1]["action"] == "submit"


def test_an_agent_that_floods_its_output_is_cut_off(tmp_path, monkeypatch):
    monkeypatch.setattr(process_runner, "MAX_OUTPUT_CHARS", 20_000)
    cmd = _script(tmp_path, """
        import json, sys
        for line in sys.stdin:
            msg = json.loads(line)
            if msg["type"] == "end":
                break
            for _ in range(200):
                print(json.dumps({"action": {"action": "calculator", "expression": "1+" * 200 + "1"}}), flush=True)
    """)
    rec = run_episode_isolated(OphanimEnv(mode="eval"), cmd, 92, CFG)
    assert rec.truncated and rec.outcome_reason == "agent_output_limit"


_EVALUATOR = """
import json, sys, textwrap
sys.path.insert(0, {src!r})
from ophanim.env import OphanimEnv
from ophanim.evaluator import process_runner as pr
if {disable!r}:
    pr.harden_evaluator_process = lambda: False
agent = {agent!r}
pr.run_episode_isolated(OphanimEnv(mode="eval"), [sys.executable, agent], 93, {{}})
"""

_PEEKER = """
import json, os, sys
try:
    data = open(f"/proc/{os.getppid()}/environ", "rb").read()
    result = "LEAKED" if b"proc-canary-secret" in data else "read-without-secret"
except OSError as exc:
    result = type(exc).__name__
open(sys.argv[0] + ".result", "w").write(result)
for line in sys.stdin:
    msg = json.loads(line)
    if msg["type"] == "end":
        break
    if msg["type"] == "reset":
        eid = msg["observation"]["manifest"]["episode_id"]
        print(json.dumps({"action": {"action": "submit", "findings": {"episode_id": eid, "findings": []}}}), flush=True)
"""


def _peek_parent_environ(tmp_path, disable_hardening: bool) -> str:
    agent = tmp_path / ("peek-off.py" if disable_hardening else "peek-on.py")
    agent.write_text(_PEEKER, encoding="utf-8")
    src = str(process_runner._SRC)
    script = _EVALUATOR.format(src=src, disable=disable_hardening, agent=str(agent))
    env = dict(os.environ, OPHANIM_EVAL_SECRET="proc-canary-secret")
    subprocess.run([sys.executable, "-c", script], env=env, check=True, timeout=60)
    return (tmp_path / (agent.name + ".result")).read_text()


def test_non_dumpable_evaluator_hides_its_environment_from_same_user_agents(tmp_path):
    if not sys.platform.startswith("linux"):
        # Not available outside Linux: the function reports that it did nothing (no false sense of security).
        assert harden_evaluator_process() is False
        return
    leaked = _peek_parent_environ(tmp_path, disable_hardening=True)
    hardened = _peek_parent_environ(tmp_path, disable_hardening=False)
    if os.geteuid() == 0:
        # root bypasses the dumpable flag (CAP_SYS_PTRACE): the protection only applies to unprivileged users
        assert leaked == "LEAKED"
        return
    assert leaked == "LEAKED"                     # the threat is real for a plain child process
    assert hardened in ("PermissionError", "OSError")


def test_container_command_is_hardened_and_mounts_nothing():
    cmd = container_agent_command("ophanim-agent:local", ["--policy", "reference_auditor"])
    joined = " ".join(cmd)
    for flag in ("--rm", "-i", "--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
                 "--user 65534:65534", "--ipc none", "--pids-limit 64", "--memory 512m", "--memory-swap 512m",
                 "--cpus 1", "--log-driver none", "PYTHONHASHSEED=0"):
        assert flag in joined, flag
    for forbidden in ("-v", "--volume", "--mount", "--privileged", "--cap-add"):
        assert forbidden not in cmd, forbidden
    for forbidden in ("docker.sock", "--network host", "--pid host", "--ipc host", "--userns host"):
        assert forbidden not in joined, forbidden
    assert cmd[-3:] == ["ophanim-agent:local", "--policy", "reference_auditor"]
    other = container_agent_command("ophanim-agent:local")
    assert container_name(cmd) != container_name(other) and container_name(cmd).startswith("ophanim-agent-")
