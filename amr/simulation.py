"""
Runs one simulated network for a chosen addressing scheme.

Schemes compared
  static     - the laptop keeps one MAC forever (normal behaviour)
  naive      - the laptop picks a new random MAC every so often on its own,
               like today's OS randomisation would if it rotated while connected
  amr_basic  - our idea: key-derived MAC that the router knows in advance
  amr        - our idea plus two small fixes from the literature:
               a short random quiet period after switching, and restarting the
               frame sequence counter (Vanhoef et al. showed it leaks the link)
  amr_padded - amr plus frame padding: every frame is rounded up to one of
               3 sizes (256 / 768 / 1514 bytes), so frame size stops being a
               clue. Costs extra data, which is measured.

What the simulation models (assumptions, kept simple on purpose)
  * The observer sees only link-layer information: source MAC, time, frame
    size and the 12-bit sequence number. Payloads (including IP) are treated
    as encrypted, as on a WPA2/WPA3 Wi-Fi network.
  * naive: the router does not recognise the new MAC, so the device has to
    reconnect and ask DHCP for an address again (1-3 s offline). DHCP hands out
    a new IP, so open connections are reset.
  * amr: the router already expects the new MAC and keeps the same IP, so
    connections continue. Switching the interface takes ~50 ms.
"""

from dataclasses import dataclass, field
import random

import numpy as np

from .gateway import Gateway
from .protocol import derive_mac, new_key, random_mac
from .traffic import activity_timeline, frames_between, mean_rate

SCHEMES = ["static", "naive", "amr_basic", "amr", "amr_padded"]
LABELS = {
    "static": "Fixed MAC",
    "naive": "Random rotation",
    "amr_basic": "AMR (basic)",
    "amr": "AMR (with fixes)",
    "amr_padded": "AMR + padding",
}

SWITCH_TIME = 0.05     # seconds to change the interface's MAC
QUIET_MAX = 8.0        # amr: max random quiet period after switching
SEQ_MOD = 4096         # 802.11 sequence numbers are 12 bits
PAD_SIZES = np.array([256, 768, 1514])   # amr_padded: frame sizes are rounded up to one of these


@dataclass
class Segment:
    device: int
    mac: str
    start: float
    end: float


@dataclass
class Rotation:
    device: int
    time: float
    downtime: float
    session_kept: bool
    frames_lost: int


@dataclass
class SimResult:
    scheme: str
    duration: float
    segments: list
    rotations: list
    frames: dict                       # numpy arrays: t, mac_idx, size, seq, device
    macs: list                         # mac_idx -> mac string
    gateway_rejected_intruders: int = 0
    gateway_failures: int = 0          # AMR frames the gateway failed to recognise
    extra: dict = field(default_factory=dict)


def simulate(scheme: str, n_devices: int = 20, duration: float = 3 * 3600,
             epoch_seconds: float = 600, seed: int = 0, n_intruder_frames: int = 200):
    assert scheme in SCHEMES
    rng = np.random.default_rng(seed)
    prng = random.Random(seed)

    gateway = Gateway(epoch_seconds)
    devices = []
    for d in range(n_devices):
        dev = {
            "id": f"laptop-{d:02d}",
            "key": new_key(),
            "ip": f"192.168.1.{10 + d}",
            "skew": rng.uniform(-0.5, 0.5),           # NTP-level clock error
            "timeline": activity_timeline(rng, duration),
            "rate_scale": rng.uniform(0.8, 1.2),
            "size_scale": rng.uniform(0.9, 1.1),
        }
        devices.append(dev)
        if scheme.startswith("amr"):
            gateway.register(dev["id"], dev["key"], dev["ip"])

    segments, rotations = [], []
    for d, dev in enumerate(devices):
        segments_d, rot_d = _plan_device(scheme, d, dev, duration, epoch_seconds, rng, prng)
        segments += segments_d
        rotations += rot_d

    # Build every frame the observer could capture.
    mac_index, macs = {}, []
    cols = {"t": [], "mac": [], "size": [], "seq": [], "dev": []}
    seq_state = {}
    for seg in sorted(segments, key=lambda s: (s.device, s.start)):
        dev = devices[seg.device]
        t, size = frames_between(rng, dev["timeline"], seg.start, seg.end,
                                 dev["rate_scale"], dev["size_scale"])
        if seg.mac not in mac_index:
            mac_index[seg.mac] = len(macs)
            macs.append(seg.mac)
        if scheme in ("amr", "amr_padded") or seg.device not in seq_state:
            start_seq = int(rng.integers(SEQ_MOD))          # fresh counter
        else:
            start_seq = seq_state[seg.device]                # counter carries on
        seq = (start_seq + np.arange(len(t))) % SEQ_MOD
        seq_state[seg.device] = int((start_seq + len(t)) % SEQ_MOD)
        cols["t"].append(t)
        cols["mac"].append(np.full(len(t), mac_index[seg.mac]))
        cols["size"].append(size)
        cols["seq"].append(seq)
        cols["dev"].append(np.full(len(t), seg.device))
    frames = {k: np.concatenate(v) for k, v in cols.items()}
    real_bytes = float(frames["size"].sum())
    if scheme == "amr_padded":
        frames["size"] = PAD_SIZES[np.searchsorted(PAD_SIZES, frames["size"])].astype(float)
    padding_overhead = float(frames["size"].sum()) / real_bytes - 1 if real_bytes else 0.0
    order = np.argsort(frames["t"], kind="stable")
    frames = {k: v[order] for k, v in frames.items()}

    result = SimResult(scheme, duration, segments, rotations, frames, macs,
                       extra={"devices": devices, "epoch_seconds": epoch_seconds,
                              "padding_overhead": padding_overhead})

    # For AMR, check the gateway really recognises every new address
    # (using each laptop's slightly-off clock), and rejects unknown ones.
    if scheme.startswith("amr"):
        for seg in segments:
            probe_t = seg.start + 0.01
            if gateway.admit(seg.mac, probe_t) != devices[seg.device]["id"]:
                result.gateway_failures += 1
        for _ in range(n_intruder_frames):
            gateway.admit(random_mac(prng), prng.uniform(0, duration))
        result.gateway_rejected_intruders = gateway.rejected
    return result


def _plan_device(scheme, d, dev, duration, T, rng, prng):
    """Decide when this device changes MAC and what happens to its connection."""
    segs, rots = [], []
    if scheme == "static":
        segs.append(Segment(d, random_mac(prng), 0.0, duration))
        return segs, rots

    if scheme == "naive":
        t, mac = 0.0, random_mac(prng)
        while True:
            switch = t + T * rng.uniform(0.7, 1.3)        # each device on its own timer
            if switch >= duration:
                segs.append(Segment(d, mac, t, duration))
                break
            segs.append(Segment(d, mac, t, switch))
            offline = rng.uniform(1.0, 3.0)               # reconnect + DHCP
            lost = rng.poisson(mean_rate(dev["timeline"], switch, switch + offline,
                                         dev["rate_scale"]) * offline)
            rots.append(Rotation(d, switch, offline, session_kept=False, frames_lost=int(lost)))
            t, mac = switch + offline, random_mac(prng)
        return segs, rots

    # AMR: switch when the laptop's own clock crosses each slot boundary.
    # Laptop clock = real time + skew, so the real switch time is k*T - skew.
    epoch = 0
    start = 0.0
    while True:
        boundary = (epoch + 1) * T - dev["skew"]
        mac = derive_mac(dev["key"], dev["id"], epoch)
        if boundary >= duration:
            segs.append(Segment(d, mac, start, duration))
            break
        segs.append(Segment(d, mac, start, boundary))
        quiet = rng.uniform(0, QUIET_MAX) if scheme in ("amr", "amr_padded") else 0.0
        downtime = SWITCH_TIME + quiet
        # The router knows the new MAC and keeps the IP, so the connection stays.
        rots.append(Rotation(d, boundary, downtime, session_kept=True, frames_lost=0))
        start = boundary + downtime
        epoch += 1
    return segs, rots
