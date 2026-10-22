# Authenticated MAC Address Rotation (AMR)

Computer Networks project by Krishiv Rajkumar (24BDE0132) and Asher Mathew (24BDE0128).

A laptop changes its MAC address every few minutes while it stays connected.
The laptop and the router share a secret key and both compute the same new
address for each time slot, so the router always recognises the laptop and the
connection never drops. Anyone else on the network only sees addresses that
look random and unrelated.

## Run it

Easiest: double-click `run_all.bat`. It installs the libraries, runs the tests, the demo, the experiments and the Wireshark export in order, then opens the results folder.

Or run each step yourself:

```
pip install -r requirements.txt
python demo.py                    # live demo: laptop + router agree on each new MAC
python run_experiments.py         # all experiments -> results/ (about 1 minute)
python make_pcap.py               # Wireshark captures -> results/*.pcap
python -m unittest discover tests # 10 checks
```

## Dashboard (website)

Double-click `run_dashboard.bat`, or run `python -m streamlit run app/dashboard.py`. It opens at http://localhost:8501 with five pages:

* **Live network**: laptops change MAC in real time. Choose the scheme, number of laptops, how often the address changes and playback speed. Watch the router's decisions, the observer's guesses, a MAC timeline, traffic and accuracy charts. You can also inject an intruder.
* **Experiments**: runs the full comparison with every graph updating as results arrive, then saves the PNGs and results.md.
* **Tests**: runs the unit tests for real and ticks each one off as it passes.
* **Security tests**: real attacks against the real AMR code (not the simulation): guessing, replaying old addresses, copying the current one, predicting the next, brute-forcing the key, randomness checks and an almost-right key. Same attacks from the command line: `python security_tests.py`.
* **How it works**: explains HMAC-SHA256 and includes a calculator that shows every step of computing an address.
* **Saved graphs**: the PNGs, results.md and Wireshark capture downloads.

Styled like the TurboRUL dashboard (Streamlit + Plotly, blue accent).

## Files

| File | What it does |
|---|---|
| `amr/protocol.py` | Turns key + device ID + time slot into a MAC with HMAC-SHA256, then fixes the unicast / locally administered bits |
| `amr/gateway.py` | Router side: keeps the expected MACs for the previous, current and next slot, recognises the laptop, rejects unknown MACs |
| `amr/traffic.py` | Simple traffic model (idle, browsing, call, streaming) so devices behave realistically |
| `amr/simulation.py` | Simulates a network of laptops under five schemes: fixed MAC, random rotation, AMR basic, AMR with fixes, AMR + padding |
| `amr/observer.py` | The "attacker": watches frames and tries to link old and new MACs using timing, sequence numbers and traffic behaviour |
| `run_experiments.py` | Runs all experiments, saves graphs and `results/results.md` |
| `make_pcap.py` | Builds real Ethernet frames with Scapy and saves `.pcap` files for Wireshark |
| `demo.py` | Short terminal demo for the review |
| `amr/attacks.py`, `security_tests.py` | Real attacks against the AMR code and router |
| `app/dashboard.py` | Streamlit dashboard (live network, experiments, tests, explanation, graphs) |
| `amr/live.py` | Plays one simulated network forward in real time for the dashboard |
| `tests/test_amr.py` | Unit tests |

## Main results (20 laptops, 3 hours, 10-minute slots, 5 runs)

| Scheme | MAC changes linked by observer | Avg. time observer can follow a device | Connection resets / device / hour |
|---|---|---|---|
| Fixed MAC | 100% | 180 min (the whole time) | 0 |
| Random rotation | 99.6% | 168 min | 5.8 |
| AMR (basic) | 96.7% | 114 min | 0 |
| AMR (with fixes) | 48.9% | 18 min | 0 |
| AMR + padding | 36.8% | 15 min | 0 (costs 26% extra data) |

* Random rotation barely helps, and it breaks connections every time the address changes.
* AMR never breaks a connection. The router recognised every new address and rejected all 200 fake ones.
* AMR basic still gets linked because the frame sequence counter carries on across the change (the leak Vanhoef et al. found). AMR with fixes adds a short random quiet period and a fresh counter, which cuts tracking from 3 hours to about 18 minutes.
* The more devices on the network, the harder it is to track (75% linked with 5 devices, 23% with 80).
* AMR + padding rounds every frame up to one of 3 sizes so frame size stops being a clue: 36.8% linked instead of 48.9%, for 26% extra data. With 80 laptops on the network only 12% of changes get linked.
* Gateway cost is tiny: about 0.5 ms per slot for 10 devices, about 36 ms for 1000.

All graphs are in `results/`.

## Assumptions and limits

* It is a simulation, not real hardware. The observer only sees link-layer info (MAC, timing, frame size, sequence number), as on an encrypted Wi-Fi network.
* For random rotation, the router does not know the new MAC, so the laptop reconnects and gets a new IP from DHCP (1-3 s), which resets connections.
* The "with fixes" quiet period (0-8 s) is time the laptop deliberately stays silent. Data waits in a queue, so nothing is lost.
* If the observer can read IP addresses (for example on an unencrypted network), the unchanged IP still links the MACs. The key also has to be shared safely at setup.
