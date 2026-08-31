# iperf-operator

Install the operator and four `netperf.iperfexporter.io/v1` CRDs:

```sh
helm install iperf-operator ./helm/charts/iperf-operator \
  --namespace iperf-measurements --create-namespace \
  --set localClusterName=cluster-a
```

The operator watches the release namespace with one replica. A MeasurementProfile
and LinkMeasurement start traffic; installing the chart alone does not.

Images default to the chart's appVersion. Configure image overrides, resources,
placement and optional ServiceMonitors in [values.yaml](values.yaml).
Prometheus and Grafana are not included.

See [installation](../../../docs/installation.md) for the first measurement and monitoring.

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| affinity | object | `{}` |  |
| exporter | object | `{"image":{"repository":"ghcr.io/loktionovam/iperf_exporter_server","tag":""}}` | Default image for generated workloads; LinkMeasurement spec.runtime.image can override it. |
| fullnameOverride | string | `""` |  |
| image | object | `{"pullPolicy":"IfNotPresent","repository":"ghcr.io/loktionovam/iperf_operator","tag":""}` | Operator image. An empty tag uses appVersion. |
| imagePullSecrets | list | `[]` | Credentials used to pull the operator image. |
| localClusterName | string | `"local"` | Logical cluster name used by LinkMeasurement endpoints. |
| nameOverride | string | `""` |  |
| nodeSelector | object | `{}` |  |
| resources.limits.cpu | string | `"500m"` |  |
| resources.limits.memory | string | `"256Mi"` |  |
| resources.requests.cpu | string | `"50m"` |  |
| resources.requests.memory | string | `"64Mi"` |  |
| serviceMonitor | object | `{"additionalLabels":{},"enabled":false,"interval":"15s"}` | Requires an existing Prometheus Operator installation. Monitors this namespace only. |
| tolerations | list | `[]` |  |
