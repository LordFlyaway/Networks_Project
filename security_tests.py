"""
Runs the real attacks against the AMR code and prints the results.

    python security_tests.py
(The dashboard's "Security tests" page runs the same attacks with live progress.)
"""

import json
import os
import time

from amr import attacks

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
ICON = {"blocked": "BLOCKED ", "warning": "BY DESIGN", "broken": "BROKEN  "}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    results = []
    for test in attacks.TESTS:
        t0 = time.perf_counter()
        r = test()
        print(f"  [{ICON[r['verdict']]}] {r['name']:38s} {r['headline']}  ({time.perf_counter() - t0:.1f} s)")
        results.append(r)
    blocked = sum(r["verdict"] == "blocked" for r in results)
    print(f"\n  {blocked}/{len(results)} attacks blocked; copying the current address works by design "
          "(AMR is privacy, not a password).")
    with open(os.path.join(OUT, "security_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
