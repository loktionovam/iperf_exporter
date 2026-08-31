# Operator CRD Reference

This document describes the full field surface of the operator CRDs:

- `MeasurementProfile`
- `RemoteCluster`
- `LinkMeasurement`
- generated `MeasurementSession`

API group and version:

- `apiVersion: netperf.iperfexporter.io/v1`

Common metadata:

| Field | Required | Meaning |
| --- | --- | --- |
| `apiVersion` | yes | CRD API version. |
| `kind` | yes | One of `MeasurementProfile`, `RemoteCluster`, `LinkMeasurement`, `MeasurementSession`. |
| `metadata.name` | yes | Object name. Used by the operator to build child resource names and labels. |
| `metadata.namespace` | recommended | Namespace for the CR and generated child resources. |

## MeasurementProfile

`MeasurementProfile` is the reusable runtime template for exporter-based measurements.

### `MeasurementProfile.spec`

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `spec.protocol` | string | yes | none | Measurement protocol. Supported values: `tcp`, `udp`. |
| `spec.exporter` | object | no | exporter defaults | Exporter runtime configuration. The operator maps these fields directly to exporter environment variables. |

### `MeasurementProfile.spec.exporter`

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `port` | integer | `5001` | `iperf` server port used by the measurement traffic. |
| `bindPort` | integer | `9868` | HTTP metrics port exposed by the exporter process. Must be unique per node for `host` mode server sessions. |
| `interval` | integer | `1` | `iperf` report interval in seconds. |
| `len` | integer | `1280` | Client payload length passed to `iperf`. |
| `metricTTL` | integer | `3600` | How long inactive peers remain in exporter state before cleanup. |
| `debug` | boolean | `false` | Enables exporter debug logging. |
| `clientBandwidth` | string | `"1M"` | Client-side rate limit. For TCP it is applied only when it is a positive rate. |
| `clientDuration` | integer | `315360000` | Client runtime in seconds. Continuous profiles use a large value here. |
| `serverAdditionalParams` | string | `""` | Extra raw arguments appended to server-side `iperf`. Example: `--histograms=100u,20`. |
| `clientAdditionalParams` | string | `""` | Extra raw arguments appended to client-side `iperf`. Example: `--trip-times`. |
| `contextClientBandwidth` | string | `""` | Value shown in Grafana/metrics as the effective client bandwidth when it should differ from `clientBandwidth`. Falls back to `clientBandwidth` when empty. |
| `contextClientAdditionalParams` | string | `""` | Value shown in Grafana/metrics as effective client flags when they should differ from `clientAdditionalParams`. Falls back to `clientAdditionalParams` when empty. |
| `pathTraceTTL` | integer | `300` | Cache TTL in seconds for `tracepath` snapshots. |
| `pathTraceMaxHops` | integer | `16` | Maximum hop count passed to `tracepath`. |
| `pathTraceTimeout` | integer | `10` | Timeout in seconds for a single `tracepath` execution. |

### `MeasurementProfile.status`

| Field | Meaning |
| --- | --- |
| `status.phase` | Controller readiness for the profile. Current value is `Ready` once reconciled. |
| `status.protocol` | Resolved protocol from `spec.protocol`. |
| `status.reconciledAt` | RFC3339 timestamp of the last successful reconcile. |

## RemoteCluster

`RemoteCluster` describes how the primary operator reaches a second Kubernetes
cluster when a `LinkMeasurement` uses `source.cluster != destination.cluster`.

### `RemoteCluster.spec`

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `spec.namespace` | string | no | local `LinkMeasurement` namespace | Namespace in the remote cluster where generated child resources should be created. |
| `spec.kubeconfigSecretRef` | object | yes | none | Secret reference containing a kubeconfig for the remote cluster. |

### `RemoteCluster.spec.kubeconfigSecretRef`

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `name` | string | yes | Name of the Secret in the same namespace as the `RemoteCluster`. |
| `key` | string | no | Secret data key containing the kubeconfig. The demo uses both `kubeconfig` and `cluster-b.kubeconfig`. |

### `RemoteCluster.status`

| Field | Meaning |
| --- | --- |
| `status.phase` | Current connectivity status. Steady-state value is `Ready`. |
| `status.namespace` | Resolved remote namespace used by the operator. |
| `status.reconciledAt` | RFC3339 timestamp of the last successful connectivity check. |

## LinkMeasurement

`LinkMeasurement` is the user-facing intent resource. It describes what to test, between which endpoints, in which modes, and with which execution policy.

### `LinkMeasurement.spec`

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `profileRef` | string | yes | none | Name of the `MeasurementProfile` in the same namespace. |
| `source` | object | yes | none | Source endpoint. |
| `destination` | object | yes | none | Destination endpoint. |
| `directions` | array[string] | no | `["sourceToDestination", "destinationToSource"]` | Directions to materialize. The operator expands them into separate `MeasurementSession` objects. |
| `networkModes` | array[string] | no | `["pod"]` | Data path modes to create. Supported values: `host`, `pod`, `service`. |
| `execution` | object | no | `{"mode":"continuous"}` | How the client side is executed. |
| `runtime` | object | no | operator defaults | Image settings for generated exporter workloads. |

### `LinkMeasurement.spec.source` and `spec.destination`

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `cluster` | string | no | `"local"` | Logical cluster name. Same-cluster measurements may continue to use `local`, but cross-cluster measurements should use explicit names such as `cluster-a` and `cluster-b`. |
| `nodeName` | string | yes | none | Kubernetes node name on which the workload should run. |

### `LinkMeasurement.spec.execution`

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `mode` | string | no | `continuous` | Supported values: `continuous`, `probe`, `periodicProbe`. |
| `every` | string | for `periodicProbe` | `""` | Human-readable period like `30s`, `5m`, `1h`. Required only for `periodicProbe`. |
| `durationSeconds` | integer | no | profile `clientDuration` | Positive duration of a bounded run for `probe` and `periodicProbe`. |

### `LinkMeasurement.spec.runtime`

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `image` | string | no | operator default exporter image | Container image for generated server/client workloads. |
| `imagePullPolicy` | string | no | `IfNotPresent` | Pull policy used by generated workloads. |

### `LinkMeasurement.status`

| Field | Meaning |
| --- | --- |
| `status.phase` | Measurement reconciliation status. Current steady-state value is `Ready`. |
| `status.profileName` | Resolved referenced profile name. |
| `status.reconciledAt` | RFC3339 timestamp of the last successful reconcile. |
| `status.sessions[]` | High-level summary of generated sessions. Each item contains `name`, `sessionId`, `direction`, `networkMode`, `executionMode`, `srcNode`, `dstNode`, `protocol`, and `clientPeer`. |

Cross-cluster rule:

- when `source.cluster != destination.cluster`, only `networkModes: ["host"]`
  is currently valid
- `pod` and `service` measurements are supported only within one cluster

## MeasurementSession

`MeasurementSession` is generated by the operator. Users normally do not create it directly. One session means one direction plus one network mode for one `LinkMeasurement`.

### `MeasurementSession.spec`

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `measurementRef.name` | string | yes | Parent `LinkMeasurement` name. |
| `profileRef.name` | string | yes | Source `MeasurementProfile` name. |
| `protocol` | string | yes | Resolved protocol, `tcp` or `udp`. |
| `direction` | string | yes | `sourceToDestination` or `destinationToSource`. |
| `networkMode` | string | yes | `host`, `pod`, or `service`. |
| `source.cluster` | string | yes | Resolved source cluster name. |
| `source.nodeName` | string | yes | Resolved source node. |
| `source.nodeAddress` | string | yes | Resolved source node IP. |
| `destination.cluster` | string | yes | Resolved destination cluster name. |
| `destination.nodeName` | string | yes | Resolved destination node. |
| `destination.nodeAddress` | string | yes | Resolved destination node IP. |
| `execution.mode` | string | yes | Resolved execution mode. |
| `execution.every` | string | no | Original human-readable period for `periodicProbe`. |
| `execution.everySeconds` | integer | no | Operator-normalized interval in seconds for `periodicProbe`. |
| `execution.durationSeconds` | integer | no | Bounded probe duration in seconds. |
| `runtime.image` | string | yes | Resolved exporter image used by child workloads. |
| `runtime.imagePullPolicy` | string | yes | Resolved pull policy. |
| `exporter` | object | yes | Fully resolved exporter configuration copied from the profile. See `MeasurementProfile.spec.exporter`. |

### `MeasurementSession.metadata.labels`

The operator attaches topology labels normalized to Kubernetes' 63-character
limit with a hash suffix when truncation is needed. Prometheus context labels
are populated from the full values in `spec`, not from these normalized labels:

| Label | Meaning |
| --- | --- |
| `netperf.iperfexporter.io/measurement-id` | Parent `LinkMeasurement` name. |
| `netperf.iperfexporter.io/session-id` | Stable slugified session identifier. |
| `netperf.iperfexporter.io/direction` | Direction label. |
| `netperf.iperfexporter.io/network-mode` | Network mode label. |
| `netperf.iperfexporter.io/src-node` | Source node name. |
| `netperf.iperfexporter.io/dst-node` | Destination node name. |
| `netperf.iperfexporter.io/src-cluster` | Source cluster name. |
| `netperf.iperfexporter.io/dst-cluster` | Destination cluster name. |

### `MeasurementSession.status`

| Field | Meaning |
| --- | --- |
| `status.phase` | Current session phase: typically `Reconciling`, `Running`, `Completed`, or `Failed`. |
| `status.serverReady` | Whether the generated server workload is ready. |
| `status.clientReady` | Whether the generated client workload is ready. For `probe`, this becomes true while the job is active or completed successfully. |
| `status.clientActive` | Active job count for `probe`. Only present for `probe`. |
| `status.clientSucceeded` | Succeeded job count for `probe`. Only present for `probe`. |
| `status.clientFailed` | Failed job count for `probe`. Only present for `probe`. |
| `status.clientPeer` | Effective peer address that the client uses. This differs by network mode: node IP for `host`, headless pod DNS for `pod`, and service DNS for `service`. |
| `status.headlessServiceName` | Headless service created for the server pod. |
| `status.serviceName` | ClusterIP service created for `service` mode, otherwise empty. |
| `status.serverStatefulSetName` | Name of the generated server `StatefulSet`. |
| `status.clientDeploymentName` | Name of the generated client `Deployment` for `continuous` and `periodicProbe`. |
| `status.clientJobName` | Name of the generated client `Job` for `probe`. |

## Execution mode behavior

| Mode | Server lifecycle | Client lifecycle | Typical use |
| --- | --- | --- | --- |
| `continuous` | Long-lived `StatefulSet` | Long-lived `Deployment` | Always-on dashboards and low-friction steady-state monitoring. |
| `probe` | Long-lived `StatefulSet` | One-shot `Job` | Short bounded tests, usually at higher rates, to check burst throughput or induced loss. |
| `periodicProbe` | Long-lived `StatefulSet` | Long-lived `Deployment` that triggers bounded client runs on a period | Periodic sampling without constant traffic. |

Completed and failed probe Jobs are retained. The operator creates a new probe
only when the `MeasurementSession` generation changes or the current Job is
explicitly deleted.

## Operator metrics

The operator exposes Prometheus metrics on port `9869` by default. Set
`IPERF_OPERATOR_METRICS_PORT` to change the listening port. The Helm chart publishes
the endpoint through its operator Service. Enable `serviceMonitor.enabled`
to discover it with Prometheus Operator.

| Metric | Labels | Meaning |
| --- | --- | --- |
| `iperf_operator_reconciliations_total` | `kind`, `result` | Reconcile attempts grouped by custom-resource kind and `success` or `error`. |
| `iperf_operator_reconciliation_duration_seconds` | `kind` | Histogram of reconcile duration. |
| `iperf_operator_reconciliation_errors_total` | `kind`, `reason` | Reconcile failures grouped by bounded reason: `kubernetes_api`, `permanent`, or `unexpected`. |
| `iperf_operator_resources` | `kind`, `phase` | Number of known custom resources in their latest observed phase. |
| `iperf_operator_remote_cluster_up` | `cluster` | `1` after the latest successful RemoteCluster connectivity check, otherwise `0`. |
| `iperf_operator_remote_cleanup_failures_total` | `cluster` | Failed session cleanup attempts against a remote cluster. |
| `iperf_operator_finalizers_pending` | none | Session finalizers currently waiting for workload cleanup. |
| `iperf_operator_probe_runs_total` | `result` | Completed probe Jobs grouped by `success` or `failed`, deduplicated by Job UID. |
| `iperf_operator_probe_duration_seconds` | `result` | Histogram of probe Job runtime derived from Kubernetes start/completion timestamps. |
| `iperf_operator_start_time_seconds` | none | Unix timestamp when operator metrics were initialized. |
| `iperf_operator_build_info` | `version`, `python_version` | Constant `1` with build and Python runtime information. |
