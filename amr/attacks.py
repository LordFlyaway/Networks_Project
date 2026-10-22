"""
Real attacks against the real AMR code.

Nothing here is simulated: every test calls the same derive_mac() and Gateway
a router would run, with fresh random 256-bit keys from os.urandom and the
real wall-clock time to pick the current slot. Numbers (attempts, time,
attempts per second) are measured on this computer.

What these tests can't do: attack a real Wi-Fi network or change the laptop's
hardware MAC (that needs a second device, admin rights and driver support).

Each test takes a progress(fraction, text) callback and returns a dict:
    {"name", "verdict": "blocked" | "warning" | "broken", "headline", "details", "numbers"}
"""

import hashlib
import hmac
import math
import os
import random
import time
import uuid

import numpy as np
from scipy import stats

from .gateway import Gateway
from .protocol import derive_mac, epoch_of, random_mac

SLOT = 600
MAC_SPACE = 2 ** 46          # 48 bits minus the 2 fixed ones
UNIVERSE_YEARS = 1.38e10
_SYS = random.SystemRandom()


def _noop(*_):
    pass


def make_network(n_laptops=50, slot=SLOT):
    gw = Gateway(slot)
    laptops = []
    for i in range(n_laptops):
        key = os.urandom(32)
        name = f"laptop-{i:02d}"
        gw.register(name, key, f"192.168.1.{10 + i}")
        laptops.append((name, key))
    return gw, laptops


def _mac_bits(mac: str) -> np.ndarray:
    """The 46 free bits of a MAC (the two fixed bits are left out)."""
    v = int(mac.replace(":", ""), 16)
    bits = [(v >> (47 - i)) & 1 for i in range(48)]
    return np.array(bits[:6] + bits[8:], dtype=np.uint8)


def _years(seconds: float) -> float:
    return seconds / (365.25 * 24 * 3600)


def human_time(seconds: float) -> str:
    for unit, size in (("years", 365.25 * 86400), ("days", 86400), ("hours", 3600), ("minutes", 60)):
        if seconds >= size:
            v = seconds / size
            return f"{v:.1e} {unit}" if v >= 1e6 else f"{v:,.0f} {unit}" if v >= 10 else f"{v:.1f} {unit}"
    return f"{seconds:.1f} seconds"


# 1 -------------------------------------------------------------------------
def guessing_attack(attempts=200_000, n_laptops=50, progress=_noop):
    gw, laptops = make_network(n_laptops)
    now = time.time()
    accepted, batch = 0, 5000
    t0 = time.perf_counter()
    done = 0
    while done < attempts:
        for _ in range(min(batch, attempts - done)):
            if gw.admit(random_mac(_SYS), now) is not None:
                accepted += 1
        done = min(done + batch, attempts)
        progress(done / attempts, f"{done:,} random MACs tried · {accepted} let in")
    secs = time.perf_counter() - t0
    rate = attempts / secs
    entries = gw.table_size()
    p = entries / MAC_SPACE
    secs_to_hit = (1 / p) / rate
    wifi_rate = 1000                     # generous: frames per second over real Wi-Fi
    return {
        "name": "Guess an address",
        "verdict": "blocked" if accepted == 0 else "broken",
        "headline": f"{accepted} of {attempts:,} random MACs got in",
        "details": (f"The router held {entries} valid addresses ({n_laptops} laptops × 3 slots) out of "
                    f"{MAC_SPACE:,} possible, so each guess has a {p:.1e} chance. Honest maths: at this PC's full "
                    f"speed ({rate:,.0f} guesses/s, no network in the way) one lucky hit would take about "
                    f"{human_time(secs_to_hit)} of non-stop guessing. Over real Wi-Fi (~{wifi_rate:,} frames/s at best) "
                    f"it's about {human_time((1 / p) / wifi_rate)}, and the router would see millions of junk frames. "
                    f"Even a lucky hit only works until that slot ends — and it gains nothing that copying the "
                    f"visible address (test 3) doesn't, so real protection comes from WPA3 / 802.1X login."),
        "numbers": {"attempts": attempts, "accepted": accepted, "seconds": secs, "rate": rate,
                    "chance_per_guess": p, "seconds_to_one_hit_local": secs_to_hit,
                    "seconds_to_one_hit_wifi": (1 / p) / wifi_rate},
    }


# 2 -------------------------------------------------------------------------
def replay_attack(history=12, progress=_noop):
    gw, laptops = make_network(5)
    name, key = laptops[0]
    now = time.time()
    e = epoch_of(now, SLOT)
    rows = []
    for k, ep in enumerate(range(e - history, e)):
        mac = derive_mac(key, name, ep)
        ok = gw.admit(mac, now) is not None
        rows.append({"Slot": ep - e, "Recorded MAC": mac, "Router": "let in" if ok else "rejected"})
        progress((k + 1) / history, f"replaying slot {ep - e}")
    old_ok = sum(r["Router"] == "let in" for r in rows if r["Slot"] <= -2)
    prev_ok = rows[-1]["Router"] == "let in"
    return {
        "name": "Replay an old address",
        "verdict": "blocked" if old_ok == 0 else "broken",
        "headline": f"{old_ok} of {history - 1} older addresses got in",
        "details": ("Addresses recorded 2 or more slots ago are useless. The one from the slot just before "
                    f"({'accepted' if prev_ok else 'rejected'}) is still accepted on purpose so a laptop whose clock is a "
                    "little behind isn't locked out — that's a one-slot window, the same idea as login codes."),
        "numbers": {"rows": rows},
    }


# 3 -------------------------------------------------------------------------
def copy_attack(progress=_noop):
    gw, laptops = make_network(5)
    name, key = laptops[0]
    now = time.time()
    mac = derive_mac(key, name, epoch_of(now, SLOT))
    progress(0.5, "copying the address the laptop is using right now")
    who = gw.admit(mac, now)
    progress(1.0, "done")
    return {
        "name": "Copy the current address (spoofing)",
        "verdict": "warning" if who else "blocked",
        "headline": f"Copied MAC {mac} was {'let in as ' + who if who else 'rejected'}",
        "details": ("Honest result: anyone can see the address a laptop is using right now and copy it until the slot "
                    "ends, because a MAC address is not a password. AMR is a privacy feature (it stops tracking over "
                    "time); it should be used together with real network login such as WPA3 or 802.1X, which stops "
                    "an impostor even if it copies the address."),
        "numbers": {"mac": mac, "accepted_as": who},
    }


# 4 -------------------------------------------------------------------------
def prediction_attack(history=2000, progress=_noop):
    key, name = os.urandom(32), "laptop-00"
    e = epoch_of(time.time(), SLOT)
    macs = [derive_mac(key, name, ep) for ep in range(e - history, e + 1)]
    progress(0.3, f"recorded {history:,} past addresses")
    bits = np.array([_mac_bits(m) for m in macs])
    train, test = bits[: int(history * 0.75)], bits[int(history * 0.75):]

    # Strategy A: same as last time.  Strategy B: repeat the last change (XOR).
    vals = [int(m.replace(":", ""), 16) for m in macs]
    hits_repeat = sum(vals[i] == vals[i - 1] for i in range(1, len(vals)))
    hits_delta = sum(vals[i] == vals[i - 1] ^ (vals[i - 1] ^ vals[i - 2]) for i in range(2, len(vals)))
    progress(0.6, "trying pattern-based predictors")

    # Strategy C: learn, for each bit, what usually follows a 0 and what follows a 1.
    pred_next = np.zeros((2, bits.shape[1]), dtype=np.uint8)
    for b in (0, 1):
        mask = train[:-1] == b
        ones = (train[1:] * mask).sum(0)
        pred_next[b] = (ones > mask.sum(0) / 2).astype(np.uint8)
    guess = np.where(test[:-1] == 1, pred_next[1], pred_next[0])
    bit_acc = float((guess == test[1:]).mean())
    exact = int((guess == test[1:]).all(1).sum())
    progress(1.0, "done")
    blocked = hits_repeat == 0 and hits_delta == 0 and exact == 0 and abs(bit_acc - 0.5) < 0.03
    return {
        "name": "Predict the next address",
        "verdict": "blocked" if blocked else "broken",
        "headline": f"0 correct predictions; bit-by-bit accuracy {bit_acc:.1%} (a coin flip is 50%)"
        if blocked else f"Prediction worked: bit accuracy {bit_acc:.1%}",
        "details": (f"The attacker saw {history:,} of the laptop's past addresses and tried three predictors: "
                    f"'same as last time' ({hits_repeat} hits), 'repeat the last change' ({hits_delta} hits) and a "
                    f"learned per-bit pattern model ({exact} exact hits). Being right on {bit_acc:.1%} of bits is what "
                    "you get by guessing — past addresses say nothing about the next one without the key."),
        "numbers": {"history": history, "bit_accuracy": bit_acc, "exact_hits": exact,
                    "repeat_hits": hits_repeat, "delta_hits": hits_delta},
    }


# 5 -------------------------------------------------------------------------
def brute_force_attack(key_bits=(16, 20), progress=_noop):
    name = "laptop-00"
    e = epoch_of(time.time(), SLOT)
    msg = f"{name}|{e}|0".encode()
    rows = []
    total = sum(2 ** b for b in key_bits)
    done_before = 0
    rate = None
    for b in key_bits:
        secret = _SYS.randrange(2 ** b)
        key = secret.to_bytes(32, "big")
        target = derive_mac(key, name, e)
        tb = bytes.fromhex(target.replace(":", ""))
        t0 = time.perf_counter()
        found, tried = None, 0
        step = 1 << 14
        for start in range(0, 2 ** b, step):
            for k in range(start, min(start + step, 2 ** b)):
                d = hmac.digest(k.to_bytes(32, "big"), msg, "sha256")
                if d[1:6] == tb[1:6] and ((d[0] & 0xFC) | 0x02) == tb[0]:
                    found, tried = k, k + 1
                    break
            if found is not None:
                break
            progress((done_before + start + step) / total, f"{b}-bit key: {start + step:,} keys tried")
        secs = time.perf_counter() - t0
        rate = tried / secs if secs > 0 else float("nan")
        rows.append({"Key size": f"{b} bits", "Keys possible": f"{2 ** b:,}", "Keys tried": f"{tried:,}",
                     "Time": f"{secs:.2f} s", "Cracked": "yes" if found == secret else "no"})
        done_before += 2 ** b
    full_years = _years((2 ** 255) / rate)
    progress(1.0, "done")
    return {
        "name": "Crack the key (brute force)",
        "verdict": "blocked",
        "headline": f"Small keys fall in seconds; the real 256-bit key would take ~{full_years:.1e} years",
        "details": (f"The attacker knows the laptop name, the slot and the MAC, and tries every key. This PC managed "
                    f"{rate:,.0f} keys per second. The real key is 256 bits, so on average it needs 2^255 tries: "
                    f"about {full_years:.1e} years — roughly {full_years / UNIVERSE_YEARS:.1e} times the age of the "
                    "universe. That's why the small-key rows are only there to show the method works."),
        "numbers": {"rows": rows, "rate": rate, "years_256": full_years},
    }


# 6 -------------------------------------------------------------------------
def randomness_test(n=50_000, progress=_noop):
    key, name = os.urandom(32), "laptop-00"
    amr = np.array([_mac_bits(derive_mac(key, name, ep)) for ep in range(n)])
    progress(0.5, f"generated {n:,} AMR addresses")
    rnd = np.array([_mac_bits(random_mac(_SYS)) for _ in range(n)])
    progress(0.8, f"generated {n:,} truly random addresses to compare")

    def checks(bits):
        ones = int(bits.sum()); total = bits.size
        z = (ones - total / 2) / math.sqrt(total / 4)
        p_mono = 2 * stats.norm.sf(abs(z))
        col = bits.mean(0)
        z_pos = (col - 0.5) / math.sqrt(0.25 / len(bits))
        p_pos = float(2 * stats.norm.sf(np.abs(z_pos).max()) * bits.shape[1])   # Bonferroni over 46 positions
        ham = (bits[1:] != bits[:-1]).sum(1)
        p_ham = float(stats.ttest_1samp(ham, bits.shape[1] / 2).pvalue)
        return {"Share of 1-bits": f"{ones / total:.4f}", "p (balanced 0/1)": p_mono,
                "Most biased bit position": f"{abs(col - 0.5).max():.4f}", "p (every position fair)": min(1.0, p_pos),
                "Avg bits changed between consecutive": f"{ham.mean():.2f} of {bits.shape[1]}", "p (no link to previous)": p_ham}

    a, r = checks(amr), checks(rnd)
    progress(1.0, "done")
    ps = [a["p (balanced 0/1)"], a["p (every position fair)"], a["p (no link to previous)"]]
    rows = [{"Check": k, "AMR addresses": (f"{v:.3f}" if isinstance(v, float) else v),
             "True random": (f"{r[k]:.3f}" if isinstance(r[k], float) else r[k])} for k, v in a.items()]
    return {
        "name": "Randomness checks",
        "verdict": "blocked" if min(ps) > 0.001 else "warning",
        "headline": "AMR addresses are statistically indistinguishable from random" if min(ps) > 0.001
        else "One check came out unusual (re-run; ~1 in 1000 runs does this by chance)",
        "details": ("Each check gives a p-value: anything above 0.001 means 'no detectable pattern'. Half the bits are "
                    "1s, no bit position is biased, and on average half the bits flip from one address to the next — "
                    "exactly like true random. An outsider can't tell an AMR address from a random one."),
        "numbers": {"rows": rows, "min_p": min(ps)},
    }


# 7 -------------------------------------------------------------------------
def near_key_attack(trials=2000, progress=_noop):
    name = "laptop-00"
    e = epoch_of(time.time(), SLOT)
    dists, exact = [], 0
    for i in range(trials):
        key = bytearray(os.urandom(32))
        real = _mac_bits(derive_mac(bytes(key), name, e))
        bit = _SYS.randrange(256)
        key[bit // 8] ^= 1 << (bit % 8)
        fake = _mac_bits(derive_mac(bytes(key), name, e))
        d = int((real != fake).sum())
        dists.append(d)
        exact += d == 0
        if (i + 1) % 200 == 0:
            progress((i + 1) / trials, f"{i + 1:,} near-miss keys tried")
    mean = float(np.mean(dists))
    return {
        "name": "Almost-right key",
        "verdict": "blocked" if exact == 0 else "broken",
        "headline": f"A key off by just 1 bit changes {mean:.1f} of 46 address bits on average; {exact} matches",
        "details": ("Getting the key 'nearly right' is worth nothing: flipping a single one of its 256 bits scrambles "
                    "about half of the address (the 'avalanche effect' of SHA-256). There's no way to creep up on the "
                    "right key."),
        "numbers": {"trials": trials, "mean_bits_changed": mean, "exact": exact, "hist": np.bincount(dists, minlength=47).tolist()},
    }


TESTS = [guessing_attack, replay_attack, copy_attack, prediction_attack, brute_force_attack,
         randomness_test, near_key_attack]


def real_mac_of_this_pc():
    """This laptop's hardware MAC as Python sees it (uuid.getnode)."""
    node = uuid.getnode()
    random_fallback = bool((node >> 40) & 0x01)   # multicast bit set = Python couldn't read a real one
    return ":".join(f"{(node >> s) & 0xFF:02x}" for s in range(40, -1, -8)), random_fallback
