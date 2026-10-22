"""
Runs every experiment and saves graphs + a results summary to ./results

    python run_experiments.py           (full run, ~1-2 minutes)
    python run_experiments.py --quick   (fewer repeats, for a fast check)
"""

import argparse
import json
import os
import statistics as st
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from amr.gateway import Gateway
from amr.protocol import new_key
from amr.simulation import simulate, SCHEMES, LABELS
from amr.observer import link, score

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
COLORS = {"static": "#6b7280", "naive": "#dc2626", "amr_basic": "#f59e0b", "amr": "#16a34a", "amr_padded": "#2563eb"}


def run_once(scheme, **kw):
    r = simulate(scheme, **kw)
    s = score(r, link(r))
    hours = r.duration / 3600
    n_dev = len({seg.device for seg in r.segments})
    rots = r.rotations
    s.update({
        "rotations": len(rots),
        "sessions_reset_per_device_hour": sum(not x.session_kept for x in rots) / (n_dev * hours),
        "mean_downtime_s": st.mean(x.downtime for x in rots) if rots else 0.0,
        "frames_lost_per_change": st.mean(x.frames_lost for x in rots) if rots else 0.0,
        "gateway_failures": r.gateway_failures,
        "intruders_rejected": r.gateway_rejected_intruders,
        "extra_data_pct": 100 * r.extra["padding_overhead"],
    })
    if scheme == "static":
        s["linkage_accuracy"] = 1.0    # the address never changes: always trackable
    return s


def avg(runs, key):
    vals = [r[key] for r in runs]
    return st.mean(vals), (st.stdev(vals) if len(vals) > 1 else 0.0)


def main_comparison(seeds):
    print("1) Main comparison (20 laptops, 3 hours, 10-minute slots)")
    table = {}
    for scheme in SCHEMES:
        runs = [run_once(scheme, seed=s) for s in seeds]
        table[scheme] = {k: avg(runs, k) for k in runs[0]}
        a = table[scheme]
        print(f"   {LABELS[scheme]:18s} linked {a['linkage_accuracy'][0]*100:5.1f}%  "
              f"follow {a['mean_track_min'][0]:6.1f} min  "
              f"resets/dev-h {a['sessions_reset_per_device_hour'][0]:.2f}  "
              f"downtime {a['mean_downtime_s'][0]:.2f}s")
    return table


def epoch_sweep(seeds, epochs=(120, 300, 600, 1200, 1800)):
    print("2) Slot length sweep (AMR with fixes)")
    rows = []
    for T in epochs:
        runs = [run_once("amr", epoch_seconds=T, seed=s) for s in seeds]
        rows.append({"T": T, "track": avg(runs, "mean_track_min"),
                     "acc": avg(runs, "linkage_accuracy"),
                     "changes_per_hour": 3600 / T})
        print(f"   T={T:5d}s  follow {rows[-1]['track'][0]:6.1f} min  linked {rows[-1]['acc'][0]*100:5.1f}%")
    return rows


def crowd_sweep(seeds, sizes=(5, 10, 20, 40, 80)):
    print("3) Number-of-devices sweep")
    rows = {s: [] for s in ("naive", "amr", "amr_padded")}
    for scheme in rows:
        for n in sizes:
            runs = [run_once(scheme, n_devices=n, duration=2 * 3600, seed=s) for s in seeds]
            rows[scheme].append({"n": n, "acc": avg(runs, "linkage_accuracy")})
            print(f"   {LABELS[scheme]:18s} n={n:3d}  linked {rows[scheme][-1]['acc'][0]*100:5.1f}%")
    return rows


def gateway_overhead(sizes=(10, 100, 1000, 5000)):
    print("4) Gateway overhead (real timing of the HMAC table rebuild)")
    rows = []
    for n in sizes:
        gw = Gateway(600)
        for d in range(n):
            gw.register(f"laptop-{d}", new_key(), f"10.0.{d // 250}.{d % 250}")
        t0 = time.perf_counter()
        gw._refresh(0.0)
        ms = (time.perf_counter() - t0) * 1000
        rows.append({"n": n, "ms": ms, "entries": gw.table_size()})
        print(f"   {n:5d} devices: {ms:8.2f} ms per slot, {gw.table_size()} table entries")
    return rows


def plots(main, sweep, crowd, over):
    os.makedirs(OUT, exist_ok=True)
    names = [LABELS[s] for s in SCHEMES]
    cols = [COLORS[s] for s in SCHEMES]

    def bar(key, title, ylabel, fname, scale=1.0, fmt="{:.0f}"):
        fig, ax = plt.subplots(figsize=(7, 4.2))
        vals = [main[s][key][0] * scale for s in SCHEMES]
        errs = [main[s][key][1] * scale for s in SCHEMES]
        bars = ax.bar(names, vals, yerr=errs, color=cols, capsize=4)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(), fmt.format(v),
                    ha="center", va="bottom", fontsize=10)
        ax.set_title(title); ax.set_ylabel(ylabel)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout(); fig.savefig(os.path.join(OUT, fname), dpi=160); plt.close(fig)

    bar("linkage_accuracy", "How often the observer links old and new MAC",
        "MAC changes linked correctly (%)", "1_linkage_accuracy.png", 100, "{:.0f}%")
    bar("mean_track_min", "How long the observer can follow one device",
        "Average continuous tracking (minutes)", "2_tracking_time.png", 1, "{:.0f}")
    bar("sessions_reset_per_device_hour", "Connections broken by MAC changes",
        "Connection resets per device per hour", "3_connection_resets.png", 1, "{:.1f}")
    bar("mean_downtime_s", "Time offline at each MAC change",
        "Average downtime per change (s)", "4_downtime.png", 1, "{:.2f}")
    bar("extra_data_pct", "Extra data sent (cost of padding)",
        "Extra data (%)", "8_extra_data.png", 1, "{:.0f}%")

    fig, ax = plt.subplots(figsize=(7, 4.2))
    x = [r["T"] / 60 for r in sweep]
    ax.plot(x, [r["track"][0] for r in sweep], "o-", color=COLORS["amr"], label="Tracking time (min)")
    ax.set_xlabel("Slot length (minutes)"); ax.set_ylabel("Average continuous tracking (min)")
    ax2 = ax.twinx()
    ax2.plot(x, [r["changes_per_hour"] for r in sweep], "s--", color="#2563eb", label="MAC changes per hour")
    ax2.set_ylabel("MAC changes per hour")
    ax.set_title("Trade-off: shorter slots = less tracking, more changes")
    fig.legend(loc="upper center", bbox_to_anchor=(0.5, 0.88))
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "5_slot_length_tradeoff.png"), dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for s, rows in crowd.items():
        ax.plot([r["n"] for r in rows], [r["acc"][0] * 100 for r in rows], "o-",
                color=COLORS[s], label=LABELS[s])
    ax.set_xscale("log"); ax.set_xticks([r["n"] for r in crowd["amr"]])
    ax.set_xticklabels([r["n"] for r in crowd["amr"]])
    ax.set_xlabel("Devices on the network"); ax.set_ylabel("MAC changes linked (%)")
    ax.set_ylim(0, 105); ax.legend(); ax.set_title("More devices = harder to track")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "6_crowd_size.png"), dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.plot([r["n"] for r in over], [r["ms"] for r in over], "o-", color="#7c3aed")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Devices registered at the gateway"); ax.set_ylabel("Time to prepare next slot (ms)")
    ax.set_title("Gateway overhead (measured)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "7_gateway_overhead.png"), dpi=160); plt.close(fig)


def write_summary(main, sweep, crowd, over, seeds, desc="20 laptops, 3 simulated hours, 10-minute slots."):
    lines = ["# Results", "", f"Averaged over {len(seeds)} runs (seeds {list(seeds)}). " + desc, "",
             "| Scheme | MAC changes linked | Avg. tracking time | Connection resets / device / hour | Downtime per change | Frames lost per change | Extra data |",
             "|---|---|---|---|---|---|---|"]
    for s in SCHEMES:
        a = main[s]
        lines.append(f"| {LABELS[s]} | {a['linkage_accuracy'][0]*100:.1f}% | {a['mean_track_min'][0]:.1f} min | "
                     f"{a['sessions_reset_per_device_hour'][0]:.2f} | {a['mean_downtime_s'][0]:.2f} s | "
                     f"{a['frames_lost_per_change'][0]:.1f} | {a['extra_data_pct'][0]:.0f}% |")
    g = main["amr"]
    lines += ["", f"Gateway check (AMR): {g['gateway_failures'][0]:.0f} unrecognised AMR addresses, "
              f"{g['intruders_rejected'][0]:.0f}/200 random intruder MACs rejected.", "",
              "## Slot length (AMR with fixes)", "", "| Slot | Tracking time | Linked | Changes/hour |", "|---|---|---|---|"]
    for r in sweep:
        lines.append(f"| {r['T']//60} min | {r['track'][0]:.1f} min | {r['acc'][0]*100:.1f}% | {r['changes_per_hour']:.0f} |")
    lines += ["", "## Number of devices", "", "| Devices | Random rotation linked | AMR (with fixes) linked | AMR + padding linked |", "|---|---|---|---|"]
    for a, b, c in zip(crowd["naive"], crowd["amr"], crowd["amr_padded"]):
        lines.append(f"| {a['n']} | {a['acc'][0]*100:.1f}% | {b['acc'][0]*100:.1f}% | {c['acc'][0]*100:.1f}% |")
    lines += ["", "## Gateway overhead (measured on this machine)", "", "| Devices | Time per slot | Table entries |", "|---|---|---|"]
    for r in over:
        lines.append(f"| {r['n']} | {r['ms']:.2f} ms | {r['entries']} |")
    with open(os.path.join(OUT, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"main": main, "slot_sweep": sweep, "crowd": crowd, "overhead": over}, f, indent=2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    seeds = range(2) if args.quick else range(5)
    small = range(1) if args.quick else range(3)
    os.makedirs(OUT, exist_ok=True)
    main = main_comparison(seeds)
    sweep = epoch_sweep(small)
    crowd = crowd_sweep(small)
    over = gateway_overhead()
    plots(main, sweep, crowd, over)
    write_summary(main, sweep, crowd, over, seeds)
    print(f"\nSaved graphs and results to {OUT}")
