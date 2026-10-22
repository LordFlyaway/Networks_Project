"""
The router / gateway side of AMR.

It keeps a small table of the MAC addresses it expects right now. Because it
holds each device's key, it can work out every device's address for the
previous, current and next slot ahead of time (the +/-1 slot covers clocks
that are slightly out of sync). When a frame arrives it just looks the source
MAC up in that table.
"""

from .protocol import derive_mac, epoch_of, EPOCH_SECONDS


class Gateway:
    def __init__(self, epoch_seconds: float = EPOCH_SECONDS):
        self.epoch_seconds = epoch_seconds
        self.registry = {}        # device_id -> key            (set up once)
        self.ip_of = {}           # device_id -> IP address     (stays the same)
        self.current_mac = {}     # device_id -> MAC it is using now
        self.expected = {}        # MAC -> device_id for epochs e-1, e, e+1
        self.table_epoch = None
        self.rotations = []       # (time, device_id, old_mac, new_mac)
        self.rejected = 0
        self.collisions = 0

    def register(self, device_id: str, key: bytes, ip: str):
        self.registry[device_id] = key
        self.ip_of[device_id] = ip
        self.table_epoch = None   # force a rebuild

    def _refresh(self, t: float):
        e = epoch_of(t, self.epoch_seconds)
        if e == self.table_epoch:
            return
        table = {}
        for dev, key in self.registry.items():
            for ep in (e - 1, e, e + 1):
                mac = derive_mac(key, dev, ep)
                if mac in table and table[mac] != dev:
                    self.collisions += 1   # ~1 in 70 trillion; just logged
                table[mac] = dev
        self.expected = table
        self.table_epoch = e

    def admit(self, mac: str, t: float):
        """Return the device a frame belongs to, or None if the MAC is unknown."""
        self._refresh(t)
        dev = self.expected.get(mac)
        if dev is None:
            self.rejected += 1
            return None
        old = self.current_mac.get(dev)
        if old != mac:
            # The binding was already prepared: same device, same IP, new MAC.
            # No DHCP or ARP lookup is needed, so the connection carries on.
            if old is not None:
                self.rotations.append((t, dev, old, mac))
            self.current_mac[dev] = mac
        return dev

    def table_size(self) -> int:
        return len(self.expected)
