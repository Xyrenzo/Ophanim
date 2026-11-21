"""OPHANIM environment: JSON-compatible, Gymnasium-style reset/step contract.

    reset(seed, config) -> (observation, info)
    step(action)        -> (observation, reward, terminated, truncated, info)

* Observations and actions are plain JSON values (dict/list/str/int/None/bool).
* Exploration steps return reward 0.0. ``submit`` ends the episode with
  terminated=True. Reaching 100 steps or 60 seconds ends it with truncated=True
  and an EMPTY final answer.
* mode="train" (open): the terminal reward is returned to the policy.
  mode="eval" (closed): every reward returned is 0.0 and info is empty; the real
  outcome stays with the judge and is read by the evaluator after the episode
  (``evaluator_outcome``). No correctness hint is ever returned mid-episode.
* Determinism: identical (seed, config, ENV_VERSION, secret, actions) reproduce
  identical observations and rewards. The 60 s wall-clock limit is the only
  non-deterministic element; tests inject a fake clock.

Isolation inside this object: the agent-facing tools (Toolbox) are built from the
public tables only. The judge holds the sealed truth; nothing it knows is copied
into observations or info. For closed evaluation the environment runs in the
evaluator process and the agent talks to it over a JSON pipe (P4), so the agent
cannot inspect this object at all.
"""

from __future__ import annotations

import copy
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable

from ophanim.env.task import TASK_TEXT, TOOL_SPECS
from ophanim.env.tools import ERROR_MESSAGES, ToolError, Toolbox
from ophanim.evaluator.judge import Judge, Outcome, validate_submission
from ophanim.generator.episode import PublicEpisode, SealedEpisode, generate_episode
from ophanim.schemas import ACTION_NAMES, CalculatorAction, EpisodeConfig, GetDocumentAction, GetRecordAction, ListRecordsAction
from ophanim.version import ENV_VERSION, SCHEMA_VERSION

from pydantic import ValidationError

MAX_STEPS = 100
TIME_LIMIT_SECONDS = 60.0

_ACTION_MODELS = {
    "list_records": ListRecordsAction,
    "get_record": GetRecordAction,
    "get_document": GetDocumentAction,
    "calculator": CalculatorAction,
}


@dataclass
class _EpisodeState:
    toolbox: Toolbox
    judge: Judge | None  # None = closed episode loaded without truth (scoring happens elsewhere)
    manifest: dict
    policy: dict
    started_at: float
    steps: int = 0
    done: bool = False
    terminated: bool = False
    truncated: bool = False
    accepted_findings: dict | None = None  # structurally valid submission (public data only)


class OphanimEnv:
    metadata = {"env_version": ENV_VERSION, "schema_version": SCHEMA_VERSION}

    def __init__(self, mode: str = "train", *, secret: bytes | None = None,
                 clock: Callable[[], float] = time.monotonic, time_limit_seconds: float = TIME_LIMIT_SECONDS) -> None:
        if mode not in ("train", "eval"):
            raise ValueError("mode must be 'train' or 'eval'")
        self.mode = mode
        self._secret = secret
        self._clock = clock
        self._time_limit = time_limit_seconds
        self._state: _EpisodeState | None = None

    # ------------------------------------------------------------------ reset
    def reset(self, seed: int | None = None, config: dict | EpisodeConfig | None = None, *,
              options: dict | None = None) -> tuple[dict, dict]:
        """Start a new, fully isolated episode. ``options`` is accepted as a Gymnasium alias of ``config``."""
        if config is None and options is not None:
            config = options
        if seed is None:  # Gymnasium convention; pass an explicit seed for reproducibility
            seed = secrets.randbelow(2**63)
        cfg = config if isinstance(config, EpisodeConfig) else EpisodeConfig.model_validate(config or {})
        generated = generate_episode(seed, cfg, secret=self._secret)
        return self._begin(generated.public, Judge(sealed=generated.sealed))

    def reset_loaded(self, public: PublicEpisode, sealed: SealedEpisode | None = None) -> tuple[dict, dict]:
        """Start an episode from already-loaded data (e.g. a jury episode directory).

        ``sealed=None`` is the closed-evaluation path: the environment then holds no truth at all;
        ``submit`` only checks the structure and records the findings, every reward is 0.0, and the
        evaluator scores the findings separately (``ophanim.adapter.score_episode``). Closed loading
        is only allowed in ``mode="eval"``.
        """
        if sealed is None and self.mode != "eval":
            raise ValueError("an episode without truth can only be run in eval mode")
        return self._begin(public, Judge(sealed=sealed) if sealed is not None else None)

    def _begin(self, public: PublicEpisode, judge: Judge | None) -> tuple[dict, dict]:
        self._state = _EpisodeState(
            toolbox=Toolbox(public.tables),
            judge=judge,
            manifest=copy.deepcopy(public.manifest),
            policy=copy.deepcopy(public.policy),
            started_at=self._clock(),
        )
        observation = {
            "task": TASK_TEXT,
            "manifest": copy.deepcopy(self._state.manifest),
            "policy": copy.deepcopy(self._state.policy),
            "tools": copy.deepcopy(TOOL_SPECS),
            "remaining_steps": MAX_STEPS,
            "time_budget_seconds": self._time_limit,
        }
        info = {"env_version": ENV_VERSION, "schema_version": SCHEMA_VERSION, "mode": self.mode}
        return observation, info

    # ------------------------------------------------------------------ step
    def step(self, action: Any) -> tuple[dict, float, bool, bool, dict]:
        st = self._state
        if st is None:
            raise RuntimeError("reset() must be called before step()")
        if st.done:
            return self._error_obs("episode_finished", 0), 0.0, st.terminated, st.truncated, {}
        if self._clock() - st.started_at > self._time_limit:
            return self._truncate(self._error_obs("time_limit", max(0, MAX_STEPS - st.steps)), "time_limit")

        st.steps += 1
        remaining = MAX_STEPS - st.steps
        name = action.get("action") if isinstance(action, dict) else None
        if name == "submit":
            return self._submit(action, remaining)

        try:
            result = self._dispatch(action, name)
            obs = {"ok": True, "result": result, "error": None, "remaining_steps": remaining}
        except ToolError as exc:
            obs = self._error_obs(exc.code, remaining)
        if st.steps >= MAX_STEPS:
            return self._truncate(obs, "step_limit")
        return obs, 0.0, False, False, {}

    # ------------------------------------------------------------------ evaluator-side accessors
    def evaluator_outcome(self) -> Outcome | None:
        """EVALUATOR ONLY: the judged outcome of the finished episode (never sent to the agent)."""
        if self._state is None or self._state.judge is None:
            return None
        return self._state.judge.outcome

    def evaluator_log(self) -> list[dict]:
        """EVALUATOR ONLY: judge diagnostics and error log."""
        if self._state is None or self._state.judge is None:
            return []
        return copy.deepcopy(self._state.judge.log)

    @property
    def accepted_findings(self) -> dict | None:
        """The structurally valid submission of the current episode, if any (public data, a deep copy)."""
        if self._state is None or self._state.accepted_findings is None:
            return None
        return copy.deepcopy(self._state.accepted_findings)

    def evaluator_time_remaining(self) -> float:
        """EVALUATOR ONLY: seconds left in this episode's time budget."""
        if self._state is None:
            return 0.0
        return self._time_limit - (self._clock() - self._state.started_at)

    def evaluator_abort(self, reason: str = "agent_error"):
        """EVALUATOR ONLY: end the episode when the agent process crashed, hung or broke the protocol.

        Scored exactly like a timeout: truncated, empty final answer.
        """
        st = self._state
        if st is None or st.done:
            return None
        return self._truncate(self._error_obs("time_limit", max(0, MAX_STEPS - st.steps)), reason)

    @property
    def steps_used(self) -> int:
        return 0 if self._state is None else self._state.steps

    # ------------------------------------------------------------------ internals
    def _dispatch(self, action: Any, name: Any) -> dict:
        if not isinstance(action, dict) or name not in _ACTION_MODELS:
            raise ToolError("invalid_action")
        try:
            parsed = _ACTION_MODELS[name].model_validate(action)
        except ValidationError:
            raise ToolError("invalid_action") from None
        tb = self._state.toolbox
        if isinstance(parsed, ListRecordsAction):
            return tb.list_records(parsed.table, parsed.cursor, parsed.limit)
        if isinstance(parsed, GetRecordAction):
            return tb.get_record(parsed.table, parsed.id)
        if isinstance(parsed, GetDocumentAction):
            return tb.get_document(parsed.doc_id)
        return tb.calculator(parsed.expression)

    def _submit(self, action: dict, remaining: int):
        st = self._state
        inspection_steps = st.steps - 1
        raw = None if set(action) - {"action", "findings"} else action.get("findings")  # extra keys -> invalid
        if st.judge is not None:
            outcome = st.judge.submit(raw, inspection_steps)
            valid = outcome.valid
        else:  # closed episode without truth: structure check only, no scoring here
            outcome = None
            valid = validate_submission(raw, st.manifest["episode_id"])[0] is not None
        if valid:
            st.accepted_findings = copy.deepcopy(raw)
        st.done = st.terminated = True
        if valid:
            obs = {"ok": True, "result": {"status": "submitted"}, "error": None, "remaining_steps": remaining}
        else:
            obs = self._error_obs("invalid_submission", remaining)
        return obs, self._visible_reward(outcome), True, False, {}

    def _truncate(self, obs: dict, reason: str):
        st = self._state
        outcome = st.judge.empty_answer(st.steps, reason) if st.judge is not None else None
        st.done = st.truncated = True
        return obs, self._visible_reward(outcome), False, True, {"truncation_reason": reason, "final_answer": "empty"}

    def _visible_reward(self, outcome: Outcome | None) -> float:
        if self.mode != "train" or outcome is None:
            return 0.0
        return outcome.reward

    @staticmethod
    def _error_obs(code: str, remaining: int) -> dict:
        return {"ok": False, "result": None, "error": {"code": code, "message": ERROR_MESSAGES[code]},
                "remaining_steps": remaining}


__all__ = ["OphanimEnv", "MAX_STEPS", "TIME_LIMIT_SECONDS", "ACTION_NAMES"]
