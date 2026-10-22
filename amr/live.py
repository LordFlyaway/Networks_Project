"""
Live view of one simulated network, for the dashboard.

A LiveRun runs the simulation once for the chosen settings, then the dashboard
moves a clock forward in real time and asks for the state "as of" that clock.
Things only appear once the clock reaches them:

  * each MAC change, and the router's decision about it (made live, by a real
    Gateway object, as the clock passes)
  * the observer's guess about each change, shown 30 s after the new MAC first
    appears (that is how much traffic it waits for before guessing)
  * traffic rates, counters and the event log
"""

import ipaddress
import random

import numpy as np

from .gateway import Gateway
from .observer import WINDOW, link
from .protocol import derive_mac, epoch_of, random_mac
from .simulation import simulate


class LiveRun:
    def __init__(self, scheme, n_devices, epoch_seconds, duration, seed=0):
        self.scheme = scheme
        self.T = epoch_seconds
        self.duration = duration
        self.r = simulate(scheme, n_devices=n_devices, duration=duration,
                          epoch_seconds=epoch_seconds, seed=seed, n_intruder_frames=0)
        self.devices = self.r.extra["devices"]
        self.n = len(self.devices)
        f = self.r.frames
        self.ft, self.fdev, self.fmac = f["t"], f["dev"], f["mac"]

        self.segments = sorted(self.r.segments, key=lambda s: s.start)
        self.rotations = sorted(self.r.rotations, key=lambda x: x.time)
        self.mac_idx = {m: i for i, m in enumerate(self.r.macs)}
        self.dev_of_mac = {self.mac_idx[s.mac]: s.device for s in self.segments}

        # Real next-MAC for every MAC (ground truth) and the observer's guesses.
        truth = {}
        by_dev = {}
        for s in self.segments:
            by_dev.setdefault(s.device, []).append(s)
        for segs in by_dev.values():
            for a, b in zip(segs, segs[1:]):
                truth[self.mac_idx[a.mac]] = self.mac_idx[b.mac]
        self.truth = truth
        first_seen = {}
        order = np.argsort(self.fmac, kind="stable")
        bounds = np.searchsorted(self.fmac[order], np.arange(len(self.r.macs) + 1))
        for m in range(len(self.r.macs)):
            idx = order[bounds[m]:bounds[m + 1]]
            if len(idx):
                first_seen[m] = float(self.ft[idx].min())
        self.guesses = []
        for o, nmac in link(self.r):
            reveal = min(first_seen.get(nmac, 0.0) + WINDOW, duration)
            self.guesses.append({
                "time": reveal, "old": self.r.macs[o], "new": self.r.macs[nmac],
                "old_dev": self.dev_of_mac[o], "new_dev": self.dev_of_mac[nmac],
                "change_time": first_seen.get(nmac, 0.0),
                "correct": truth.get(o) == nmac,
            })
        self.guesses.sort(key=lambda g: g["time"])

        # Live router state.
        self.gateway = Gateway(self.T) if scheme.startswith("amr") else None
        if self.gateway:
            for d in self.devices:
                self.gateway.register(d["id"], d["key"], d["ip"])
        self.ip = {i: d["ip"] for i, d in enumerate(self.devices)}
        self._ip_pool = ipaddress.ip_address("192.168.1.100")
        self.seg_ptr = 0
        self.current_mac = {}
        self.changes = {i: 0 for i in range(self.n)}
        self.router_log = []          # (time, text, kind)
        self.accepted = 0
        self.rejected = 0
        self.intruders = 0
        self._rng = random.Random(seed + 99)

    # -- live router -------------------------------------------------------
    def advance(self, clock):
        """Let the router handle every MAC change the clock has passed."""
        while self.seg_ptr < len(self.segments) and self.segments[self.seg_ptr].start <= clock:
            s = self.segments[self.seg_ptr]
            self.seg_ptr += 1
            name = self.devices[s.device]["id"]
            first = s.device not in self.current_mac
            self.current_mac[s.device] = s.mac
            if not first:
                self.changes[s.device] += 1
            if self.gateway:
                ok = self.gateway.admit(s.mac, s.start + 0.01) == name
                self.accepted += ok
                if not first:
                    self.router_log.append((s.start, f"{name} switched to {s.mac} — router expected it, "
                                            f"same IP {self.ip[s.device]}, connection kept" if ok else
                                            f"{name} switched to {s.mac} — NOT recognised", "ok" if ok else "bad"))
            elif not first:
                self._ip_pool += 1
                self.ip[s.device] = str(self._ip_pool)
                self.router_log.append((s.start, f"{name} appeared as unknown MAC {s.mac} — had to reconnect, "
                                        f"new IP {self.ip[s.device]} from DHCP, connections reset", "bad"))

    def inject_intruder(self, clock):
        mac = random_mac(self._rng)
        self.intruders += 1
        if self.gateway:
            ok = self.gateway.admit(mac, clock) is not None
            self.rejected += not ok
            self.router_log.append((clock, f"Intruder tried MAC {mac} — "
                                    + ("accepted?!" if ok else "REJECTED (not in the expected table)"),
                                    "bad" if ok else "ok"))
        else:
            self.router_log.append((clock, f"Intruder tried MAC {mac} — accepted, this router has no "
                                    "way to check addresses", "bad"))

    # -- read-only views ---------------------------------------------------
    def activity(self, d, clock):
        for a, b, act in self.devices[d]["timeline"]:
            if a <= clock < b:
                return act
        return "idle"

    def rates(self, clock, window=4.0):
        lo, hi = np.searchsorted(self.ft, [clock - window, clock])
        counts = np.bincount(self.fdev[lo:hi], minlength=self.n)
        return counts / window

    def traffic_history(self, clock, span=180.0, step=3.0):
        start = max(0.0, clock - span)
        edges = np.arange(start, clock + 1e-9, step)
        if len(edges) < 2:
            return np.array([]), np.zeros((self.n, 0))
        lo, hi = np.searchsorted(self.ft, [edges[0], edges[-1]])
        t, d = self.ft[lo:hi], self.fdev[lo:hi]
        out = np.zeros((self.n, len(edges) - 1))
        bins = np.clip(np.searchsorted(edges, t, side="right") - 1, 0, len(edges) - 2)
        np.add.at(out, (d, bins), 1)
        return edges[:-1], out / step

    def segments_until(self, clock):
        out = []
        for s in self.segments[:self.seg_ptr]:
            out.append((s.device, s.mac, s.start, min(s.end, clock)))
        return out

    def rotations_until(self, clock):
        return [x for x in self.rotations if x.time <= clock]

    def guesses_until(self, clock):
        return [g for g in self.guesses if g["time"] <= clock]

    def changes_judgeable(self, clock):
        """Real MAC changes old enough that the observer has had its 30 s to guess."""
        return sum(1 for x in self.rotations if x.time + x.downtime + WINDOW <= clock)

    def router_table(self, clock):
        if not self.gateway:
            return []
        rows = []
        for d in self.devices:
            e = epoch_of(clock, self.T)
            rows.append({"Laptop": d["id"],
                         f"Slot {e - 1} (previous)": derive_mac(d["key"], d["id"], e - 1),
                         f"Slot {e} (now)": derive_mac(d["key"], d["id"], e),
                         f"Slot {e + 1} (next)": derive_mac(d["key"], d["id"], e + 1)})
        return rows
