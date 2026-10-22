"""
Live terminal demo for the review.

Shows one laptop and the router working out the same MAC for each slot,
the router recognising it straight away, and a fake MAC being rejected.

    python demo.py            (1 second per slot)
    python demo.py --fast     (no pauses)
"""

import os
import random
import sys
import time

from amr.gateway import Gateway
from amr.protocol import derive_mac, is_local_unicast, new_key, random_mac

SLOT = 600  # 10-minute slots

GREEN, RED, BOLD, DIM, END = "\033[92m", "\033[91m", "\033[1m", "\033[2m", "\033[0m"


def main(pause):
    key = new_key()
    laptop = "krishiv-laptop"
    router = Gateway(SLOT)
    router.register(laptop, key, "192.168.1.23")

    print(f"{BOLD}Authenticated MAC Rotation - demo{END}")
    print(f"Shared key (set up once): {DIM}{key.hex()[:32]}...{END}")
    print(f"Laptop IP stays at 192.168.1.23 the whole time\n")
    print(f"{'Slot':<6}{'Time':<10}{'Laptop computes':<22}{'Router expects':<22}Result")
    print("-" * 72)

    for slot in range(6):
        t = slot * SLOT + 5                       # 5 s into the slot
        laptop_mac = derive_mac(key, laptop, slot)
        router._refresh(t)
        expected = [m for m, d in router.expected.items() if d == laptop]
        ok = router.admit(laptop_mac, t) == laptop
        assert is_local_unicast(laptop_mac)
        mins = f"{t // 60:02d}:{t % 60:02d}"
        verdict = f"{GREEN}recognised, connection kept{END}" if ok else f"{RED}REJECTED{END}"
        print(f"{slot:<6}{mins:<10}{laptop_mac:<22}{expected[1]:<22}{verdict}")
        time.sleep(pause)

    fake = random_mac(random.Random())
    ok = router.admit(fake, 5) is not None
    print("-" * 72)
    print(f"Intruder tries a random MAC {fake}: "
          f"{RED + 'REJECTED' + END if not ok else 'accepted?!'}")
    print(f"\nTo an outsider the 6 addresses above look unrelated. "
          f"Only someone with the key can tell they are the same laptop.")


if __name__ == "__main__":
    os.system("")  # turns on colours in the Windows terminal
    main(0 if "--fast" in sys.argv else 1.0)
