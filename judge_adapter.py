"""OPHANIM - official Genesis FinTech jury adapter (entry point).

Run from the repository root (Docker: WORKDIR /app):

    import judge_adapter
    judge_adapter.generate_episode(seed, config, output_dir)
    env = judge_adapter.make_env()
    observation, info = env.reset(seed, {"mode": "closed", "episode_dir": output_dir, "team_config": {}})
    observation, reward, terminated, truncated, info = env.step({"name": "list_records", "args": {...}})
    scores = judge_adapter.score_episode(output_dir, findings, inspection_steps)

Self-check:  python judge_adapter.py --smoke

The implementation lives in ``src/ophanim/adapter.py``; see README, section "Official judge adapter".
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ophanim.adapter import generate_episode, make_env, score_episode  # noqa: E402

__all__ = ["generate_episode", "make_env", "score_episode"]

if __name__ == "__main__":
    if sys.argv[1:] == ["--smoke"]:
        from ophanim.adapter import smoke

        sys.exit(smoke())
    print(__doc__)
