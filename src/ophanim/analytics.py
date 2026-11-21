"""Trajectory logging (public) - trajectories.jsonl.

Each line: {episode_id, step, action, observation, reward, terminated, truncated}.
Step 0 is the reset observation (action null). Lines contain only what the agent
saw - never truth, provenance, seeds or judge diagnostics - so training
trajectories cannot leak the hidden answer. Evaluator diagnostics are written to
separate evaluator-only reports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import IO, Any


class TrajectoryLogger:
    def __init__(self, sink: str | Path | IO[str] | None = None) -> None:
        self._own = False
        self.lines: list[str] = []
        if sink is None:
            self._fh = None
        elif isinstance(sink, (str, Path)):
            Path(sink).parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(sink, "a", encoding="utf-8", newline="\n")
            self._own = True
        else:
            self._fh = sink

    def record(self, episode_id: str, step: int, action: Any, observation: Any, reward: float,
               terminated: bool, truncated: bool) -> None:
        line = json.dumps({
            "episode_id": episode_id,
            "step": step,
            "action": action,
            "observation": observation,
            "reward": reward,
            "terminated": terminated,
            "truncated": truncated,
        }, ensure_ascii=True)
        self.lines.append(line)
        if self._fh is not None:
            self._fh.write(line + "\n")

    def close(self) -> None:
        if self._own and self._fh is not None:
            self._fh.close()
            self._fh = None
