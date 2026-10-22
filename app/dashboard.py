"""AMR dashboard: live network, experiments, tests, how the address is computed, saved graphs.

    streamlit run app/dashboard.py        (or double-click run_dashboard.bat)
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import run_experiments as rx                                         # noqa: E402
from amr.live import LiveRun                                         # noqa: E402
from amr.observer import WINDOW                                      # noqa: E402
from amr.protocol import derive_mac, epoch_of, is_local_unicast, new_key  # noqa: E402
from amr.simulation import LABELS, SCHEMES                           # noqa: E402

RESULTS = ROOT / "results"
BLUE, INK, MUTED, GRID = "#2a78d6", "#1f1f1e", "#6b6a64", "#e4e3dc"
GOOD, BAD, WARN = "#0ca30c", "#d03b3b", "#fab219"
SCHEME_COLOR = {"static": "#8a8983", "naive": "#eb6834", "amr_basic": "#eda100", "amr": BLUE, "amr_padded": "#7c3aed"}
_draw_id = itertools.count()  # unique key per redraw, so identical charts don't clash
PAGES = ["Live network", "Experiments", "Tests", "Security tests", "How it works", "Saved graphs"]

st.set_page_config(page_title="AMR Dashboard", page_icon="🔁", layout="wide")


def style_fig(fig: go.Figure, height: int = 340) -> go.Figure:
    fig.update_layout(template="plotly_white", height=height, margin=dict(l=10, r=10, t=44, b=10),
                      font=dict(color=INK), legend=dict(orientation="h", y=1.1, x=0), hovermode="closest")
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def card(col, label: str, value: str, color: str = BLUE, sub: str = "") -> None:
    col.markdown(
        f"<div style='border-left:6px solid {color};padding:8px 14px;background:#f7f7f5;border-radius:6px'>"
        f"<div style='font-size:0.85em;color:{MUTED}'>{label}</div>"
        f"<div style='font-size:1.7em;font-weight:700;color:{INK};line-height:1.2'>{value}</div>"
        f"<div style='font-size:0.8em;color:{MUTED}'>{sub}&nbsp;</div></div>", unsafe_allow_html=True)


def clock_str(sec: float) -> str:
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def mac_color(mac: str) -> str:
    h = int(hashlib.md5(mac.encode()).hexdigest()[:6], 16) % 360
    return f"hsl({h},62%,58%)"


# --- sidebar -----------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🔁 AMR")
    st.caption("Authenticated MAC Address Rotation")
    # ?page=<name> opens a page directly (used for report screenshots); ?run=1 also presses its run button
    if "page" not in st.session_state and st.query_params.get("page") in PAGES:
        st.session_state.page = st.query_params["page"]
    page = st.radio("View", PAGES, key="page")
    st.caption("Krishiv Rajkumar · 24BDE0132  \nAsher Mathew · 24BDE0128")
    st.info("Everything here is a simulation of a local network. Router speed and the address maths are "
            "real measurements; reconnect times are modelled.", icon="ℹ️")


# --- live network ------------------------------------------------------------------

SLOT_OPTIONS = {15: "15 s", 30: "30 s", 60: "1 min", 120: "2 min", 300: "5 min", 600: "10 min", 1200: "20 min"}


def start_run(scheme, n, slot, minutes, seed):
    with st.spinner("Building the network…"):
        st.session_state.run = LiveRun(scheme, n, slot, minutes * 60, seed=seed)
    st.session_state.clock = 0.0
    st.session_state.last_real = time.time()
    st.session_state.playing = True


def page_live() -> None:
    st.title("Live network")
    st.caption("Laptops on one network change their MAC address every slot. Watch the router recognise them and "
               "the observer try to follow them. Change the settings and press **Start new run**.")

    c = st.columns([2, 1.3, 1.3, 1.2, 0.8, 1.2])
    scheme = c[0].selectbox("Addressing scheme", SCHEMES, index=4, format_func=LABELS.get)
    n = c[1].slider("Laptops", 3, 15, 8)
    slot = c[2].select_slider("Address changes every", list(SLOT_OPTIONS), value=60, format_func=SLOT_OPTIONS.get)
    minutes = c[3].selectbox("Run length (simulated)", [10, 20, 30, 60, 120], index=1, format_func=lambda m: f"{m} min")
    seed = c[4].number_input("Seed", 0, 999, 0)
    c[5].write("")
    if c[5].button("▶ Start new run", type="primary", width="stretch") or "run" not in st.session_state:
        start_run(scheme, n, slot, minutes, seed)
    st.slider("Playback speed (simulated seconds per real second)", 1, 120, 15, key="speed")
    live_view()


@st.fragment(run_every=1.0)
def live_view() -> None:
    run: LiveRun = st.session_state.run
    now = time.time()
    if st.session_state.playing:
        st.session_state.clock = min(run.duration, st.session_state.clock + (now - st.session_state.last_real) * st.session_state.speed)
        if st.session_state.clock >= run.duration:
            st.session_state.playing = False
    st.session_state.last_real = now
    clock = st.session_state.clock

    b = st.columns([1, 1, 1, 4])
    if b[0].button("⏸ Pause" if st.session_state.playing else "▶ Resume", width="stretch"):
        st.session_state.playing = not st.session_state.playing
        st.session_state.last_real = time.time()
    if b[1].button("🕵 Inject intruder", width="stretch", help="A device with a made-up MAC tries to get on"):
        run.inject_intruder(clock)
    if b[2].button("⏮ Restart", width="stretch"):
        st.session_state.run = LiveRun(run.scheme, run.n, run.T, run.duration)
        st.session_state.clock = 0.0
        st.session_state.playing = True
        st.rerun()
    run.advance(clock)

    rots = run.rotations_until(clock)
    guesses = run.guesses_until(clock)
    judge = run.changes_judgeable(clock)
    correct = sum(g["correct"] for g in guesses)
    broken = sum(not x.session_kept for x in rots)
    slot_now = epoch_of(clock, run.T)
    next_switch = (slot_now + 1) * run.T - clock

    st.progress(clock / run.duration, text=f"{LABELS[run.scheme]} · simulated time {clock_str(clock)} / "
                f"{clock_str(run.duration)} · {'playing' if st.session_state.playing else 'paused'}")
    k = st.columns(5)
    card(k[0], "Current slot", f"#{slot_now}" if run.scheme != "static" else "—", BLUE,
         f"next change in {next_switch:.0f} s" if run.scheme != "static" else "address never changes")
    card(k[1], "MAC changes so far", f"{len(rots)}", BLUE)
    card(k[2], "Connections broken", f"{broken}", BAD if broken else GOOD,
         "router lost the device" if broken else "router kept every connection")
    if run.gateway:
        card(k[3], "Router check", f"{run.accepted} ✓", GOOD, f"{run.rejected}/{run.intruders} intruders rejected")
    else:
        card(k[3], "Router check", "none", WARN, f"{run.intruders} intruders, all let in" if run.intruders else
             "router can't tell who is who")
    if run.scheme == "static":
        card(k[4], "Observer", "100%", BAD, "same address all the time: fully tracked")
    else:
        pct = correct / judge if judge else 0
        card(k[4], "Observer linked", f"{pct:.0%}" if judge else "—", BAD if pct > 0.7 else WARN if pct > 0.35 else GOOD,
             f"{correct} of {judge} changes linked")

    rates = run.rates(clock)
    table = pd.DataFrame({
        "Laptop": [d["id"] for d in run.devices],
        "Activity": [run.activity(i, clock) for i in range(run.n)],
        "IP address": [run.ip[i] for i in range(run.n)],
        "Current MAC": [run.current_mac.get(i, "") for i in range(run.n)],
        "MAC changes": [run.changes[i] for i in range(run.n)],
        "Frames / s": np.round(rates, 1),
    })
    left, right = st.columns([3, 2])
    left.markdown("**Laptops right now**")
    left.dataframe(table, hide_index=True, width="stretch", height=36 * (run.n + 1) + 4,
                   column_config={"Frames / s": st.column_config.ProgressColumn("Frames / s", min_value=0, max_value=25, format="%.1f")})

    log = [(t, txt, kind) for t, txt, kind in run.router_log]
    for g in guesses:
        who = run.devices[g["old_dev"]]["id"]
        if g["correct"]:
            log.append((g["time"], f"Observer linked {g['old']} → {g['new']} as {who} — correct, it tracked the laptop", "bad"))
        else:
            log.append((g["time"], f"Observer linked {g['old']} → {g['new']} as {who} — wrong, it was "
                        f"{run.devices[g['new_dev']]['id']}", "ok"))
    log.sort(key=lambda x: -x[0])
    icon = {"ok": "🟢", "bad": "🔴"}
    right.markdown("**Event log** (newest first)")
    right.markdown("<div style='height:%dpx;overflow-y:auto;font-size:0.85em;border:1px solid %s;border-radius:6px;padding:6px 10px'>%s</div>"
                   % (36 * (run.n + 1) + 4, GRID, "<br>".join(f"<b>{clock_str(t)}</b> {icon[k]} {txt}" for t, txt, k in log[:60])
                      or "<span style='color:#6b6a64'>Nothing yet…</span>"), unsafe_allow_html=True)
    right.caption("🟢 good for privacy / connection   🔴 bad for privacy / connection")

    # MAC timeline
    segs = run.segments_until(clock)
    names = [d["id"] for d in run.devices]
    fig = go.Figure(go.Bar(
        y=[names[d] for d, *_ in segs], x=[e - s for _, _, s, e in segs], base=[s for _, _, s, _ in segs],
        orientation="h", marker_color=[mac_color(m) for _, m, _, _ in segs], marker_line=dict(color="white", width=1),
        customdata=[m for _, m, _, _ in segs], hovertemplate="%{y}<br>MAC %{customdata}<extra></extra>", showlegend=False))
    lost = [g for g in guesses if not g["correct"]]
    fig.add_trace(go.Scatter(x=[g["change_time"] for g in lost], y=[names[g["new_dev"]] for g in lost], mode="markers",
                             marker=dict(symbol="circle", size=10, color=GOOD, line=dict(width=1.5, color="white")),
                             name="Observer lost track of this laptop here", hovertemplate="observer lost track<extra></extra>"))
    if run.scheme != "static" and run.duration / run.T <= 80:
        for k_ in range(1, int(run.duration // run.T) + 1):
            fig.add_vline(x=k_ * run.T, line=dict(color=GRID, width=1, dash="dot"))
    fig.add_vline(x=clock, line=dict(color=INK, width=2))
    fig.update_layout(title="MAC address timeline — each colour block is one address", barmode="overlay", showlegend=True,
                      xaxis=dict(title="Simulated time (s)", range=[0, run.duration]),
                      yaxis=dict(autorange="reversed", categoryorder="array", categoryarray=names))
    st.plotly_chart(style_fig(fig, 90 + 30 * run.n), width="stretch", key="timeline")

    c1, c2 = st.columns(2)
    edges, hist = run.traffic_history(clock)
    fig = go.Figure()
    for i in range(run.n):
        fig.add_trace(go.Scatter(x=edges, y=hist[i] if hist.size else [], stackgroup="one", name=names[i],
                                 mode="lines", line=dict(width=0.5)))
    fig.update_layout(title="Traffic on the network (last 3 minutes)", xaxis_title="Simulated time (s)",
                      yaxis_title="Frames per second", showlegend=False)
    c1.plotly_chart(style_fig(fig), width="stretch", key="traffic")

    fig = go.Figure()
    if run.scheme != "static" and guesses:
        ts, ys, cum = [], [], 0
        for g in guesses:
            cum += g["correct"]
            j = run.changes_judgeable(g["time"])
            if j:
                ts.append(g["time"]); ys.append(100 * cum / j)
        fig.add_trace(go.Scatter(x=ts, y=ys, mode="lines+markers", line=dict(color=SCHEME_COLOR[run.scheme], width=2),
                                 name="Changes linked so far"))
    fig.update_layout(title="How often the observer links old → new MAC", xaxis_title="Simulated time (s)",
                      yaxis_title="Changes linked (%)", yaxis_range=[0, 105], xaxis_range=[0, max(clock, 1)])
    c2.plotly_chart(style_fig(fig), width="stretch", key="accuracy")

    if run.gateway:
        st.markdown("**Router's expected-address table** — worked out in advance from each laptop's key")
        st.dataframe(pd.DataFrame(run.router_table(clock)), hide_index=True, width="stretch")
        st.caption("The router accepts the previous, current and next slot's address, so a laptop whose clock is a "
                   "little off still gets in. Anything else is rejected.")


# --- experiments ---------------------------------------------------------------------

def bar_fig(main: dict, key: str, title: str, ylabel: str, scale: float = 1.0, fmt: str = "{:.0f}") -> go.Figure:
    schemes = [s for s in SCHEMES if s in main and key in main[s]]
    vals = [main[s][key][0] * scale for s in schemes]
    errs = [main[s][key][1] * scale for s in schemes]
    fig = go.Figure(go.Bar(x=[LABELS[s] for s in schemes], y=vals, error_y=dict(array=errs, color=MUTED),
                           marker_color=[SCHEME_COLOR[s] for s in schemes], text=[fmt.format(v) for v in vals],
                           textposition="outside", cliponaxis=False))
    fig.update_layout(title=title, yaxis_title=ylabel)
    return style_fig(fig, 320)


def draw_experiments(ph: dict, main: dict, sweep: list, crowd: dict, over: list) -> None:
    if main:
        ph["acc"].plotly_chart(bar_fig(main, "linkage_accuracy", "MAC changes the observer linked",
                                       "Linked (%)", 100, "{:.0f}%"), width="stretch", key=f"acc-{next(_draw_id)}")
        ph["track"].plotly_chart(bar_fig(main, "mean_track_min", "How long it can follow one laptop",
                                         "Minutes"), width="stretch", key=f"track-{next(_draw_id)}")
        ph["reset"].plotly_chart(bar_fig(main, "sessions_reset_per_device_hour", "Connections broken",
                                         "Resets per laptop per hour", 1, "{:.1f}"), width="stretch", key=f"reset-{next(_draw_id)}")
        ph["down"].plotly_chart(bar_fig(main, "mean_downtime_s", "Time offline per change",
                                        "Seconds", 1, "{:.2f}"), width="stretch", key=f"down-{next(_draw_id)}")
        if any("extra_data_pct" in v for v in main.values()):
            ph["extra"].plotly_chart(bar_fig(main, "extra_data_pct", "Extra data sent (cost of padding)",
                                             "Extra data (%)", 1, "{:.0f}%"), width="stretch", key=f"extra-{next(_draw_id)}")
    if sweep:
        fig = go.Figure()
        x = [r["T"] / 60 for r in sweep]
        fig.add_trace(go.Scatter(x=x, y=[r["track"][0] for r in sweep], mode="lines+markers", name="Tracking time (min)",
                                 line=dict(color=BLUE, width=2)))
        fig.add_trace(go.Scatter(x=x, y=[r["changes_per_hour"] for r in sweep], mode="lines+markers", yaxis="y2",
                                 name="Changes per hour", line=dict(color="#eb6834", dash="dash")))
        fig.update_layout(title="Slot length trade-off (AMR with fixes)", xaxis_title="Slot length (minutes)",
                          yaxis_title="Tracking time (min)", yaxis2=dict(title="Changes per hour", overlaying="y", side="right"))
        ph["sweep"].plotly_chart(style_fig(fig), width="stretch", key=f"sweep-{next(_draw_id)}")
    if crowd and any(crowd.values()):
        fig = go.Figure()
        for s, rows in crowd.items():
            if rows:
                fig.add_trace(go.Scatter(x=[r["n"] for r in rows], y=[r["acc"][0] * 100 for r in rows], mode="lines+markers",
                                         name=LABELS[s], line=dict(color=SCHEME_COLOR[s], width=2)))
        fig.update_layout(title="More laptops = harder to track", xaxis_title="Laptops on the network",
                          yaxis_title="Changes linked (%)", yaxis_range=[0, 105], xaxis_type="log")
        ph["crowd"].plotly_chart(style_fig(fig), width="stretch", key=f"crowd-{next(_draw_id)}")
    if over:
        fig = go.Figure(go.Scatter(x=[r["n"] for r in over], y=[r["ms"] for r in over], mode="lines+markers",
                                   line=dict(color="#7c3aed", width=2), text=[f"{r['ms']:.1f} ms" for r in over],
                                   textposition="top left"))
        fig.update_layout(title="Router work per slot (measured on this PC)", xaxis_title="Laptops registered",
                          yaxis_title="Milliseconds", xaxis_type="log", yaxis_type="log")
        ph["over"].plotly_chart(style_fig(fig), width="stretch", key=f"over-{next(_draw_id)}")


def summarise(runs: list[dict]) -> dict:
    return {k: rx.avg(runs, k) for k in runs[0]}


def page_experiments() -> None:
    st.title("Experiments")
    st.caption("Runs the full comparison and draws each graph as results come in. When it finishes, the PNG graphs "
               "and results.md in the results folder are updated too.")
    c = st.columns(5)
    laptops = c[0].slider("Laptops", 5, 40, 20)
    hours = c[1].selectbox("Simulated time", [1, 2, 3], index=2, format_func=lambda h: f"{h} h")
    slot = c[2].select_slider("Address changes every", [2, 5, 10, 20, 30], value=10, format_func=lambda m: f"{m} min")
    runs = c[3].slider("Repeats per scheme", 1, 5, 3)
    c[4].write("")
    go_btn = c[4].button("▶ Run experiments live", type="primary", width="stretch")

    progress = st.empty()
    status = st.empty()
    r1 = st.columns(2); r2 = st.columns(3); r3 = st.columns(3)
    ph = {"acc": r1[0].empty(), "track": r1[1].empty(), "reset": r2[0].empty(), "down": r2[1].empty(), "extra": r2[2].empty(),
          "sweep": r3[0].empty(), "crowd": r3[1].empty(), "over": r3[2].empty()}
    table_ph = st.empty()

    if not go_btn:
        saved = RESULTS / "results.json"
        if saved.exists():
            d = json.loads(saved.read_text())
            status.caption("Showing the last saved results. Press **Run experiments live** to run them again.")
            draw_experiments(ph, d["main"], d["slot_sweep"], d["crowd"], d["overhead"])
        else:
            status.info("No saved results yet. Press **Run experiments live**.")
        return

    duration = hours * 3600
    seeds = list(range(runs))
    small = seeds[:max(1, min(2, runs))]
    slots = [120, 300, 600, 1200, 1800]
    sizes = [5, 10, 20, 40, 80]
    total = len(SCHEMES) * len(seeds) + len(slots) * len(small) + 2 * len(sizes) * len(small) + 4
    done = 0
    t0 = time.time()

    def tick(msg):
        nonlocal done
        done += 1
        progress.progress(done / total, text=f"{msg} · {done}/{total} runs · {time.time() - t0:.0f} s")

    main, raw = {}, {s: [] for s in SCHEMES}
    for seed in seeds:
        for s in SCHEMES:
            status.markdown(f"Running **{LABELS[s]}**, repeat {seed + 1}/{runs}…")
            raw[s].append(rx.run_once(s, n_devices=laptops, duration=duration, epoch_seconds=slot * 60, seed=seed))
            main[s] = summarise(raw[s])
            tick(f"{LABELS[s]} repeat {seed + 1}")
            draw_experiments(ph, main, [], {}, [])
            table_ph.dataframe(pd.DataFrame([{
                "Scheme": LABELS[s2], "Repeats": len(raw[s2]),
                "Changes linked": f"{main[s2]['linkage_accuracy'][0]:.1%}",
                "Tracking time": f"{main[s2]['mean_track_min'][0]:.1f} min",
                "Resets / laptop / h": f"{main[s2]['sessions_reset_per_device_hour'][0]:.2f}",
                "Downtime / change": f"{main[s2]['mean_downtime_s'][0]:.2f} s",
                "Frames lost / change": f"{main[s2]['frames_lost_per_change'][0]:.1f}",
                "Extra data": f"{main[s2]['extra_data_pct'][0]:.0f}%"} for s2 in main]),
                hide_index=True, width="stretch")

    sweep = []
    for T in slots:
        status.markdown(f"Slot length sweep: **{T // 60} min** slots…")
        rr = []
        for seed in small:
            rr.append(rx.run_once("amr", n_devices=laptops, duration=duration, epoch_seconds=T, seed=seed))
            tick(f"slot {T // 60} min")
        sweep.append({"T": T, "track": rx.avg(rr, "mean_track_min"), "acc": rx.avg(rr, "linkage_accuracy"),
                      "changes_per_hour": 3600 / T})
        draw_experiments(ph, main, sweep, {}, [])

    crowd = {"naive": [], "amr": [], "amr_padded": []}
    for s in crowd:
        for n in sizes:
            status.markdown(f"Crowd size: **{LABELS[s]}** with **{n}** laptops…")
            rr = []
            for seed in small:
                rr.append(rx.run_once(s, n_devices=n, duration=2 * 3600, epoch_seconds=slot * 60, seed=seed))
                tick(f"{n} laptops")
            crowd[s].append({"n": n, "acc": rx.avg(rr, "linkage_accuracy")})
            draw_experiments(ph, main, sweep, crowd, [])

    over = []
    for n in [10, 100, 1000, 5000]:
        status.markdown(f"Timing the router with **{n}** laptops…")
        over += rx.gateway_overhead((n,))
        tick(f"router {n}")
        draw_experiments(ph, main, sweep, crowd, over)

    rx.plots(main, sweep, crowd, over)
    rx.write_summary(main, sweep, crowd, over, seeds,
                     desc=f"{laptops} laptops, {hours} simulated hours, {slot}-minute slots.")
    progress.progress(1.0, text=f"Finished in {time.time() - t0:.0f} s")
    status.success("Done. The PNG graphs and results.md in the results folder have been updated "
                   "(see **Saved graphs**).")


# --- tests ---------------------------------------------------------------------------

TEST_INFO = {
    "test_same_inputs_same_mac": "Same key, laptop and slot always give the same MAC",
    "test_mac_changes_every_slot": "1000 slots give 1000 different MACs",
    "test_different_key_different_mac": "A different key gives a different MAC",
    "test_always_valid_local_unicast": "Every address is unicast and locally administered",
    "test_recognises_current_slot": "Router recognises the laptop's current address",
    "test_tolerates_one_slot_clock_drift": "Router accepts the previous / next slot (clock drift)",
    "test_rejects_old_and_unknown": "Router rejects old and made-up addresses",
    "test_rotation_logged": "Router logs each address change",
    "test_amr_never_drops_connections": "With AMR no connection is ever dropped",
    "test_amr_harder_to_track_than_random": "AMR is harder to track than random rotation",
    "test_random_guesses_never_get_in": "5,000 random MACs fired at the router: none get in",
    "test_old_addresses_rejected": "Addresses from 2+ slots ago are rejected",
    "test_brute_force_cracks_tiny_key_only": "Brute force cracks a tiny key, but 256-bit is out of reach",
    "test_padding_uses_three_sizes": "Padding leaves only 3 frame sizes and never shrinks a frame",
}
LINE = re.compile(r"^(test_\w+) \(([\w.]+)\)(?: \.\.\. (.*))?$")


def page_tests() -> None:
    st.title("Tests")
    st.caption("Runs the project's unit tests for real (python -m unittest) and shows each result as it finishes.")
    if not (st.button("▶ Run all tests", type="primary") or st.query_params.get("run") == "1"):
        st.dataframe(pd.DataFrame({"Test": list(TEST_INFO.values()), "Status": "not run yet"}),
                     hide_index=True, width="stretch")
        return
    rows = {name: {"Test": desc, "Status": "⏳ waiting", "Code name": name} for name, desc in TEST_INFO.items()}
    table = st.empty()
    summary = st.empty()
    raw = []
    proc = subprocess.Popen([sys.executable, "-u", "-m", "unittest", "discover", "-v", "-s", "tests"], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        raw.append(line.rstrip())
        m = LINE.match(line.strip())
        if m:
            name, _, result = m.groups()
            row = rows.setdefault(name, {"Test": name, "Code name": name})
            row["Status"] = {"ok": "✅ passed", "FAIL": "❌ failed", "ERROR": "💥 error"}.get(result, f"⏳ {result or 'running'}")
        table.dataframe(pd.DataFrame(rows.values()), hide_index=True, width="stretch")
    proc.wait()
    passed = sum(r["Status"].startswith("✅") for r in rows.values())
    (summary.success if proc.returncode == 0 else summary.error)(f"{passed} of {len(rows)} tests passed.")
    with st.expander("Raw test output"):
        st.code("\n".join(raw))


# --- how it works ----------------------------------------------------------------------

def page_how() -> None:
    st.title("How a new address is computed")
    st.caption("The algorithm is **HMAC-SHA256**, used the same way login authenticator apps make their 6-digit codes "
               "(TOTP, RFC 6238), except the output becomes a MAC address.")

    st.markdown("""
**The idea in one line:** the laptop and the router share a secret key. For every time slot both of them run
`HMAC-SHA256(key, laptop name | slot number)` and keep the first 6 bytes as the MAC. Same inputs → same MAC on both
sides, so the router always knows the next address. Without the key the output looks completely random.
""")

    if "calc_key" not in st.session_state:
        st.session_state.calc_key = new_key().hex()
    st.subheader("Try it")
    c = st.columns([3, 2, 1.4, 1.4])
    key_hex = c[0].text_input("Secret key (64 hex characters = 256 bits)", key="calc_key")
    device = c[1].text_input("Laptop name", "krishiv-laptop")
    T = c[2].select_slider("Slot length", [15, 30, 60, 300, 600, 1800], value=600, format_func=lambda s: f"{s // 60} min" if s >= 60 else f"{s} s")
    t = c[3].number_input("Time since start (s)", 0, 10**7, 1234)
    if st.button("🎲 New random key"):
        st.session_state.calc_key = new_key().hex()
        st.rerun()
    try:
        key = bytes.fromhex(key_hex.strip())
        assert len(key) > 0
    except Exception:
        st.error("The key must be hex (0-9, a-f).")
        return

    e = epoch_of(t, T)
    msg = f"{device}|{e}|0"
    digest = hmac.new(key, msg.encode(), hashlib.sha256).digest()
    first6 = digest[:6]
    b0 = first6[0]
    b0_new = (b0 & 0xFC) | 0x02
    mac = ":".join(f"{x:02x}" for x in bytes([b0_new]) + first6[1:])
    assert mac == derive_mac(key, device, e) and is_local_unicast(mac)

    def bits(v: int) -> str:
        s = f"{v:08b}"
        return (f"<span style='font-family:monospace;font-size:1.25em'>{s[:6]}"
                f"<span style='background:#fde68a;padding:0 2px'>{s[6]}</span>"
                f"<span style='background:#bfdbfe;padding:0 2px'>{s[7]}</span></span>")

    st.markdown(f"**Step 1 — which slot are we in?**  `slot = floor(time / slot length) = floor({t} / {T}) = {e}`")
    st.markdown("**Step 2 — build the message** (laptop name, slot number, and a 0 used only if two laptops ever collide)")
    st.code(msg)
    st.markdown("**Step 3 — HMAC-SHA256(key, message)** gives 32 bytes (256 bits). Shown in hex, first 6 bytes in bold:")
    hx = digest.hex()
    st.markdown(f"<div style='font-family:monospace;word-break:break-all;background:#f3f4f6;padding:8px;border-radius:6px'>"
                f"<b style='color:{BLUE}'>{hx[:12]}</b>{hx[12:]}</div>", unsafe_allow_html=True)
    st.markdown(f"**Step 4 — keep the first 6 bytes:** `{' '.join(f'{x:02x}' for x in first6)}`")
    st.markdown(
        f"**Step 5 — fix two bits of the first byte** so it is always a valid address<br>"
        f"before: {bits(b0)} (0x{b0:02x}) &nbsp;→&nbsp; after: {bits(b0_new)} (0x{b0_new:02x})<br>"
        f"<span style='background:#bfdbfe;padding:0 4px'>last bit</span> = 0 → <b>unicast</b> (one device, not a group) &nbsp; "
        f"<span style='background:#fde68a;padding:0 4px'>second-last bit</span> = 1 → <b>locally administered</b> "
        f"(set by software, can never clash with a real manufacturer address). In code: <code>(byte AND 0xFC) OR 0x02</code>",
        unsafe_allow_html=True)
    st.success(f"**MAC for slot {e}: `{mac}`**")

    st.markdown("**The next few slots for this laptop** — each one looks unrelated to the last:")
    st.dataframe(pd.DataFrame([{"Slot": k, "Time range": f"{k * T} – {(k + 1) * T} s", "MAC": derive_mac(key, device, k)}
                               for k in range(e, e + 6)]), hide_index=True, width="stretch")

    st.subheader("Why HMAC-SHA256?")
    st.markdown(r"""
* **SHA-256** is a hash function: it turns any input into 32 bytes that look random, and you can't go backwards.
* **HMAC** mixes a secret key into the hash in a safe way:
  `HMAC(K, m) = SHA256( (K ⊕ opad) ‖ SHA256( (K ⊕ ipad) ‖ m ) )`, where `ipad` and `opad` are fixed padding values.
  It is the standard keyed hash (RFC 2104). Just doing `SHA256(key ‖ message)` is unsafe (length-extension attacks).
* **Deterministic for the router, random for everyone else.** That is exactly what we need: a truly random source
  (or a lava lamp) would also be unpredictable to the router, so it couldn't prepare for the next address.
* **Cheap.** One HMAC per laptop per slot. The router's whole table for 1000 laptops takes milliseconds (see Experiments).
""")
    st.subheader("What the router does")
    st.markdown("""
1. At setup it stores each laptop's key and name.
2. Every slot it works out each laptop's address for the **previous, current and next** slot (so a laptop whose clock
   is a little off still gets in).
3. When a frame arrives, it looks the source MAC up in that table: found → same laptop, same IP, connection kept.
   Not found → rejected.
""")
    st.subheader("What the observer tries, and the two fixes")
    st.markdown("""
The observer only sees MAC, time, frame size and the frame sequence number. It links an old address to a new one using:
**timing** (one vanished, one appeared), the **sequence counter** carrying on, and **similar traffic** before and after.
It then picks the best overall matching (Hungarian algorithm).

* **AMR (basic)** still gets linked mostly because the sequence counter carries on (the leak found by Vanhoef et al.).
* **AMR (with fixes)** restarts the counter at a random value and stays quiet for a random 0–8 s after switching,
  so new addresses don't line up neatly with old ones.
* **AMR + padding** also rounds every frame up to one of 3 sizes (256, 768 or 1514 bytes). The observer can no
  longer tell a laptop by its frame sizes, only by how busy it is. The cost is extra data (shown in Experiments).

**Limits:** it's a simulation; reconnect times for random rotation are modelled. If an observer can read IP addresses,
an unchanged IP still links the MACs. The key has to be shared safely at setup.
""")


# --- security tests -----------------------------------------------------------------------

ATTACK_INFO = [
    ("guessing_attack", "Guess an address", "Fire random MAC addresses at a real router that holds the laptops' keys."),
    ("replay_attack", "Replay an old address", "Record a laptop's addresses from earlier slots and try them again now."),
    ("copy_attack", "Copy the current address", "Copy the address a laptop is using right now (spoofing)."),
    ("prediction_attack", "Predict the next address", "Study 2,000 past addresses and try to work out the next one."),
    ("brute_force_attack", "Crack the key", "Try every possible key until the MAC matches (real brute force, timed on this PC)."),
    ("randomness_test", "Randomness checks", "Statistical tests on 50,000 real AMR addresses vs true random ones."),
    ("near_key_attack", "Almost-right key", "Use a key that's off by just one bit."),
]
VERDICT = {"blocked": ("🛡 Blocked", GOOD), "warning": ("⚠ Works — by design", WARN), "broken": ("❌ Attack worked", BAD)}


def page_security() -> None:
    from amr import attacks

    st.title("Security tests — can an intruder get in?")
    st.caption("Real attacks, run on this PC against the real AMR code (the same address maths and router logic a real "
               "router would use), with fresh 256-bit keys and the real clock. Nothing here is simulated or pre-recorded.")
    st.info("Not covered: attacking a real Wi-Fi network or changing this laptop's hardware MAC — that needs a second "
            "device, admin rights and driver support.", icon="ℹ️")

    with st.expander("🔍 Can someone see my laptop's real MAC address right now?"):
        if st.button("Show this laptop's real MAC"):
            mac, fallback = attacks.real_mac_of_this_pc()
            if fallback:
                st.warning("Windows didn't give Python a hardware address, so this can't be shown.")
            else:
                st.markdown(f"Your laptop's hardware MAC is **`{mac}`**. Yes — anyone on the same Wi-Fi can already "
                            "see this; it's in every frame you send, and it never changes, so they can recognise your "
                            "laptop every time. That's the problem AMR solves: with AMR they'd see a different, "
                            "unrelated address every slot. Seeing an address doesn't give access to your laptop.")

    c = st.columns([1.4, 1.2, 1.4, 1.2])
    guesses = c[0].select_slider("Random guesses to fire", [50_000, 100_000, 200_000, 500_000, 1_000_000], value=200_000,
                                 format_func=lambda v: f"{v:,}")
    laptops = c[1].select_slider("Laptops on the router", [10, 50, 100, 200], value=50)
    big = c[2].checkbox("Also crack a 24-bit key (~30–60 s more)")
    c[3].write("")
    go_btn = c[3].button("▶ Run all attacks", type="primary", width="stretch") or st.query_params.get("run") == "1"

    score = st.empty()
    if not go_btn:
        st.dataframe(pd.DataFrame([{"#": i + 1, "Attack": t, "What the intruder does": d}
                                   for i, (_, t, d) in enumerate(ATTACK_INFO)]), hide_index=True, width="stretch")
        return

    kwargs = {"guessing_attack": {"attempts": guesses, "n_laptops": laptops},
              "brute_force_attack": {"key_bits": (16, 20, 24) if big else (16, 20)}}
    results, broken = [], 0
    for i, (fn, title, desc) in enumerate(ATTACK_INFO):
        box = st.container(border=True)
        box.markdown(f"**{i + 1}. {title}** — {desc}")
        bar = box.progress(0.0, text="starting…")
        t0 = time.perf_counter()
        r = getattr(attacks, fn)(progress=lambda f, txt: bar.progress(min(f, 1.0), text=txt), **kwargs.get(fn, {}))
        bar.progress(1.0, text=f"finished in {time.perf_counter() - t0:.1f} s")
        label, color = VERDICT[r["verdict"]]
        box.markdown(f"<span style='background:{color};color:#fff;padding:2px 10px;border-radius:10px;font-weight:600'>"
                     f"{label}</span> &nbsp; **{r['headline']}**", unsafe_allow_html=True)
        box.caption(r["details"])
        n = r["numbers"]
        if "rows" in n:
            box.dataframe(pd.DataFrame(n["rows"]), hide_index=True, width="stretch")
        if fn == "near_key_attack":
            fig = go.Figure(go.Bar(x=list(range(47)), y=n["hist"], marker_color=BLUE))
            fig.update_layout(title="Address bits changed by a 1-bit key change", xaxis_title="Bits changed (of 46)",
                              yaxis_title="Trials")
            box.plotly_chart(style_fig(fig, 280), width="stretch", key=f"near-{next(_draw_id)}")
        if fn == "guessing_attack":
            k = box.columns(3)
            k[0].metric("Guesses", f"{n['attempts']:,}")
            k[1].metric("Let in", n["accepted"])
            k[2].metric("Speed", f"{n['rate']:,.0f} /s")
        results.append(r)
        blocked = sum(x["verdict"] == "blocked" for x in results)
        by_design = sum(x["verdict"] == "warning" for x in results)
        broken = sum(x["verdict"] == "broken" for x in results)
        with score.container():
            k = st.columns(3)
            card(k[0], "Attacks blocked", f"{blocked} / {len(results)}", GOOD)
            card(k[1], "Work by design", f"{by_design}", WARN, "copying the current address" if by_design else "")
            card(k[2], "Attacks that broke AMR", f"{broken}", BAD if broken else GOOD)
    if broken:
        st.error("At least one attack succeeded — see above.")
    else:
        st.success("All attacks finished. Nothing broke AMR; copying the current address works by design (see test 3).")


# --- saved graphs ------------------------------------------------------------------------

CAPTIONS = {
    "1_linkage_accuracy.png": "How often the observer links old and new MAC",
    "2_tracking_time.png": "How long the observer can follow one device",
    "3_connection_resets.png": "Connections broken by MAC changes",
    "4_downtime.png": "Time offline at each change",
    "5_slot_length_tradeoff.png": "Slot length trade-off",
    "6_crowd_size.png": "Effect of the number of devices",
    "8_extra_data.png": "Extra data sent (cost of padding)",
    "7_gateway_overhead.png": "Router overhead (measured)",
}


def page_graphs() -> None:
    st.title("Saved graphs")
    st.caption("PNG graphs and capture files in the results folder. Re-run them from **Experiments**.")
    pngs = sorted(RESULTS.glob("*.png"))
    if not pngs:
        st.info("No graphs yet. Run the experiments first.")
    cols = st.columns(2)
    for i, p in enumerate(pngs):
        cols[i % 2].image(str(p), caption=CAPTIONS.get(p.name, p.name), width="stretch")
    md = RESULTS / "results.md"
    if md.exists():
        with st.expander("results.md"):
            st.markdown(md.read_text(encoding="utf-8"))
    st.subheader("Wireshark captures")
    st.caption("Open in Wireshark → Statistics → Endpoints → Ethernet to see the addresses change.")
    c = st.columns(3)
    for col, name in zip(c, ["capture_amr.pcap", "capture_random_rotation.pcap"]):
        f = RESULTS / name
        if f.exists():
            col.download_button(f"⬇ {name}", f.read_bytes(), file_name=name, width="stretch")
    if c[2].button("Rebuild captures", width="stretch"):
        with st.spinner("Building frames with Scapy…"):
            import make_pcap
            make_pcap.export("naive", "capture_random_rotation.pcap")
            make_pcap.export("amr", "capture_amr.pcap")
        st.success("Captures rebuilt.")


{"Live network": page_live, "Experiments": page_experiments, "Tests": page_tests, "Security tests": page_security,
 "How it works": page_how, "Saved graphs": page_graphs}[page]()
