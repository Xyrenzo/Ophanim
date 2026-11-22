"""Official Genesis FinTech jury adapter (see `fintech-checks.txt`, "Единый способ подключения").

The jury imports the root-level ``judge_adapter.py``, which re-exports the three entry points below.

    generate_episode(seed, config, output_dir) -> None
    make_env() -> JudgeEnv                              # .reset(seed, config) / .step(action)
    score_episode(episode_dir, findings, inspection_steps) -> dict

This module is a thin translation layer over the existing components; it contains no scoring or
environment logic of its own:

* generation  -> ``ophanim.generator.episode.generate_episode``  (unchanged)
* loading     -> ``ophanim.audit.dataset.PublicDataset.from_directory`` (stdlib reader, file order kept)
* environment -> ``ophanim.env.OphanimEnv``  (``reset`` = generate, ``reset_loaded`` = load)
* scoring     -> ``ophanim.evaluator.judge.Judge``  (the shared matcher + official reward)

Episode directory layout written by ``generate_episode`` and read by ``reset``/``score_episode``::

    <episode_dir>/public/{manifest.json, policy.json, ledger.csv, invoices.jsonl, payments.jsonl, fx.csv}
    <episode_dir>/evaluator/{truth.json, provenance.json}          # jury side only

Isolation: in closed mode the environment reads ``public/`` only and holds no truth, provenance, seed or
path; it validates the structure of a submission and returns reward 0.0 at every step, including the
last one. Scoring happens only in ``score_episode``, in the jury's evaluator process.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

from ophanim.env.environment import MAX_STEPS, TIME_LIMIT_SECONDS, OphanimEnv
from ophanim.env.task import TASK_TEXT
from ophanim.generator.episode import PublicEpisode, SealedEpisode
from ophanim.schemas import TruthFile
from ophanim.version import ENV_VERSION, SCHEMA_VERSION

ACTION_NAMES = ("list_records", "get_record", "get_document", "calculator", "submit")
ADAPTER_CONFIG_KEYS = frozenset({"mode", "episode_dir", "team_config"})
PUBLIC_DIR = "public"
EVALUATOR_DIR = "evaluator"
_LOG = logging.getLogger("ophanim.judge_adapter")

ADAPTER_TASK_TEXT = TASK_TEXT + """
Action format: every action is a JSON object {"name": <action>, "args": {...}}. Each action, valid or
not, uses one of the 100 steps; submit is the last one and is not an inspection step.
  list_records  args {"table": "ledger"|"invoices"|"payments"|"fx", "cursor": null or next_cursor, "limit": 1-50}
                -> {"records": [...], "next_cursor": string or null}
  get_record    args {"table": ..., "id": row_id | invoice_id | payment_id | FX key "YYYY-MM-DD:SRC:BASE"}
                -> the record
  get_document  args {"doc_id": ...} -> the invoice or payment document
  calculator    args {"expression": "..."} -> the exact result as a decimal string
  submit        args {"findings": {"episode_id": ..., "findings": [...]}} -> {"accepted": true}
Observations after an action: {"result": ..., "error": null or {"code", "message"}, "remaining_steps": int}.
"""


# --------------------------------------------------------------------------- config
def _split_config(config: Any) -> tuple[str, str | None, dict]:
    """Return (mode, episode_dir, team_config) from an adapter config.

    Accepted forms: the official ``{"mode", "episode_dir", "team_config"}`` object (every key
    optional, mode defaults to "train"), or a bare team configuration (an ``EpisodeConfig`` object).
    """
    if config is None:
        return "train", None, {}
    if not isinstance(config, dict):
        raise TypeError("config must be a JSON object")
    if not set(config) & ADAPTER_CONFIG_KEYS:
        return "train", None, dict(config)  # bare team configuration
    unknown = set(config) - ADAPTER_CONFIG_KEYS
    if unknown:
        raise ValueError(f"unknown adapter config keys: {sorted(unknown)}")
    mode = config.get("mode", "train")
    if mode not in ("train", "closed"):
        raise ValueError("mode must be 'train' or 'closed'")
    team = config.get("team_config") or {}
    if not isinstance(team, dict):
        raise TypeError("team_config must be a JSON object")
    episode_dir = config.get("episode_dir")
    if episode_dir is not None and not isinstance(episode_dir, (str, os.PathLike)):
        raise TypeError("episode_dir must be a path")
    return mode, (None if episode_dir is None else os.fspath(episode_dir)), dict(team)


# --------------------------------------------------------------------------- episode files
def generate_episode(seed: int, config: dict, output_dir: str) -> None:
    """Write one deterministic episode to ``output_dir`` (layout in the module docstring).

    ``config`` is the team configuration (``EpisodeConfig``: profile, size, errors, scenarios,
    distractors, presentation), given bare or as ``{"team_config": {...}}``. The same
    (seed, config, ENV_VERSION) always writes byte-identical files. If the environment variable
    ``OPHANIM_EVAL_SECRET`` is set in the jury process, generation is additionally keyed with it
    (defence against seed brute force with the open-source generator).
    """
    from ophanim.generator.episode import generate_episode as _generate

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an int")
    _, _, team = _split_config(config)
    secret = os.environ.get("OPHANIM_EVAL_SECRET")
    episode = _generate(seed, team, secret=secret.encode("utf-8") if secret else None)
    episode.write(Path(output_dir))


def load_public_episode(episode_dir: str | os.PathLike) -> PublicEpisode:
    """Read ``<episode_dir>/public`` exactly as stored: same ids, same record order, no regeneration."""
    from ophanim.audit.dataset import PublicDataset

    ds = PublicDataset.from_directory(Path(episode_dir) / PUBLIC_DIR)
    return PublicEpisode(manifest=ds.manifest, policy=ds.policy,
                         tables={"ledger": ds.ledger, "invoices": ds.invoices, "payments": ds.payments, "fx": ds.fx})


def load_sealed_episode(episode_dir: str | os.PathLike, public: PublicEpisode) -> SealedEpisode:
    """Read ``<episode_dir>/evaluator`` (jury side only). The evidence universe comes from the public files."""
    d = Path(episode_dir) / EVALUATOR_DIR
    truth = TruthFile.model_validate(json.loads((d / "truth.json").read_text(encoding="utf-8")))
    provenance = json.loads((d / "provenance.json").read_text(encoding="utf-8"))
    return SealedEpisode(truth=truth, provenance=provenance, evidence_universe=public.evidence_universe())


# --------------------------------------------------------------------------- environment
def translate_action(action: Any) -> tuple[Any, str | None]:
    """``{"name", "args"}`` -> the native flat action. Malformed envelopes become an invalid action."""
    malformed = {"action": "__malformed_envelope__"}
    if not isinstance(action, dict) or "name" not in action or set(action) - {"name", "args"}:
        return malformed, None
    name = action["name"]
    args = action.get("args")
    if args is None:
        args = {}
    if not isinstance(name, str) or not isinstance(args, dict) or "action" in args:
        return malformed, None
    native = dict(args)
    native["action"] = name
    return native, name


def _shape_observation(native_obs: dict, name: str | None) -> dict:
    """Native step observation -> official ``{"result", "error", "remaining_steps"}``."""
    out = {"result": None, "error": None, "remaining_steps": native_obs["remaining_steps"]}
    if not native_obs.get("ok"):
        out["error"] = native_obs["error"]
        return out
    result = native_obs["result"]
    if name == "list_records":
        out["result"] = {"records": result["records"], "next_cursor": result["next_cursor"]}
    elif name == "get_record":
        out["result"] = result["record"]
    elif name == "get_document":
        out["result"] = result["document"]
    elif name == "calculator":
        out["result"] = result["result"]
    elif name == "submit":
        out["result"] = {"accepted": True}
    return out


class JudgeEnv:
    """Environment object returned by ``make_env()``.

    ``reset(seed, config)`` / ``reset(seed=..., options=config)``:
      * ``{"mode": "closed", "episode_dir": d, ...}`` -> load ``d/public`` as-is; no truth is loaded;
        reward 0.0 everywhere; a repeated reset re-reads the same directory and starts it again.
      * ``{"mode": "train", "episode_dir": d}`` -> load ``d/public`` and ``d/evaluator``; the terminal
        reward is returned to the policy.
      * ``{"mode": "train", "team_config": {...}}`` (no ``episode_dir``) -> generate from ``seed``.
    ``step({"name": ..., "args": {...}})`` -> (observation, reward, terminated, truncated, info).
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 time_limit_seconds: float = TIME_LIMIT_SECONDS) -> None:
        self._clock = clock
        self._time_limit = time_limit_seconds
        self._env: OphanimEnv | None = None
        self._mode: str | None = None

    def reset(self, seed: int | None = None, config: dict | None = None, *, options: dict | None = None):
        mode, episode_dir, team = _split_config(config if config is not None else options)
        env = OphanimEnv(mode="eval" if mode == "closed" else "train", clock=self._clock,
                         time_limit_seconds=self._time_limit)
        if episode_dir is not None:
            public = load_public_episode(episode_dir)
            sealed = load_sealed_episode(episode_dir, public) if mode == "train" else None
            native_obs, _ = env.reset_loaded(public, sealed)
        elif mode == "closed":
            raise ValueError("closed mode requires episode_dir")
        else:
            native_obs, _ = env.reset(seed, team)
        self._env, self._mode = env, mode
        observation = {
            "task": ADAPTER_TASK_TEXT,
            "manifest": native_obs["manifest"],
            "policy": native_obs["policy"],
            "remaining_steps": native_obs["remaining_steps"],
        }
        info = {"env_version": ENV_VERSION, "schema_version": SCHEMA_VERSION, "mode": mode}
        return observation, info

    def step(self, action: Any):
        if self._env is None:
            raise RuntimeError("reset() must be called before step()")
        native, name = translate_action(action)
        obs, reward, terminated, truncated, info = self._env.step(native)
        return _shape_observation(obs, name), float(reward), bool(terminated), bool(truncated), dict(info)

    # -- jury conveniences (public quantities only; nothing derived from truth)
    @property
    def steps_used(self) -> int:
        return 0 if self._env is None else self._env.steps_used

    @property
    def inspection_steps(self) -> int:
        """Steps before the final submit (all steps if the episode ended without a submit)."""
        if self._env is None:
            return 0
        st = self._env._state
        return st.steps - 1 if (st is not None and st.terminated) else self._env.steps_used

    @property
    def submitted_findings(self) -> dict | None:
        """The structurally valid findings object accepted by submit, if any."""
        return None if self._env is None else self._env.accepted_findings


def make_env(*, clock: Callable[[], float] = time.monotonic, time_limit_seconds: float = TIME_LIMIT_SECONDS) -> JudgeEnv:
    """Factory used by the jury. Optional keyword arguments exist only for tests."""
    return JudgeEnv(clock=clock, time_limit_seconds=time_limit_seconds)


# --------------------------------------------------------------------------- scoring
_NULL_SCORE = {"tp": None, "fp": None, "fn": None, "precision": None, "recall": None, "f1": None}


def score_episode(episode_dir: str, findings: dict, inspection_steps: int) -> dict:
    """Closed evaluator call: score ``findings`` against ``<episode_dir>/evaluator/truth.json``.

    Uses the shared judge (one-to-one matcher + official reward). A structurally invalid submission
    returns ``return = -1`` with every other field ``null``; the reasons go to the evaluator log
    (logger ``ophanim.judge_adapter``), never to the policy.
    """
    if isinstance(inspection_steps, bool) or not isinstance(inspection_steps, int) or inspection_steps < 0:
        raise ValueError("inspection_steps must be a non-negative int")
    from ophanim.evaluator.judge import Judge

    public = load_public_episode(episode_dir)
    judge = Judge(sealed=load_sealed_episode(episode_dir, public))
    out = judge.submit(findings, inspection_steps)
    if not out.valid:
        _LOG.warning("invalid submission (episode %s): %s", public.episode_id, judge.log[-1].get("errors"))
        return dict(_NULL_SCORE, **{"return": -1.0})
    return {"tp": out.tp, "fp": out.fp, "fn": out.fn, "precision": out.precision, "recall": out.recall,
            "f1": out.f1, "return": out.reward}


# --------------------------------------------------------------------------- smoke test
def smoke() -> int:
    """End-to-end self-check of the three entry points (``python judge_adapter.py --smoke``)."""
    import tempfile

    from ophanim.evaluator.oracle import oracle_submission

    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="ophanim-adapter-") as tmp:
        cfg = {"errors": {"duplicate_invoice": 1, "payment_allocation": 1, "fx_rate": 1, "period_attribution": 1}}
        generate_episode(7, cfg, tmp)
        public = load_public_episode(tmp)
        env = make_env()
        obs, info = env.reset(seed=7, options={"mode": "closed", "episode_dir": tmp, "team_config": {}})
        checks["first_observation_keys"] = sorted(obs) == ["manifest", "policy", "remaining_steps", "task"]
        o, r1, *_ = env.step({"name": "list_records", "args": {"table": "ledger", "cursor": None, "limit": 50}})
        checks["list_records"] = len(o["result"]["records"]) == 50 and r1 == 0.0
        row = o["result"]["records"][0]
        o, *_ = env.step({"name": "get_record", "args": {"table": "ledger", "id": row["row_id"]}})
        checks["get_record"] = o["result"] == row
        doc = public.tables["invoices"][0]
        o, *_ = env.step({"name": "get_document", "args": {"doc_id": doc["doc_id"]}})
        checks["get_document"] = o["result"] == doc
        o, *_ = env.step({"name": "calculator", "args": {"expression": "0.1+0.2"}})
        checks["calculator"] = o["result"] == "0.3"
        o, *_ = env.step({"name": "unknown_action", "args": {}})
        checks["unknown_action"] = o["error"] is not None and o["remaining_steps"] == 95  # 5th action
        sub = oracle_submission(load_sealed_episode(tmp, public))  # jury-side oracle
        o, reward, terminated, truncated, info = env.step({"name": "submit", "args": {"findings": sub}})
        checks["submit_closed"] = o["result"] == {"accepted": True} and reward == 0.0 and terminated and info == {}
        score = score_episode(tmp, sub, env.inspection_steps)
        checks["score_episode"] = score["tp"] == len(sub["findings"]) and abs(score["return"] - (1 - 0.002 * 5)) < 1e-9
    print(json.dumps({"ok": all(checks.values()), "checks": checks}, indent=2))
    return 0 if all(checks.values()) else 1
