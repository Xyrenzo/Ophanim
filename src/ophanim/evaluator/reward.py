"""Metrics and the OFFICIAL reward (exact formula from the case).

    P  = TP / (TP + FP)          (0 when the denominator is 0)
    R  = TP / (TP + FN)          (0 when the denominator is 0)
    F1 = 2TP / (2TP + FP + FN)   (1 when truth and findings are both empty)

    R_episode = clip(2 * F1 - 1 - 0.002 * inspection_steps, -1, 1)

inspection_steps = every step consumed before the final submit: list_records,
get_record, get_document, calculator AND invalid actions (they consume a step).
The submit step itself is not counted. On truncation (step or time limit) it is
the number of steps consumed. The same definition is used by the trajectory logger.

An invalid findings structure gives exactly -1.

Arithmetic is exact (fractions) and converted to float once, so the reward is
bit-identical on every platform. Episode return == terminal reward
(exploration steps return 0).
"""

from __future__ import annotations

from fractions import Fraction

INSPECTION_COST = Fraction(2, 1000)
INVALID_SUBMISSION_REWARD = -1.0


def precision(tp: int, fp: int) -> Fraction:
    return Fraction(tp, tp + fp) if tp + fp else Fraction(0)


def recall(tp: int, fn: int) -> Fraction:
    return Fraction(tp, tp + fn) if tp + fn else Fraction(0)


def f1(tp: int, fp: int, fn: int) -> Fraction:
    denominator = 2 * tp + fp + fn
    if denominator == 0:  # empty truth and empty findings
        return Fraction(1)
    return Fraction(2 * tp, denominator)


def official_reward(tp: int, fp: int, fn: int, inspection_steps: int) -> float:
    if inspection_steps < 0:
        raise ValueError("inspection_steps must be non-negative")
    raw = 2 * f1(tp, fp, fn) - 1 - INSPECTION_COST * inspection_steps
    return float(max(Fraction(-1), min(Fraction(1), raw)))
