"""
Simple traffic model for each simulated device.

A device moves between a few activities (idle, browsing, video call, streaming).
Each activity has a typical frame rate and frame size, and each device is
slightly different from the others. This gives the observer something
realistic to try to recognise devices by.
"""

import numpy as np

ACTIVITIES = {
    #             frames/sec   mean frame size (bytes)
    "idle":      (0.3,  150),
    "browsing":  (3.0,  700),
    "call":      (8.0,  420),
    "streaming": (15.0, 1300),
}
NAMES = list(ACTIVITIES)


def activity_timeline(rng: np.random.Generator, duration: float, mean_dwell: float = 240.0):
    """List of (start, end, activity) covering [0, duration)."""
    prefs = rng.dirichlet(np.ones(len(NAMES)) * 2.0)   # each device has its own habits
    t, out = 0.0, []
    while t < duration:
        act = NAMES[rng.choice(len(NAMES), p=prefs)]
        end = min(duration, t + rng.exponential(mean_dwell))
        out.append((t, end, act))
        t = end
    return out


def frames_between(rng, timeline, start, end, rate_scale, size_scale):
    """Frame timestamps and sizes a device sends between start and end."""
    times, sizes = [], []
    for a, b, act in timeline:
        lo, hi = max(a, start), min(b, end)
        if hi <= lo:
            continue
        rate, size = ACTIVITIES[act]
        n = rng.poisson(rate * rate_scale * (hi - lo))
        times.append(np.sort(rng.uniform(lo, hi, n)))
        sizes.append(np.clip(rng.normal(size * size_scale, 90, n), 60, 1514))
    if not times:
        return np.empty(0), np.empty(0)
    return np.concatenate(times), np.concatenate(sizes)


def mean_rate(timeline, start, end, rate_scale):
    """Expected frames/sec over an interval (used to estimate lost frames)."""
    total = 0.0
    for a, b, act in timeline:
        lo, hi = max(a, start), min(b, end)
        if hi > lo:
            total += ACTIVITIES[act][0] * rate_scale * (hi - lo)
    return total / max(end - start, 1e-9)
