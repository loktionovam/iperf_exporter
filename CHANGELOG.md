# Changelog


## v4.0.0 (unreleased)

* Promote all four operator resources to `netperf.iperfexporter.io/v1`.
  The alpha API and legacy workload names are no longer supported; the operator
  chart requires a clean installation when alpha CRDs are present.
* Add the `iperf-operator` Helm chart with namespace-scoped operation, configurable
  operator/exporter images, metrics services, and optional ServiceMonitors.
* Require an explicit default exporter image when starting the operator; remove
  the old environment variable alias and implicit demo image fallback.
* Run two-cluster kind tests for pull requests and gate image, chart, and release
  publication on all checks. Publish the tested images without rebuilding them.
* Reorganize the README around installation and first measurements, with focused
  installation, metric, and dashboard references and fresh demo screenshots.


## v3.0.0 (2026-07-24)

### Breaking changes

* Remove the unused `allowOverlap`, `env`, `serverEnv`, `clientEnv`, and
  user-supplied `nodeAddress` fields from the experimental `v1alpha1` API.
  Reapply the CRDs, `MeasurementProfile`, and `LinkMeasurement` resources after
  upgrading; generated `MeasurementSession` resources are recreated.
* Remove the dynamic `hop_summary` label from path-trace metrics.
* Use a consistent 3600-second metric TTL across CLI, containers, Helm, and the
  operator.

### Operator

* Add declarative profile, measurement, session, and remote-cluster
  reconciliation for continuous, probe, and periodic-probe execution.
* Keep completed and failed probe Jobs as one-shot results. A probe runs again
  only after its Job is explicitly deleted or the desired generation changes.
* Preserve existing workloads when a StatefulSet patch is rejected and retain
  finalizers while remote-cluster cleanup is unavailable.
* Add strict CRD validation, safe Kubernetes label normalization, namespace
  RBAC, restricted pod security settings, and operator runtime metrics.
* Add a two-cluster kind demo with live exporter/operator integration tests.

### Exporter and observability

* Replace ConfigArgParse with validated `argparse` CLI and environment handling.
* Add graceful process shutdown, bounded `ss` collection, exporter lifecycle
  metrics, test outcomes, collector errors, and TCP retransmission counters.
* Move path tracing to a deduplicated background worker so Prometheus scrapes do
  not wait for `tracepath`.
* Add exporter and operator health panels, test outcomes, freshness,
  retransmission panels, and updated screenshots to the Grafana dashboards.

### Delivery

* Publish TCP and UDP iperf ports from the Helm Service and verify both protocols
  with a real Helm test.
* Build and scan exporter and operator images, validate manifests and dashboards,
  and run Python 3.10/3.14 plus two-cluster kind tests in CI.
* Package the Helm chart with Helm and publish it through chart-releaser.


## v2.0.0 (2026-03-26)

### Other

* Add support for TCP metrics, client workload, and Grafana dashboards. [Aleksandr Loktionov]

  - TCP protocol support alongside UDP with per-stream metrics (transfer, bandwidth, reads)
  - Optional in-cluster client workload deployable as Deployment or DaemonSet
  - Process health metrics (uptime, restart count, exit code) for supervised iperf process
  - Automatic watchdog that restarts crashed iperf child processes
  - Metric TTL-based cleanup for inactive peer streams
  - Three Grafana dashboards: overview, UDP quality, TCP quality
  - Local demo stack with docker-compose for quick testing
  - Improved Docker image with pip-based installation and security updates
  - Refactored Helm chart with independent server/client configuration
  - Enhanced CLI with better error handling and testability
  - Comprehensive test coverage for TCP/UDP parsing and process management


## v1.0.0 (2023-06-11)

### Other

* Update the project. [Aleksandr Loktionov]

* Update CI and README. [Aleksandr Loktionov]

* Fix logger name. [Aleksandr Loktionov]

* Print client output to logs. [Aleksandr Loktionov]

* Fix servicemonitor. [Aleksandr Loktionov]

* Update helm chart. [Aleksandr Loktionov]

* Initial commit. [Aleksandr Loktionov]

