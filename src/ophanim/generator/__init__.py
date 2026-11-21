"""Episode generator (evaluator side).

Pipeline (see episode.py):
  profile -> consistent hidden history -> correct postings -> accounting self-check
  -> causal error injection (truth + provenance) -> presentation (ids, names, order)
  -> public dataset + sealed evaluator bundle.

Nothing in this package is reachable through the agent's tools.
"""

from ophanim.generator.episode import GeneratedEpisode, PublicEpisode, SealedEpisode, generate_episode

__all__ = ["GeneratedEpisode", "PublicEpisode", "SealedEpisode", "generate_episode"]
