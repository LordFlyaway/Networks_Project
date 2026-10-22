"""
Writes small packet captures you can open in Wireshark:

    results/capture_random_rotation.pcap
    results/capture_amr.pcap

3 laptops, 15 simulated minutes, 5-minute slots. Each frame is a real
Ethernet frame (built with Scapy) from the laptop's current MAC to the router.
Payloads are random bytes standing in for encrypted data, and are cut to
64 bytes to keep the files small.

In Wireshark, use Statistics -> Endpoints -> Ethernet to see the MAC
addresses change, or filter with  eth.src == <mac>
"""

import os
import random

from scapy.all import Ether, Raw, wrpcap

from amr.simulation import simulate

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
ROUTER_MAC = "02:00:00:00:00:01"


def export(scheme, fname):
    r = simulate(scheme, n_devices=3, duration=900, epoch_seconds=300, seed=7, n_intruder_frames=0)
    rng = random.Random(1)
    pkts = []
    f = r.frames
    for t, m, size in zip(f["t"], f["mac"], f["size"]):
        # 0x88B5 = IEEE "local experimental" EtherType, so Wireshark shows the
        # payload as plain data instead of trying to decode it as IP.
        p = Ether(src=r.macs[m], dst=ROUTER_MAC, type=0x88B5) / Raw(rng.randbytes(min(int(size), 64)))
        p.time = float(t)
        pkts.append(p)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, fname)
    wrpcap(path, pkts)
    print(f"{scheme:10s} -> {path}  ({len(pkts)} frames, {len(r.macs)} different MACs)")


if __name__ == "__main__":
    export("naive", "capture_random_rotation.pcap")
    export("amr", "capture_amr.pcap")
