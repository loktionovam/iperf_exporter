# Measurement Profile Catalog

These profiles are intended to be reusable starting points, not just kind-demo fixtures. They are named after the job they do:

- run `tcp-quality-continuous` to keep a long-lived TCP quality baseline
- run `udp-quality-continuous` to watch steady-state UDP loss and jitter
- run `tcp-quality-periodic` to sample TCP quality periodically with bounded runs
- run `udp-quality-periodic` to sample UDP quality periodically with bounded runs
- run `tcp-throughput-probe` to check short TCP burst throughput
- run `udp-loss-probe` to induce enough UDP load to expose loss and jitter

Reusable manifests live under [examples/profiles](../examples/profiles).

## Recommended profiles

| Profile | Protocol | Intended execution | Use it to test | Use it to verify | File |
| --- | --- | --- | --- | --- | --- |
| `tcp-quality-continuous` | TCP | `continuous` | Stable long-lived TCP flow with `--trip-times` and histograms | Routing, MSS/MTU, congestion control, read distribution, exporter health, dashboard wiring | [tcp-quality-continuous.yaml](../examples/profiles/tcp-quality-continuous.yaml) |
| `udp-quality-continuous` | UDP | `continuous` | Stable long-lived UDP flow at modest rate | Persistent loss, jitter, latency spread, path trace stability | [udp-quality-continuous.yaml](../examples/profiles/udp-quality-continuous.yaml) |
| `tcp-quality-periodic` | TCP | `periodicProbe` | Bounded TCP quality probe on a schedule | Repeated TCP latency/read-distribution snapshots without constant traffic | [tcp-quality-periodic.yaml](../examples/profiles/tcp-quality-periodic.yaml) |
| `udp-quality-periodic` | UDP | `periodicProbe` | Bounded UDP quality probe on a schedule | Repeated jitter/loss sampling with lower steady-state blast radius | [udp-quality-periodic.yaml](../examples/profiles/udp-quality-periodic.yaml) |
| `tcp-throughput-probe` | TCP | `probe` | Short higher-rate TCP burst | Peak path throughput, transient cwnd/RTT behavior, host-vs-pod-vs-service comparison | [tcp-throughput-probe.yaml](../examples/profiles/tcp-throughput-probe.yaml) |
| `udp-loss-probe` | UDP | `probe` | Short higher-rate UDP burst | Loss onset, jitter spikes, latency spread under stress | [udp-loss-probe.yaml](../examples/profiles/udp-loss-probe.yaml) |

## Selection guidance

- Start with `tcp-quality-continuous` or `udp-quality-continuous` when you are bringing up a new path and want persistent dashboards.
- Use `tcp-quality-periodic` or `udp-quality-periodic` when you want regular checks but do not want to keep the client generating traffic all the time.
- Use `tcp-throughput-probe` when the question is "how fast can this path go right now?"
- Use `udp-loss-probe` when the question is "at what point does this path start dropping or jittering?"

## Tuning guidance

- Increase `clientBandwidth` only after you confirm the low-rate baseline is healthy.
- Keep `bindPort` unique per node for `host`-mode server sessions.
- Keep `serverAdditionalParams` and `clientAdditionalParams` explicit so Grafana context tables describe the real test conditions.
- For very long-lived measurements, keep `metricTTL` comfortably above the expected scrape and reconnect gaps.
