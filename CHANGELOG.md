# Changelog


## (unreleased)

### Other

* Add Kubernetes operator and kind demo. [Aleksandr Loktionov]

  This commit introduces a complete Kubernetes operator implementation for iperf_exporter,
  enabling declarative network performance measurement management via CRDs.

  Major additions:
  - MeasurementProfile, LinkMeasurement, and MeasurementSession CRDs with full validation
  - kopf-based operator controller with reconciliation logic for all CRD types
  - Support for three execution modes: continuous, probe, and periodicProbe
  - Three network modes: host, pod, and service with proper service topology
  - Bidirectional session expansion from single LinkMeasurement resources
  - Context labels propagated to Prometheus metrics for operator-managed measurements

  kind cluster demo:
  - 3-node kind cluster with ingress-nginx controller
  - In-cluster Prometheus and Grafana with pre-provisioned dashboards
  - Six reusable measurement profiles (TCP/UDP quality, throughput, loss)
  - Six example measurements demonstrating all execution and network modes
  - Integration tests validating cluster setup and metric availability

  Exporter enhancements:
  - Client execution mode support (continuous, probe, periodicProbe)
  - Configurable client duration and interval parameters
  - Context label environment variables for operator integration
  - Period-based probe loop for periodic measurements

  Grafana dashboards updated:
  - Dynamic variable filtering by measurement_id, profile_ref, execution_mode, direction
  - Node and cluster filtering for multi-cluster monitoring readiness
  - Network mode indicators for topology-aware analysis

  Testing:
  - Unit tests for operator spec expansion and manifest generation
  - Integration tests for kind demo cluster health and CRD reconciliation
  - Updated existing tests to accommodate new CLI and collector parameters


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


