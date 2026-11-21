"""In-process episode runner (evaluator side).

Drives one policy through one episode, logs the public trajectory, and reads the
judged outcome from the environment's evaluator-only accessor afterwards.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from ophanim.analytics import TrajectoryLogger
from ophanim.env.environment import OphanimEnv


@dataclass
class EpisodeRecord:
    policy: str
    episode_id: str
    reward: float
    terminated: bool
    truncated: bool
    steps: int
    inspection_steps: int
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    findings_submitted: int
    outcome_reason: str
    runtime_seconds: float

    def to_dict(self) -> dict:
        return asdict(self)


def run_episode(env: OphanimEnv, policy, seed: int, config: dict | None = None,
                logger: TrajectoryLogger | None = None) -> EpisodeRecord:
    obs, info = env.reset(seed, config)
    policy.reset(obs, info)
    episode_id = obs["manifest"]["episode_id"]
    if logger is not None:
        logger.record(episode_id, 0, None, obs, 0.0, False, False)
    started = time.perf_counter()
    step = 0
    terminated = truncated = False
    while not (terminated or truncated):
        action = policy.act(obs)
        obs, reward, terminated, truncated, info = env.step(action)
        step += 1
        if logger is not None:
            logger.record(episode_id, step, action, obs, reward, terminated, truncated)
    runtime = time.perf_counter() - started
    out = env.evaluator_outcome()
    return record_from_outcome(getattr(policy, "name", type(policy).__name__), episode_id, out, terminated, truncated, step, runtime)


def record_from_outcome(policy: str, episode_id: str, out, terminated: bool, truncated: bool, steps: int,
                        runtime: float) -> EpisodeRecord:
    return EpisodeRecord(
        policy=policy, episode_id=episode_id, reward=out.reward, terminated=terminated, truncated=truncated,
        steps=steps, inspection_steps=out.inspection_steps, tp=out.tp, fp=out.fp, fn=out.fn,
        precision=out.precision, recall=out.recall, f1=out.f1, findings_submitted=out.findings_submitted,
        outcome_reason=out.reason, runtime_seconds=round(runtime, 4),
    )
