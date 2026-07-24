# iperf-exporter-server

![Version: 3.0.0](https://img.shields.io/badge/Version-3.0.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: v3.0.0](https://img.shields.io/badge/AppVersion-v3.0.0-informational?style=flat-square)

IPerf prometheus metrics exporter with optional client workload

## What Changed

- `server` and `client` are configured independently.
- Each component has its own `nodeSelector`, `affinity`, `tolerations`, `resources`, `podAnnotations` and `podLabels`.
- `client.controller` can be either `DaemonSet` or `Deployment`.
- TCP and UDP are supported through `server.config.proto` and `client.config.proto`.
- The optional client can target the in-release server automatically or any external peer via `client.peer`.

## Example

Deploy the server on infra nodes and the client on worker nodes:

```yaml
server:
  enabled: true
  config:
    proto: tcp
    additionalParams: "--histograms=100u,20"
  nodeSelector:
    node-role.kubernetes.io/infra: "true"

client:
  enabled: true
  controller: DaemonSet
  config:
    proto: tcp
    bandwidth: 1M
    additionalParams: "--trip-times"
  nodeSelector:
    node-role.kubernetes.io/worker: "true"
```

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| client | object | `{"affinity":{},"config":{"additionalParams":"","bandwidth":"1M","port":5001,"proto":"udp"},"controller":"DaemonSet","enabled":false,"nodeSelector":{},"peer":"","podAnnotations":{},"podLabels":{},"replicaCount":1,"resources":{"limits":{"cpu":"100m","memory":"64Mi"},"requests":{"cpu":"100m","memory":"64Mi"}},"tolerations":[]}` | Optional client workload configuration. |
| client.affinity | object | `{}` | Affinity rules for the client workload. |
| client.config | object | `{"additionalParams":"","bandwidth":"1M","port":5001,"proto":"udp"}` | Environment-level client settings passed to the exporter. |
| client.config.additionalParams | string | `""` | Extra iperf client flags appended to the client command, for example `--trip-times`. |
| client.config.bandwidth | string | `"1M"` | Client bandwidth passed to iperf. For TCP, positive values enable rate limiting. |
| client.config.port | int | `5001` | Destination port used by the iperf client. |
| client.config.proto | string | `"udp"` | Protocol used by the iperf client (`udp` or `tcp`). |
| client.controller | string | `"DaemonSet"` | Controller type for the client workload (`DaemonSet` or `Deployment`). |
| client.enabled | bool | `false` | Deploy the client workload. |
| client.nodeSelector | object | `{}` | Node selector for the client workload. |
| client.peer | string | `""` | Explicit iperf peer hostname or IP. When empty, the chart targets the in-release server service. |
| client.podAnnotations | object | `{}` | Extra annotations for the client pod template. |
| client.podLabels | object | `{}` | Extra labels for the client pod template. |
| client.replicaCount | int | `1` | Replica count when `client.controller=Deployment`. |
| client.resources | object | `{"limits":{"cpu":"100m","memory":"64Mi"},"requests":{"cpu":"100m","memory":"64Mi"}}` | CPU and memory resources for the client container. |
| client.resources.limits.cpu | string | `"100m"` | CPU limit for the client container. |
| client.resources.limits.memory | string | `"64Mi"` | Memory limit for the client container. |
| client.resources.requests.cpu | string | `"100m"` | CPU request for the client container. |
| client.resources.requests.memory | string | `"64Mi"` | Memory request for the client container. |
| client.tolerations | list | `[]` | Tolerations for the client workload. |
| fullnameOverride | string | `""` | Override the full generated release name. |
| image | object | `{"pullPolicy":"IfNotPresent","repository":"loktionovam/iperf_exporter_server","tag":""}` | Container image settings shared by server and optional client workloads. |
| image.pullPolicy | string | `"IfNotPresent"` | Kubernetes image pull policy. |
| image.repository | string | `"loktionovam/iperf_exporter_server"` | Image repository for the exporter containers. |
| image.tag | string | `""` | Image tag to deploy. |
| imagePullSecrets | list | `[]` | Image pull secrets for private registries. |
| nameOverride | string | `""` | Override the chart name used in resource names. |
| podSecurityContext | object | `{"runAsNonRoot":true,"seccompProfile":{"type":"RuntimeDefault"}}` | Pod-level security context shared by workloads. |
| podSecurityContext.runAsNonRoot | bool | `true` | Require every container in the pod to run as non-root. |
| podSecurityContext.seccompProfile | object | `{"type":"RuntimeDefault"}` | Apply the default container-runtime seccomp profile. |
| securityContext | object | `{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]},"readOnlyRootFilesystem":true,"runAsNonRoot":true,"runAsUser":1000}` | Container security context shared by workloads. |
| securityContext.allowPrivilegeEscalation | bool | `false` | Prevent gaining extra privileges. |
| securityContext.capabilities | object | `{"drop":["ALL"]}` | Drop all Linux capabilities. |
| securityContext.readOnlyRootFilesystem | bool | `true` | Mount the container filesystem as read-only. |
| securityContext.runAsNonRoot | bool | `true` | Require the container to run as a non-root user. |
| securityContext.runAsUser | int | `1000` | Numeric UID used by the container process. |
| server | object | `{"affinity":{},"config":{"additionalParams":"","clientAdditionalParamsHint":"","clientBandwidthHint":"","len":1280,"metricTtl":3600,"pathTraceMaxHops":16,"pathTraceTimeout":10,"pathTraceTtl":300,"port":5001,"proto":"udp"},"enabled":true,"ingress":{"annotations":{},"className":"","enabled":false,"hosts":[{"host":"iperf-exporter.local","paths":[{"path":"/","pathType":"ImplementationSpecific"}]}],"tls":[]},"nodeSelector":{},"podAnnotations":{},"podLabels":{},"replicaCount":1,"resources":{"limits":{"cpu":"100m","memory":"64Mi"},"requests":{"cpu":"100m","memory":"64Mi"}},"service":{"port":9868,"type":"ClusterIP"},"tolerations":[]}` | Server workload configuration. |
| server.affinity | object | `{}` | Affinity rules for the server workload. |
| server.config | object | `{"additionalParams":"","clientAdditionalParamsHint":"","clientBandwidthHint":"","len":1280,"metricTtl":3600,"pathTraceMaxHops":16,"pathTraceTimeout":10,"pathTraceTtl":300,"port":5001,"proto":"udp"}` | Environment-level server settings passed to the exporter. |
| server.config.additionalParams | string | `""` | Extra iperf server flags appended to the server command, for example `--histograms=100u,20`. |
| server.config.clientAdditionalParamsHint | string | `""` | Optional client extra params hint shown in Grafana measurement-context tables when the client is external to this chart. |
| server.config.clientBandwidthHint | string | `""` | Optional client bandwidth hint shown in Grafana measurement-context tables when the client is external to this chart. |
| server.config.len | int | `1280` | Buffer length passed to the iperf server. |
| server.config.metricTtl | int | `3600` | TTL for inactive peer metrics before they are removed. |
| server.config.pathTraceMaxHops | int | `16` | Maximum number of hops used by `tracepath`. |
| server.config.pathTraceTimeout | int | `10` | Timeout in seconds for one `tracepath` execution. |
| server.config.pathTraceTtl | int | `300` | Seconds to cache `tracepath` snapshots. Set to `0` to disable path-trace metrics. |
| server.config.port | int | `5001` | iperf server listen port. |
| server.config.proto | string | `"udp"` | Protocol used by the iperf server (`udp` or `tcp`). |
| server.enabled | bool | `true` | Deploy the server workload. |
| server.ingress | object | `{"annotations":{},"className":"","enabled":false,"hosts":[{"host":"iperf-exporter.local","paths":[{"path":"/","pathType":"ImplementationSpecific"}]}],"tls":[]}` | Optional Ingress exposing the server metrics endpoint. |
| server.ingress.annotations | object | `{}` | Additional ingress annotations. |
| server.ingress.className | string | `""` | Ingress class name. |
| server.ingress.enabled | bool | `false` | Enable ingress creation for the metrics service. |
| server.ingress.hosts | list | `[{"host":"iperf-exporter.local","paths":[{"path":"/","pathType":"ImplementationSpecific"}]}]` | Ingress host and path rules. |
| server.ingress.tls | list | `[]` | TLS configuration for the ingress. |
| server.nodeSelector | object | `{}` | Node selector for the server workload. |
| server.podAnnotations | object | `{}` | Extra annotations for the server pod template. |
| server.podLabels | object | `{}` | Extra labels for the server pod template. |
| server.replicaCount | int | `1` | Number of server replicas. |
| server.resources | object | `{"limits":{"cpu":"100m","memory":"64Mi"},"requests":{"cpu":"100m","memory":"64Mi"}}` | CPU and memory resources for the server container. |
| server.resources.limits.cpu | string | `"100m"` | CPU limit for the server container. |
| server.resources.limits.memory | string | `"64Mi"` | Memory limit for the server container. |
| server.resources.requests.cpu | string | `"100m"` | CPU request for the server container. |
| server.resources.requests.memory | string | `"64Mi"` | Memory request for the server container. |
| server.service | object | `{"port":9868,"type":"ClusterIP"}` | Kubernetes Service settings exposing exporter metrics. |
| server.service.port | int | `9868` | Service port for the Prometheus metrics endpoint. |
| server.service.type | string | `"ClusterIP"` | Service type for the server metrics endpoint. |
| server.tolerations | list | `[]` | Tolerations for the server workload. |
| serviceAccount | object | `{"annotations":{},"create":true,"name":""}` | Service account settings for the server workload. |
| serviceAccount.annotations | object | `{}` | Additional annotations for the ServiceAccount. |
| serviceAccount.create | bool | `true` | Create a dedicated ServiceAccount for the server workload. |
| serviceAccount.name | string | `""` | Existing ServiceAccount name to use when `create=false`. |
| serviceMonitor | object | `{"additionalLabels":{},"enabled":false,"interval":"1m","port":"http-metrics"}` | ServiceMonitor settings for Prometheus Operator integration. |
| serviceMonitor.additionalLabels | object | `{}` | Extra labels used by the Prometheus Operator selector. |
| serviceMonitor.enabled | bool | `false` | Create a ServiceMonitor for the server metrics service. |
| serviceMonitor.interval | string | `"1m"` | Scrape interval used by the ServiceMonitor. |
| serviceMonitor.port | string | `"http-metrics"` | Named service port scraped by the ServiceMonitor. |
