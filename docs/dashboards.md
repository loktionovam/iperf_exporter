# Grafana dashboards

Three dashboards cover traffic, connection quality and measurement health.
They share filters for clusters, nodes, measurements and connection pairs.

Import the JSON files below into Grafana using **Dashboards → New → Import**,
then select your Prometheus datasource. The [local demos](../demo/README.md)
provision all three automatically. For collection setup, see
[installation](installation.md#prometheus-and-grafana).

These screenshots show real measurements from the kind demo. Zero losses or
retransmissions are valid results; error counters show actual demo events.

## Overview

[Dashboard JSON](../grafana/dashboards/iperf-exporter-overview.json)

Active streams and TCP/UDP traffic.

![Overview — streams and traffic](../grafana/img/overview-01.png)

Per-interval transfer and read activity.

![Overview — interval detail](../grafana/img/overview-02.png)

Data freshness, test outcomes and exporter errors.

![Overview — freshness and outcomes](../grafana/img/overview-03.png)

Operator availability, reconciliation and remote-cluster health.

![Overview — operator health](../grafana/img/overview-04.png)

## TCP Quality

[Dashboard JSON](../grafana/dashboards/iperf-exporter-tcp-quality.json)

Measurement parameters and the observed server-to-client route.

![TCP — context and route](../grafana/img/tcp-quality-01.png)

Throughput and server read behavior.

![TCP — throughput and reads](../grafana/img/tcp-quality-02.png)

Burst latency and its distribution.

![TCP — latency and histogram](../grafana/img/tcp-quality-03.png)

Socket state and retransmissions.

![TCP — sockets and retransmissions](../grafana/img/tcp-quality-04.png)

## UDP Quality

[Dashboard JSON](../grafana/dashboards/iperf-exporter-udp-quality.json)

Measurement parameters and the observed server-to-client route.

![UDP — context and route](../grafana/img/udp-quality-01.png)

Packet loss and jitter.

![UDP — loss and jitter](../grafana/img/udp-quality-02.png)

Latency spread, packet rate and socket queues.

![UDP — latency, rate and queues](../grafana/img/udp-quality-03.png)

Exporter availability, sample freshness and test outcomes.

![UDP — freshness and outcomes](../grafana/img/udp-quality-04.png)

Read the [metrics reference](metrics.md) for units, counter semantics and the
clock synchronization requirements of one-way latency measurements.
