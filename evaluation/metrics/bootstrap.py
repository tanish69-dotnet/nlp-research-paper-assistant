"""Style-free bootstrap (EVALUATION.md §7, point 4).

Paired bootstrap over cases — accepts a ``seed`` so a re-run of a stochastic
forecast still produces a deterministic confidence interval for the *same*
bootstrapped sample.
"""

from __future__ import annotations

import math
import random
from typing import Any


def paired_bootstrap_ci(
    before: list[float],
    after: list[float],
    *,
    n_bootstrap: int = 5000,
    level: float = 0.95,
    seed: int = 17,
    handle_insufficient: str | None = None,
) -> dict[str, Any]:
    if len(before) != len(after):
        raise ValueError("before and after must have equal length")
    if len(before) < 5:
        return {
            "status": "insufficient",
            "reason": "bootstrap requires >=5 paired examples",
            "n": len(before),
            "ci_lo": None,
            "ci_hi": None,
        }
    if handle_insufficient is not None:
        raise ValueError("handle_insufficient is not yet implemented — omit this arg")

    rng = random.Random(seed)
    diffs = [after_value - before_value for before_value, after_value in zip(before, after)]
    observed = sum(diffs) / len(diffs)

    resampled: list[float] = []
    for _ in range(n_bootstrap):
        sample = [rng.choice(diffs) for _ in range(len(diffs))]
        resampled.append(sum(sample) / len(sample))

    resampled.sort()
    alpha = 1 - level
    lo_index = math.ceil(alpha / 2 * len(resampled)) - 1
    hi_index = math.ceil((1 - alpha / 2) * len(resampled)) - 1
    lo_index = max(0, min(lo_index, len(resampled) - 1))
    hi_index = max(0, min(hi_index, len(resampled) - 1))

    return {
        "status": "computed",
        "observed_mean_diff": observed,
        "n": len(diffs),
        "n_bootstrap": n_bootstrap,
        "seed": seed,
        "level": level,
        "ci_lo": resampled[lo_index],
        "ci_hi": resampled[hi_index],
    }
