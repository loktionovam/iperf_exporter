# Kind Operator Demo

This demo creates two kind clusters:

- `iperf-demo`: one control-plane node plus two workers
- `iperf-demo-remote`: one control-plane node plus one worker

It loads two local images,
`iperf_exporter:kind-demo` and `iperf_operator:kind-demo`, deploys the `kopf`
operator, installs Prometheus and Grafana, provisions the repository dashboards,
and applies example `MeasurementProfile`, `RemoteCluster`, and
`LinkMeasurement` resources.

The operator currently implements:

- `execution.mode: continuous`
- `execution.mode: probe`
- `execution.mode: periodicProbe`
- `networkMode: host`
- `networkMode: pod`
- `networkMode: service`
- bidirectional sessions via generated `MeasurementSession` resources
- cross-cluster `host` measurements through a `RemoteCluster` kubeconfig secret

Current cross-cluster limitation:

- only `networkMode: host` is supported when `source.cluster != destination.cluster`
- `pod` and `service` remain single-cluster-only because the demo assumes those
  networks are not routable between clusters

The demo applies all three execution styles:

- continuous measurements:
  - [measurement-tcp.yaml](./examples/measurement-tcp.yaml)
  - [measurement-udp.yaml](./examples/measurement-udp.yaml)
- periodic bounded probes:
  - [measurement-tcp-periodic.yaml](./examples/measurement-tcp-periodic.yaml)
  - [measurement-udp-periodic.yaml](./examples/measurement-udp-periodic.yaml)
- oneshot bounded probes with higher bandwidth:
  - [measurement-tcp-probe.yaml](./examples/measurement-tcp-probe.yaml)
  - [measurement-udp-probe.yaml](./examples/measurement-udp-probe.yaml)
- cross-cluster continuous host measurement:
  - [remote-cluster-b.yaml](./examples/remote-cluster-b.yaml)
  - [profile-tcp-quality-cross-cluster.yaml](./examples/profile-tcp-quality-cross-cluster.yaml)
  - [measurement-tcp-cross-cluster.yaml](./examples/measurement-tcp-cross-cluster.yaml)

Reusable scenario profiles:

- [tcp-quality-continuous](../../examples/profiles/tcp-quality-continuous.yaml)
- [udp-quality-continuous](../../examples/profiles/udp-quality-continuous.yaml)
- [tcp-quality-periodic](../../examples/profiles/tcp-quality-periodic.yaml)
- [udp-quality-periodic](../../examples/profiles/udp-quality-periodic.yaml)
- [tcp-throughput-probe](../../examples/profiles/tcp-throughput-probe.yaml)
- [udp-loss-probe](../../examples/profiles/udp-loss-probe.yaml)

The in-cluster monitoring stack is also installed automatically:

- Prometheus scrapes all generated server-side exporter services via Kubernetes SD
- Grafana provisions the existing repository dashboards from [grafana/dashboards](../../grafana/dashboards)

Endpoints:

- Grafana: `http://grafana.127.0.0.1.nip.io:8080`
- Prometheus: `http://prometheus.127.0.0.1.nip.io:8080`
`make demo-kind-up` installs `ingress-nginx` and exposes both UIs through the kind control-plane host port mappings.

Start:

```sh
make demo-kind-up
```

`make demo-kind-up` rebuilds and reloads both the exporter and operator demo
images into kind, refreshes the dashboard ConfigMaps, reinstalls ingress when
needed, and restarts the operator plus generated workloads so code and
dashboard changes are visible immediately on an existing cluster. The `make`
targets call the shell scripts, so old script-based usage still works
unchanged.

Verify again later:

```sh
make demo-kind-verify
```

`make demo-kind-verify` now runs a dedicated `pytest` suite for the live kind
demo instead of mixing shell logic with inline Python.

Run the same verification directly:

```sh
venv/bin/python -m pytest tests/kind/test_demo_cluster.py -q
```

Stop:

```sh
make demo-kind-down
```

Useful checks:

```sh
kubectl --context kind-iperf-demo -n iperf-exporter-demo get measurementprofiles
kubectl --context kind-iperf-demo -n iperf-exporter-demo get remoteclusters
kubectl --context kind-iperf-demo -n iperf-exporter-demo get linkmeasurements
kubectl --context kind-iperf-demo -n iperf-exporter-demo get measurementsessions
kubectl --context kind-iperf-demo -n iperf-exporter-demo get statefulset,deploy,svc
kubectl --context kind-iperf-demo-remote -n iperf-exporter-demo get statefulset,deploy,svc
```

Note:

- `host` mode uses `hostNetwork=true`
- if multiple server sessions land on the same node, their exporter metrics `bindPort` values must be unique
- the demo profiles already separate TCP and UDP bind ports for this reason
- the cross-cluster example uses a dedicated TCP profile with its own traffic and
  metrics ports so it does not collide with the single-cluster host sessions

Dashboards provisioned in Grafana:

- `iperf-exporter-overview`
- `iperf-exporter-tcp-quality`
- `iperf-exporter-udp-quality`

The TCP and UDP dashboards expose filters for `measurement_id`, `profile_ref`,
`execution_mode`, `direction`, source/destination cluster and node, plus
`network_mode`, so you can narrow the view to a specific CRD slice without
guessing from pod IPs alone.

Port-forward one service-mode session metrics endpoint:

```sh
kubectl --context kind-iperf-demo -n iperf-exporter-demo port-forward svc/tcp-demo-service-sourcetodestination-service 9868:9868
curl http://127.0.0.1:9868/metrics
```
