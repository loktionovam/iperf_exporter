# Installation

Choose the operator to manage measurements between Kubernetes nodes and
clusters. Use the standalone exporter when you already manage the iperf clients.
Both use **iperf2**; iperf3 clients are not compatible.

## Kubernetes operator

You need Helm, `kubectl`, a Kubernetes cluster with Linux nodes, and permission
to install CRDs and RBAC. The operator runs one replica and watches the namespace
where it is installed. It does not install Prometheus/Grafana or start test traffic.

```sh
helm repo add iperf-exporter https://raw.githubusercontent.com/loktionovam/iperf_exporter/gh-pages/
helm repo update
helm upgrade --install iperf-operator iperf-exporter/iperf-operator \
  --version 4.0.0 \
  --namespace iperf-measurements --create-namespace \
  --set localClusterName=cluster-a \
  --wait
```

Create a `MeasurementProfile` and `LinkMeasurement` in that namespace using
the [first-measurement example](../README.md#2-choose-a-profile-and-two-nodes).
The operator creates a `MeasurementSession` for each direction/network-mode
combination, and deploys the server and client on the chosen nodes.

```sh
kubectl -n iperf-measurements get measurementprofiles,linkmeasurements,measurementsessions
```

A session normally reaches `Running`; a successful one-shot probe reaches
`Completed`. Delete its `LinkMeasurement` to stop traffic and clean up the
workloads. Keep the operator and remote access available until cleanup finishes.

The [chart reference](../helm/charts/iperf-operator/README.md) lists image,
resource, placement and monitoring settings. Execution modes and their lifecycle
are described in the [CRD reference](operator-crds.md#execution-mode-behavior).

### Network requirements

- Allow the profile's iperf port between client and server, and its metrics port
  from Prometheus. Defaults are `5001` and `9868` respectively.
- `host` measurements use host networking and need unique server/metrics ports
  for co-located sessions. Namespace security policy must permit host networking.
- `pod` and `service` measurements are supported within one cluster.
- Synchronize node clocks before interpreting one-way `--trip-times` latency.
  Socket metrics describe the server; tracepath observes the server-to-client route.

### Remote cluster

Cross-cluster measurements support `networkModes: [host]`. Both clusters' node
addresses must be routable, and the operator must reach the remote Kubernetes API.
The remote namespace needs RBAC and workloads, not another operator or CRDs.

Apply the [remote access example](../examples/remote-cluster) using the remote
context. Its default namespace is `iperf-measurements`; adjust the Kustomization
namespace and ServiceAccount binding if you use another namespace.

```sh
kubectl --context REMOTE_CONTEXT apply -k examples/remote-cluster
```

Create a kubeconfig for that remote ServiceAccount with the remote API address,
CA certificate and credentials. Mounting your administrator kubeconfig is not
necessary. Use credentials whose validity covers the measurement and cleanup
period, and rotate them when required. Store the file locally as
`cluster-b.kubeconfig`, then create the Secret in the operator's namespace:

```sh
kubectl --context LOCAL_CONTEXT -n iperf-measurements create secret generic cluster-b-kubeconfig \
  --from-file=kubeconfig=cluster-b.kubeconfig
```

Register the remote cluster in the same namespace:

```yaml
apiVersion: netperf.iperfexporter.io/v1
kind: RemoteCluster
metadata:
  name: cluster-b
  namespace: iperf-measurements
spec:
  namespace: iperf-measurements
  kubeconfigSecretRef:
    name: cluster-b-kubeconfig
    key: kubeconfig
```

In a `LinkMeasurement`, set `source.cluster: cluster-a`,
`destination.cluster: cluster-b`, the actual node names, and
`networkModes: [host]`. Use `directions` to select one or both directions.
See the [CRD reference](operator-crds.md#remotecluster) for the full fields.

## Prometheus and Grafana

### With Prometheus Operator

Enable discovery when installing the operator chart:

```sh
helm upgrade --install iperf-operator iperf-exporter/iperf-operator \
  --version 4.0.0 \
  --namespace iperf-measurements --create-namespace \
  --set localClusterName=cluster-a \
  --set serviceMonitor.enabled=true \
  --set serviceMonitor.additionalLabels.release=prometheus \
  --wait
```

Replace `release=prometheus` with labels matching your Prometheus
`serviceMonitorSelector`; its namespace selector must include
`iperf-measurements`. Prometheus Operator and its CRDs must already be installed.
The chart creates monitors for the operator and local measurement servers,
scraping only the `metrics` port to avoid duplicate series.

### With plain Prometheus or a remote cluster

The [scrape configuration example](../examples/prometheus/scrape-configs.yaml)
contains jobs for operator-managed and standalone exporters, the operator and
remote exporters. Copy the
jobs you need into your Prometheus configuration and adjust namespaces.
Local Kubernetes discovery needs read access to Services, Endpoints and Pods.

For the remote job, mount a remote kubeconfig at
`/etc/prometheus/remote/cluster-b.kubeconfig`; a separate read-only discovery
identity is sufficient. Prometheus must reach the remote Kubernetes API and
exporter node metrics ports. A local ServiceMonitor does not discover another
cluster automatically.

Import the [three dashboards](dashboards.md) into your existing Grafana and select
the Prometheus datasource. The local demos provision the datasource and dashboards
automatically.

## Standalone exporter

### Helm

The standalone chart installs an exporter/server by default. Add a client to
start generating traffic, and select the same protocol for both:

```sh
helm upgrade --install iperf-server iperf-exporter/iperf-exporter-server \
  --version 4.0.0 \
  --namespace iperf-measurements --create-namespace \
  --set server.config.proto=tcp \
  --set client.enabled=true \
  --set client.config.proto=tcp \
  --wait
```

Use server/client placement settings to select different nodes. The optional
client supports Deployment or DaemonSet; `client.peer` can target an external
iperf2 server. Enable `serviceMonitor.enabled` if you use Prometheus Operator.
See the [standalone chart reference](../helm/charts/iperf-exporter-server/README.md).

### Docker

This example creates a TCP server and a bounded client test on one Docker
network. Only the Prometheus endpoint is published on the host:

```sh
docker network create iperf-net
docker run -d --name iperf-server --network iperf-net \
  -p 127.0.0.1:9868:9868 \
  -e IPERF_EXPORTER_PROTO=tcp \
  ghcr.io/loktionovam/iperf_exporter_server:v4.0.0
docker run --rm --network iperf-net \
  -e IPERF_EXPORTER_MODE=client \
  -e IPERF_EXPORTER_PROTO=tcp \
  -e IPERF_EXPORTER_CLIENT_PEER=iperf-server \
  -e IPERF_EXPORTER_CLIENT_EXECUTION_MODE=probe \
  -e IPERF_EXPORTER_CLIENT_DURATION=30 \
  ghcr.io/loktionovam/iperf_exporter_server:v4.0.0
curl http://localhost:9868/metrics
```

For external clients, publish port `5001/tcp` (or `5001/udp` for UDP) and allow it
through the firewall. Run the image with `--help` to see runtime options; the
[metrics reference](metrics.md) explains the output.

## Complete local demos

- [kind](../demo/kind/README.md): two clusters, the operator, sample measurements,
  Prometheus and Grafana. Run `make demo-kind-up` from a checkout.
- [Docker Compose](../demo/docker-compose/README.md): TCP/UDP clients and servers,
  Prometheus and Grafana without Kubernetes. Run `make demo-compose-up`.
