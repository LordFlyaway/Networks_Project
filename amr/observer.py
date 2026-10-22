"""
The outside observer: someone on the network trying to follow devices.

It only sees what is visible in the air / on the wire: source MAC, time,
frame size and sequence number. Whenever a MAC disappears and new MACs
appear, it guesses which new MAC belongs to the same device, using three
clues from the research papers:

  * timing    - a new MAC showing up right after an old one vanished
  * sequence  - the frame counter carrying on from where it stopped
  * behaviour - similar traffic (rate and frame size) just before and after

It picks the best overall pairing with the Hungarian algorithm
(scipy's linear_sum_assignment).
"""

import numpy as np
from scipy.optimize import linear_sum_assignment

from .simulation import SEQ_MOD

EDGE = 30.0          # ignore MACs that start/end near the edges of the capture
MAX_GAP = 60.0       # a new MAC more than 60 s later is not considered
WINDOW = 30.0        # seconds of traffic compared before/after a change
NO_LINK = 1e6


def _profile(t, size, lo, hi):
    m = (t >= lo) & (t < hi)
    n = int(m.sum())
    rate = (n + 0.5) / max(hi - lo, 1.0)
    mean_size = float(size[m].mean()) if n else 0.0
    return rate, mean_size


def _summaries(frames, n_macs):
    t, mac, size, seq = frames["t"], frames["mac"], frames["size"], frames["seq"]
    out = {}
    order = np.argsort(mac, kind="stable")
    bounds = np.searchsorted(mac[order], np.arange(n_macs + 1))
    for m in range(n_macs):
        idx = order[bounds[m]:bounds[m + 1]]
        if len(idx) == 0:
            continue
        tt, ss, qq = t[idx], size[idx], seq[idx]
        first, last = tt[0], tt[-1]
        out[m] = {
            "first": first, "last": last,
            "first_seq": int(qq[0]), "last_seq": int(qq[-1]),
            "before": _profile(tt, ss, last - WINDOW, last + 1e-9),
            "after": _profile(tt, ss, first, first + WINDOW),
        }
    return out


def link(result):
    """Return the observer's guesses as a list of (old_mac_idx, new_mac_idx)."""
    s = _summaries(result.frames, len(result.macs))
    D = result.duration
    olds = [m for m, v in s.items() if v["last"] < D - EDGE]
    news = [m for m, v in s.items() if v["first"] > EDGE]
    if not olds or not news:
        return []
    cost = np.full((len(olds), len(news)), NO_LINK)
    for i, o in enumerate(olds):
        so = s[o]
        for j, n in enumerate(news):
            sn = s[n]
            gap = sn["first"] - so["last"]
            if o == n or gap < -1.0 or gap > MAX_GAP:
                continue
            timing = abs(gap) / 10.0
            seq_jump = (sn["first_seq"] - so["last_seq"]) % SEQ_MOD
            sequence = 0.0 if seq_jump <= 3 else 1.0
            (r1, z1), (r2, z2) = so["before"], sn["after"]
            behaviour = abs(np.log(r1 / r2)) + abs(z1 - z2) / 300.0
            cost[i, j] = timing + 3.0 * sequence + behaviour
    rows, cols = linear_sum_assignment(cost)
    return [(olds[i], news[j]) for i, j in zip(rows, cols) if cost[i, j] < NO_LINK]


def score(result, guesses):
    """
    linkage_accuracy : share of real MAC changes the observer linked correctly
    mean_track_min   : on average, how long (minutes) the observer can follow
                       a device continuously before losing it
    """
    idx = {m: i for i, m in enumerate(result.macs)}
    by_dev = {}
    for seg in sorted(result.segments, key=lambda s: s.start):
        by_dev.setdefault(seg.device, []).append(seg)
    truth = {}
    for segs in by_dev.values():
        for a, b in zip(segs, segs[1:]):
            truth[idx[a.mac]] = idx[b.mac]
    guessed = dict(guesses)
    correct = sum(1 for o, n in truth.items() if guessed.get(o) == n)
    accuracy = correct / len(truth) if truth else float("nan")

    tracks = []
    for segs in by_dev.values():
        run = segs[0].end - segs[0].start
        for a, b in zip(segs, segs[1:]):
            if guessed.get(idx[a.mac]) == idx[b.mac]:
                run += b.end - a.end
            else:
                tracks.append(run)
                run = b.end - b.start
        tracks.append(run)
    return {
        "linkage_accuracy": accuracy,
        "true_changes": len(truth),
        "correct_links": correct,
        "mean_track_min": float(np.mean(tracks)) / 60.0,
    }
