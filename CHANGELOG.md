# Changelog


## (unreleased)

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


