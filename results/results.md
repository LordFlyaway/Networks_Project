# Results

Averaged over 5 runs (seeds [0, 1, 2, 3, 4]). 20 laptops, 3 simulated hours, 10-minute slots.

| Scheme | MAC changes linked | Avg. tracking time | Connection resets / device / hour | Downtime per change | Frames lost per change | Extra data |
|---|---|---|---|---|---|---|
| Fixed MAC | 100.0% | 180.0 min | 0.00 | 0.00 s | 0.0 | 0% |
| Random rotation | 99.6% | 168.3 min | 5.83 | 2.02 s | 13.0 | 0% |
| AMR (basic) | 96.7% | 114.0 min | 0.00 | 0.05 s | 0.0 | 0% |
| AMR (with fixes) | 48.9% | 18.2 min | 0.00 | 4.06 s | 0.0 | 0% |
| AMR + padding | 36.8% | 14.9 min | 0.00 | 4.06 s | 0.0 | 26% |

Gateway check (AMR): 0 unrecognised AMR addresses, 200/200 random intruder MACs rejected.

## Slot length (AMR with fixes)

| Slot | Tracking time | Linked | Changes/hour |
|---|---|---|---|
| 2 min | 3.9 min | 50.4% | 30 |
| 5 min | 9.3 min | 48.8% | 12 |
| 10 min | 17.2 min | 46.0% | 6 |
| 20 min | 31.9 min | 44.8% | 3 |
| 30 min | 43.7 min | 42.8% | 2 |

## Number of devices

| Devices | Random rotation linked | AMR (with fixes) linked | AMR + padding linked |
|---|---|---|---|
| 5 | 100.0% | 75.7% | 66.4% |
| 10 | 100.0% | 63.3% | 51.8% |
| 20 | 99.4% | 46.5% | 35.2% |
| 40 | 99.6% | 32.6% | 22.3% |
| 80 | 99.3% | 23.0% | 12.3% |

## Gateway overhead (measured on this machine)

| Devices | Time per slot | Table entries |
|---|---|---|
| 10 | 0.23 ms | 30 |
| 100 | 2.10 ms | 300 |
| 1000 | 24.71 ms | 3000 |
| 5000 | 104.75 ms | 15000 |
