"""Closed evaluation across a process boundary (evaluator side).

The environment, judge and sealed truth live in THIS (evaluator) process. The
policy runs as a child process (``ophanim.agent_runtime`` or any program that
speaks the same JSON-lines protocol). The child:

  * receives only observations, rewards (0.0 in eval mode), flags and info;
  * runs in an empty temporary working directory, which is also its HOME and TMP;
  * gets a minimal allow-listed environment (PATH and the few variables an interpreter needs, never
    any ``OPHANIM_*`` variable, so it never sees the evaluation secret), with PYTHONHASHSEED=0 so that
    Python agents run deterministically;
  * cannot reach the environment object, the judge or the truth in memory.

Robustness: replies are read on a background thread with a deadline. A hung agent, a crashed agent,
malformed JSON or oversized lines cannot stall or crash the evaluator; they are scored as a timeout or an
invalid action. Reads are bounded: a line longer than MAX_LINE_CHARS is never held in memory (it is drained
and becomes one invalid action), and an agent that writes more than MAX_OUTPUT_CHARS in total is cut off.

Limits of this boundary (see docs/security_model.md): a child process is NOT a sandbox. It runs as the same
OS user, shares the filesystem and could read files that user can read. On Linux the evaluator marks itself
non-dumpable (``harden_evaluator_process``) so that a same-user agent cannot read /proc/<evaluator>/environ
or its memory; /proc/<evaluator>/cmdline stays world-readable, so a hidden seed base must be passed in
OPHANIM_SEED_BASE, not on the command line. For untrusted code, run each agent in its own container
(``container_agent_command``): own PID/network/IPC namespaces, read-only root filesystem, no capabilities,
an unprivileged user and resource limits.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from ophanim.analytics import TrajectoryLogger
from ophanim.env.environment import OphanimEnv
from ophanim.evaluator.runner import EpisodeRecord, record_from_outcome

MAX_LINE_CHARS = 1_000_000
MAX_OUTPUT_CHARS = 16_000_000          # total agent output per episode (100 actions are far below this)
RESPONSE_GRACE_SECONDS = 2.0
_SRC = str(Path(__file__).resolve().parents[2])
# Inherited only if present: what a Windows or POSIX interpreter needs to start, nothing user-specific.
_ALLOWED_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
_OVERSIZED = object()                  # reader -> main loop: one line exceeded MAX_LINE_CHARS
_OUTPUT_LIMIT = object()               # reader -> main loop: the agent exceeded MAX_OUTPUT_CHARS


def agent_command(policy: str, policy_seed: int = 0) -> list[str]:
    return [sys.executable, "-m", "ophanim.agent_runtime", "--policy", policy, "--policy-seed", str(policy_seed)]


def agent_environment(workdir: str | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Minimal environment for an agent process. ``extra`` adds variables an agent explicitly needs;
    ``OPHANIM_*`` variables are dropped from it as well."""
    allowed = {name.upper() for name in _ALLOWED_ENV}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update({k: v for k, v in (extra or {}).items() if not k.upper().startswith("OPHANIM_")})
    env["PYTHONPATH"] = _SRC
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    if workdir is not None:
        for name in ("HOME", "USERPROFILE", "TMPDIR", "TEMP", "TMP"):
            env[name] = workdir
    return env


def harden_evaluator_process() -> bool:
    """Linux only: make this (evaluator) process non-dumpable, so that a child running as the same user can
    no longer read /proc/<evaluator>/environ (the evaluation secret), /proc/<evaluator>/mem or maps.
    Returns True when applied. On other systems it does nothing and returns False."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes

        return ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) == 0   # PR_SET_DUMPABLE = 4
    except (OSError, AttributeError):
        return False


def container_agent_command(image: str, args: list[str] | None = None, *, name: str | None = None,
                            docker: str = "docker", memory: str = "512m", cpus: str = "1",
                            pids_limit: int = 64, user: str = "65534:65534", tmpfs_size: str = "16m") -> list[str]:
    """Command that runs an agent image as a hardened, disposable container speaking JSON lines on stdin/stdout.

    No network, read-only root filesystem, all capabilities dropped, no privilege escalation, an
    unprivileged user, private IPC, PID/memory/CPU limits, a small non-executable /tmp, no volume mounts,
    no host Docker socket, and no stored logs. Remove it afterwards with ``remove_container(name)``.
    """
    return [docker, "run", "--rm", "-i", "--name", name or f"ophanim-agent-{uuid.uuid4().hex[:12]}",
            "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", user, "--ipc", "none", "--pids-limit", str(pids_limit), "--memory", memory,
            "--memory-swap", memory, "--cpus", cpus, "--tmpfs", f"/tmp:rw,noexec,nosuid,size={tmpfs_size}",
            "--env", "PYTHONHASHSEED=0", "--env", "PYTHONDONTWRITEBYTECODE=1", "--log-driver", "none",
            image, *(args or [])]


def container_name(cmd: list[str]) -> str | None:
    return cmd[cmd.index("--name") + 1] if "--name" in cmd else None


def remove_container(name: str, docker: str = "docker") -> None:
    """Best-effort cleanup: a killed ``docker run`` client does not always stop its container."""
    subprocess.run([docker, "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def _reader(stream, q: queue.Queue, line_limit: int | None = None, budget: int | None = None) -> None:
    line_limit = MAX_LINE_CHARS if line_limit is None else line_limit
    budget = MAX_OUTPUT_CHARS if budget is None else budget
    total = 0
    try:
        while True:
            chunk = stream.readline(line_limit + 1)
            if not chunk:
                break
            total += len(chunk)
            if total > budget:
                q.put(_OUTPUT_LIMIT)
                return
            if len(chunk) > line_limit:
                while not chunk.endswith("\n"):          # drain the rest of the oversized line
                    chunk = stream.readline(line_limit + 1)
                    total += len(chunk)
                    if not chunk or total > budget:
                        break
                if total > budget:
                    q.put(_OUTPUT_LIMIT)
                    return
                q.put(_OVERSIZED)
            else:
                q.put(chunk)
    except (OSError, ValueError):
        pass
    finally:
        q.put(None)  # EOF marker


def _writer(stream, q: queue.Queue) -> None:
    try:
        while True:
            item = q.get()
            if item is None:
                break
            stream.write(item)
            stream.flush()
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _parse_action(line: str):
    if len(line) > MAX_LINE_CHARS:
        return {"action": "__oversized__"}
    try:
        msg = json.loads(line)
    except (json.JSONDecodeError, RecursionError):
        return {"action": "__malformed__"}
    if not isinstance(msg, dict) or "action" not in msg:
        return {"action": "__malformed__"}
    return msg["action"]


def run_episode_isolated(env: OphanimEnv, agent_cmd: list[str], seed: int, config: dict | None = None,
                         logger: TrajectoryLogger | None = None, policy_name: str = "agent",
                         extra_env: dict[str, str] | None = None) -> EpisodeRecord:
    obs, info = env.reset(seed, config)
    episode_id = obs["manifest"]["episode_id"]
    if logger is not None:
        logger.record(episode_id, 0, None, obs, 0.0, False, False)
    harden_evaluator_process()
    workdir = tempfile.mkdtemp(prefix="ophanim-agent-")
    proc = subprocess.Popen(agent_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            cwd=workdir, env=agent_environment(workdir, extra_env), text=True, encoding="utf-8",
                            bufsize=1)
    replies: queue.Queue = queue.Queue()
    outbox: queue.Queue = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, replies), daemon=True).start()
    # Writes happen on their own thread: an agent that never reads its stdin fills the OS pipe
    # buffer (4 KB on Windows), and a blocking write must not stall the evaluator.
    threading.Thread(target=_writer, args=(proc.stdin, outbox), daemon=True).start()

    def send(msg: dict) -> None:
        outbox.put(json.dumps(msg) + "\n")

    started = time.perf_counter()
    steps = 0
    terminated = truncated = False
    aborted = False
    try:
        send({"type": "reset", "observation": obs, "info": info})
        while env.evaluator_outcome() is None:
            try:
                line = replies.get(timeout=max(0.0, env.evaluator_time_remaining()) + RESPONSE_GRACE_SECONDS)
            except queue.Empty:
                env.evaluator_abort("agent_timeout")
                aborted = True
                break
            if line is None:
                env.evaluator_abort("agent_exited")
                aborted = True
                break
            if line is _OUTPUT_LIMIT:
                env.evaluator_abort("agent_output_limit")
                aborted = True
                break
            action = {"action": "__oversized__"} if line is _OVERSIZED else _parse_action(line)
            obs, reward, terminated, truncated, info = env.step(action)
            steps += 1
            if logger is not None:
                logger.record(episode_id, steps, action, obs, reward, terminated, truncated)
            send({"type": "step", "observation": obs, "reward": reward, "terminated": terminated,
                  "truncated": truncated, "info": info})
        send({"type": "end"})
        outbox.put(None)
    finally:
        if aborted:
            proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        shutil.rmtree(workdir, ignore_errors=True)
    out = env.evaluator_outcome()
    if aborted:
        terminated, truncated = False, True
    return record_from_outcome(policy_name, episode_id, out, terminated, truncated, steps, time.perf_counter() - started)
