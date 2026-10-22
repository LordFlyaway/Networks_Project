"""Basic checks.  Run with:  python -m unittest discover tests"""

import random
import unittest

from amr.gateway import Gateway
from amr.observer import link, score
from amr.protocol import derive_mac, is_local_unicast, new_key, random_mac
from amr.simulation import simulate


class ProtocolTests(unittest.TestCase):
    def test_same_inputs_same_mac(self):
        key = new_key()
        self.assertEqual(derive_mac(key, "a", 5), derive_mac(key, "a", 5))

    def test_mac_changes_every_slot(self):
        key = new_key()
        macs = {derive_mac(key, "a", e) for e in range(1000)}
        self.assertEqual(len(macs), 1000)

    def test_different_key_different_mac(self):
        self.assertNotEqual(derive_mac(new_key(), "a", 1), derive_mac(new_key(), "a", 1))

    def test_always_valid_local_unicast(self):
        key = new_key()
        for e in range(2000):
            self.assertTrue(is_local_unicast(derive_mac(key, "a", e)))
        rng = random.Random(0)
        for _ in range(2000):
            self.assertTrue(is_local_unicast(random_mac(rng)))


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.key = new_key()
        self.gw = Gateway(600)
        self.gw.register("laptop", self.key, "192.168.1.5")

    def test_recognises_current_slot(self):
        self.assertEqual(self.gw.admit(derive_mac(self.key, "laptop", 3), 3 * 600 + 10), "laptop")

    def test_tolerates_one_slot_clock_drift(self):
        t = 3 * 600 + 10
        self.assertEqual(self.gw.admit(derive_mac(self.key, "laptop", 2), t), "laptop")
        self.assertEqual(self.gw.admit(derive_mac(self.key, "laptop", 4), t), "laptop")

    def test_rejects_old_and_unknown(self):
        t = 3 * 600 + 10
        self.assertIsNone(self.gw.admit(derive_mac(self.key, "laptop", 0), t))
        self.assertIsNone(self.gw.admit(random_mac(random.Random(1)), t))

    def test_rotation_logged(self):
        self.gw.admit(derive_mac(self.key, "laptop", 0), 10)
        self.gw.admit(derive_mac(self.key, "laptop", 1), 610)
        self.assertEqual(len(self.gw.rotations), 1)


class SimulationTests(unittest.TestCase):
    def test_amr_never_drops_connections(self):
        r = simulate("amr", n_devices=5, duration=3600, seed=3)
        self.assertEqual(r.gateway_failures, 0)
        self.assertTrue(all(x.session_kept for x in r.rotations))

    def test_amr_harder_to_track_than_random(self):
        naive = simulate("naive", n_devices=20, duration=3600, seed=4)
        amr = simulate("amr", n_devices=20, duration=3600, seed=4)
        a = score(naive, link(naive))["linkage_accuracy"]
        b = score(amr, link(amr))["linkage_accuracy"]
        self.assertLess(b, a)


class PaddingTests(unittest.TestCase):
    def test_padding_uses_three_sizes(self):
        plain = simulate("amr", n_devices=3, duration=900, seed=5)
        padded = simulate("amr_padded", n_devices=3, duration=900, seed=5)
        self.assertLessEqual(set(padded.frames["size"].astype(int)), {256, 768, 1514})
        self.assertGreaterEqual(padded.frames["size"].sum(), plain.frames["size"].sum())
        self.assertGreater(padded.extra["padding_overhead"], 0)


class SecurityTests(unittest.TestCase):
    def test_random_guesses_never_get_in(self):
        from amr.attacks import guessing_attack
        self.assertEqual(guessing_attack(attempts=5000, n_laptops=20)["numbers"]["accepted"], 0)

    def test_old_addresses_rejected(self):
        from amr.attacks import replay_attack
        self.assertEqual(replay_attack()["verdict"], "blocked")

    def test_brute_force_cracks_tiny_key_only(self):
        from amr.attacks import brute_force_attack
        r = brute_force_attack(key_bits=(12,))
        self.assertEqual(r["numbers"]["rows"][0]["Cracked"], "yes")
        self.assertGreater(r["numbers"]["years_256"], 1e30)


if __name__ == "__main__":
    unittest.main()
