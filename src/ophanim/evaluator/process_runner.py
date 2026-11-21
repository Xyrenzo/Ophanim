"""Closed evaluation across a process boundary (evaluator side).

The environment, judge and sealed truth live in THIS (evaluator) process. The
policy runs as a child process (``ophanim.agent_runtime`` or any program that
speaks the same JSON-lines protocol). The child:

  * receives only observations, rewards (0.0 in eval mode), flags and info;
  * runs in an empty temporary working directory;
  * gets an environment with every ``OPHANIM_*`` variable removed (so it never
    sees the evaluation secret);
  * cannot reach the environment object, the judge or the truth in memory.

Robustness: replies are read on a background thread with a deadline. A hung
agent, a crashed agent, malformed JSON or oversized lines cannot stall or crash
the evaluator; they are scored as a timeout / invalid action.
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
from pathlib import Path

from ophanim.analytics import TrajectoryLogger
from ophanim.env.environment import OphanimEnv
from ophanim.evaluator.runner import EpisodeRecord, record_from_outcome

MAX_LINE_CHARS = 1_000_000
RESPONSE_GRACE_SECONDS = 2.0
_SRC = str(Path(__file__).resolve().parents[2])


def agent_command(policy: str, policy_seed: int = 0) -> list[str]:
    return [sys.executable, "-m", "ophanim.agent_runtime", "--policy", policy, "--policy-seed", str(policy_seed)]


def agent_environment() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("OPHANIM_")}
    env["PYTHONPATH"] = _SRC + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _reader(stream, q: queue.Queue) -> None:
    try:
        for line in stream:
            q.put(line)
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
                         logger: TrajectoryLogger | None = None, policy_name: str = "agent") -> EpisodeRecord:
    obs, info = env.reset(seed, config)
    episode_id = obs["manifest"]["episode_id"]
    if logger is not None:
        logger.record(episode_id, 0, None, obs, 0.0, False, False)
    workdir = tempfile.mkdtemp(prefix="ophanim-agent-")
    proc = subprocess.Popen(agent_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            cwd=workdir, env=agent_environment(), text=True, encoding="utf-8", bufsize=1)
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
            action = _parse_action(line)
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
