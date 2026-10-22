"""
Core of Authenticated MAC Rotation (AMR).

The laptop and the router share a secret key. For every time slot ("epoch")
both of them compute the same MAC address from that key, so the router always
knows the laptop's next address, while everyone else just sees random values.
"""

import hashlib
import hmac
import os

EPOCH_SECONDS = 600  # default slot length: 10 minutes


def new_key() -> bytes:
    """A fresh 256-bit secret key, shared once between laptop and router."""
    return os.urandom(32)


def epoch_of(t: float, epoch_seconds: float = EPOCH_SECONDS, t0: float = 0.0) -> int:
    """Which time slot a timestamp falls in:  e = floor((t - t0) / T)."""
    return int((t - t0) // epoch_seconds)


def derive_mac(key: bytes, device_id: str, epoch: int, attempt: int = 0) -> str:
    """
    MAC for one epoch = first 6 bytes of HMAC-SHA256(key, device_id || epoch).

    Two bits of the first byte are then fixed so the result is always a valid
    address:
      * bit 0 (I/G) = 0  -> unicast (a single device, not a group)
      * bit 1 (U/L) = 1  -> locally administered (can never clash with a real
                            manufacturer address)
    `attempt` lets both sides skip to another value if two devices ever collide.
    """
    msg = f"{device_id}|{epoch}|{attempt}".encode()
    digest = hmac.new(key, msg, hashlib.sha256).digest()
    octets = bytearray(digest[:6])
    octets[0] = (octets[0] & 0xFC) | 0x02
    return ":".join(f"{b:02x}" for b in octets)


def is_local_unicast(mac: str) -> bool:
    first = int(mac.split(":")[0], 16)
    return (first & 0x01) == 0 and (first & 0x02) == 0x02


def random_mac(rng) -> str:
    """What today's OS-style randomisation does: a fresh random local MAC, no key."""
    octets = bytearray(rng.getrandbits(8) for _ in range(6))
    octets[0] = (octets[0] & 0xFC) | 0x02
    return ":".join(f"{b:02x}" for b in octets)
