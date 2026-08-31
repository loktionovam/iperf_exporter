# Exported metrics

The exporter exposes `/metrics` on port `9868` by default. TCP/UDP interval
reports are gauges describing the latest interval, not cumulative counters.
Use the reported bandwidth directly; do not apply `rate()` to interval transfer
or bandwidth gauges. Metrics ending in `_total` that are documented as counters
can be used with `rate()`.

Measurements use **iperf2**, not iperf3. One-way latency from `--trip-times`
requires synchronized client and server clocks; clock error biases the result.
Socket metrics describe the exporter/server side. Path traces run from server
to client and may differ from the measured traffic's route.

[Installation](installation.md) · [Dashboards](dashboards.md) ·
[Operator metrics](operator-crds.md#operator-metrics)

## Common labels on per-stream metrics

All UDP and TCP stream metrics share the same label set:

| Label | Meaning |
| --- | --- |
| `peer_id` | Connection identifier emitted by `iperf`. |
| `local_address` | Server-side local address that accepted the stream. |
| `interface_name` | Interface suffix parsed from the local address if present in `iperf` output. |
| `local_port` | Server-side listening port. |
| `peer_address` | Client address seen by the server. |
| `peer_port` | Client source port seen by the server. |
| `connection_pair` | Convenience label in the form `<peer_address>-><local_address>`, intended for Grafana filtering by client/server pair. |
| `measurement_id` | Optional higher-level measurement identifier. Populated by the operator; empty for standalone runs. |
| `profile_ref` | Optional `MeasurementProfile` reference name. Populated by the operator; empty for standalone runs. |
| `session_id` | Optional session identifier. Populated by the operator; empty for standalone runs. |
| `execution_mode` | Optional execution mode such as `continuous`, `probe` or `periodicProbe`. Populated by the operator; empty for standalone runs. |
| `direction` | Optional direction such as `sourceToDestination` or `destinationToSource`. Populated by the operator; empty for standalone runs. |
| `network_mode` | Optional topology hint such as `host`, `pod` or `service`. Populated by the operator; empty for standalone runs. |
| `src_node` | Optional source node name. Populated by the operator; empty for standalone runs. |
| `dst_node` | Optional destination node name. Populated by the operator; empty for standalone runs. |
| `src_cluster` | Optional source cluster name. Populated by the operator; empty for standalone runs. |
| `dst_cluster` | Optional destination cluster name. Populated by the operator; empty for standalone runs. |

## UDP metrics

These metrics are created from UDP server-side interval reports.

| Metric | Unit | Meaning |
| --- | --- | --- |
| `iperf_exporter_udp_transfer` | bytes | Payload transferred during the reporting interval. |
| `iperf_exporter_udp_bandwidth` | bits/sec | UDP bitrate reported by `iperf` for the interval. |
| `iperf_exporter_udp_jitter` | ms | UDP jitter reported by `iperf`. |
| `iperf_exporter_udp_lost` | packets | Lost UDP packets during the interval. |
| `iperf_exporter_udp_total` | packets | Total UDP packets sent during the interval. |
| `iperf_exporter_udp_lost_percentage` | percent | Packet loss percentage for the interval. |
| `iperf_exporter_udp_latency_avg` | ms | Average latency reported by `iperf`. |
| `iperf_exporter_udp_latency_min` | ms | Minimum latency reported by `iperf`. |
| `iperf_exporter_udp_latency_max` | ms | Maximum latency reported by `iperf`. |
| `iperf_exporter_udp_latency_stdev` | ms | Latency standard deviation reported by `iperf`. |
| `iperf_exporter_udp_pps` | packets/sec | Packets per second reported by `iperf`. |
| `iperf_exporter_udp_netpwr` | iperf2 net power | Net power value from `iperf2` enhanced output. This is an `iperf2`-specific composite signal, not a Prometheus or IETF standard metric. |

## UDP test-condition info metric

This metric captures the static context for each UDP stream so Grafana can answer "under what conditions was this measured?" directly from labels. In server mode you can also populate optional client-side launch hints with `IPERF_EXPORTER_CONTEXT_CLIENT_BANDWIDTH` and `IPERF_EXPORTER_CONTEXT_CLIENT_ADDITIONAL_PARAMS`.

| Metric | Unit | Meaning |
| --- | --- | --- |
| `iperf_exporter_udp_test_info` | info | Gauge with constant value `1`. Labels carry the test context: `peer_version`, `trip_times_enabled`, `report_interval_seconds`, optional `client_bandwidth_limit`, optional `client_additional_params`, `server_len_bytes`, `server_udp_buffer_bytes` and `server_additional_params`. |

## UDP path-trace metrics

These metrics are sampled with `tracepath -n` from the exporter/server network namespace toward the peer/client address and cached for `IPERF_EXPORTER_PATH_TRACE_TTL` seconds. They show the route observed from server to client, which may differ from the reverse client-to-server path that carried the measured traffic.

| Metric | Unit | Meaning |
| --- | --- | --- |
| `iperf_exporter_udp_path_trace_success` | bool | `1` when the last cached `tracepath` run reached the peer/client address. |
| `iperf_exporter_udp_path_trace_pmtu_bytes` | bytes | Path MTU reported by `tracepath`. |
| `iperf_exporter_udp_path_trace_hops_total` | hops | Hop count reported by `tracepath`. |
| `iperf_exporter_udp_path_trace_hop_info` | info | Gauge with constant value `1`. Labels carry one hop from the last cached trace snapshot: `trace_direction`, `hop_index` and `hop_address`. |

## UDP socket metrics

These metrics are server-side kernel socket snapshots collected from `ss -uin` and matched to active `iperf` peers by local/remote address and port.

| Metric | Unit | Meaning |
| --- | --- | --- |
| `iperf_exporter_udp_socket_recv_queue_bytes` | bytes | Bytes currently queued in the UDP receive queue on the exporter host. |
| `iperf_exporter_udp_socket_send_queue_bytes` | bytes | Bytes currently queued in the UDP send queue on the exporter host. |

## TCP metrics

These metrics are created from TCP server-side interval reports. Some of them are only available when the client runs with `--trip-times` and the server runs with `--histograms=...`.

| Metric | Unit | Meaning |
| --- | --- | --- |
| `iperf_exporter_tcp_transfer` | bytes | Payload transferred during the reporting interval. |
| `iperf_exporter_tcp_bandwidth` | bits/sec | TCP bitrate reported by `iperf` for the interval. |
| `iperf_exporter_tcp_reads` | reads | Number of server-side TCP read operations reported by `iperf` for the interval. |
| `iperf_exporter_tcp_burst_latency_avg` | ms | Average TCP write-to-read latency reported by `iperf2 --trip-times`. |
| `iperf_exporter_tcp_burst_latency_min` | ms | Minimum TCP write-to-read latency reported by `iperf2 --trip-times`. |
| `iperf_exporter_tcp_burst_latency_max` | ms | Maximum TCP write-to-read latency reported by `iperf2 --trip-times`. |
| `iperf_exporter_tcp_burst_latency_stdev` | ms | TCP write-to-read latency standard deviation reported by `iperf2 --trip-times`. |
| `iperf_exporter_tcp_burst_count` | bursts | Number of TCP bursts included in the reporting interval. |
| `iperf_exporter_tcp_burst_size` | bytes | TCP burst size reported by `iperf2` for the reporting interval. |
| `iperf_exporter_tcp_inprogress_bytes` | bytes | Bytes reported by `iperf2` as still in progress / queued at the receiver. |
| `iperf_exporter_tcp_netpwr` | iperf2 net power | TCP net power value from `iperf2` enhanced trip-times output. |
| `iperf_exporter_tcp_read_bin_0` | reads | Count of reads in `Reads=Dist` bin 0. |
| `iperf_exporter_tcp_read_bin_1` | reads | Count of reads in `Reads=Dist` bin 1. |
| `iperf_exporter_tcp_read_bin_2` | reads | Count of reads in `Reads=Dist` bin 2. |
| `iperf_exporter_tcp_read_bin_3` | reads | Count of reads in `Reads=Dist` bin 3. |
| `iperf_exporter_tcp_read_bin_4` | reads | Count of reads in `Reads=Dist` bin 4. |
| `iperf_exporter_tcp_read_bin_5` | reads | Count of reads in `Reads=Dist` bin 5. |
| `iperf_exporter_tcp_read_bin_6` | reads | Count of reads in `Reads=Dist` bin 6. |
| `iperf_exporter_tcp_read_bin_7` | reads | Count of reads in `Reads=Dist` bin 7. |
| `iperf_exporter_tcp_latency_histogram_bin_count` | samples | Raw count stored in one TCP latency histogram bin. This metric adds `histogram_name`, `upper_bound_seconds` and `upper_bound_ms` labels. |
| `iperf_exporter_tcp_latency_histogram_bucket` | samples | Cumulative TCP latency histogram buckets with Prometheus-style `le` labels in milliseconds, intended for heatmap-style visualizations. |
| `iperf_exporter_tcp_latency_histogram_sample_count` | samples | Total number of samples in one TCP latency histogram snapshot. This metric adds the `histogram_name` label. |
| `iperf_exporter_tcp_latency_histogram_bin_width_seconds` | seconds | Width of one TCP latency histogram bin. This metric adds the `histogram_name` label. |

TCP notes:

- `iperf_exporter_tcp_read_bin_<0..7>` comes from the `Reads=Dist` field in `iperf2` enhanced output. The exact byte boundaries depend on the server read buffer configuration shown by `iperf`.
- `burst_*`, `inprogress_bytes`, `netpwr` and `tcp_latency_histogram_*` require `--trip-times` on the client. Histogram metrics additionally require `--histograms=...` on the server.

## TCP test-condition info metric

This metric captures the static context for each TCP stream so Grafana can show how a given pair was measured. In server mode you can also populate optional client-side launch hints with `IPERF_EXPORTER_CONTEXT_CLIENT_BANDWIDTH` and `IPERF_EXPORTER_CONTEXT_CLIENT_ADDITIONAL_PARAMS`.

| Metric | Unit | Meaning |
| --- | --- | --- |
| `iperf_exporter_tcp_test_info` | info | Gauge with constant value `1`. Labels carry the test context: `peer_version`, `trip_times_enabled`, `report_interval_seconds`, optional `client_bandwidth_limit`, optional `client_additional_params`, `initial_cwnd_segments`, `initial_mss_bytes`, `initial_rtt_microseconds`, `server_len_bytes`, `server_window_bytes`, `server_read_buffer_bytes`, `server_read_dist_bin_width_bytes`, `server_histogram_bin_width_ms`, `server_histogram_bin_count`, `server_congestion_control_default` and `server_additional_params`. |

## TCP path-trace metrics

These metrics are sampled with `tracepath -n` from the exporter/server network namespace toward the peer/client address and cached for `IPERF_EXPORTER_PATH_TRACE_TTL` seconds. They show the route observed from server to client, which may differ from the reverse client-to-server path that carried the measured traffic.

| Metric | Unit | Meaning |
| --- | --- | --- |
| `iperf_exporter_tcp_path_trace_success` | bool | `1` when the last cached `tracepath` run reached the peer/client address. |
| `iperf_exporter_tcp_path_trace_pmtu_bytes` | bytes | Path MTU reported by `tracepath`. |
| `iperf_exporter_tcp_path_trace_hops_total` | hops | Hop count reported by `tracepath`. |
| `iperf_exporter_tcp_path_trace_hop_info` | info | Gauge with constant value `1`. Labels carry one hop from the last cached trace snapshot: `trace_direction`, `hop_index` and `hop_address`. |

## TCP socket metrics

These metrics are server-side kernel socket snapshots collected from `ss -tin` and matched to active `iperf` peers by local/remote address and port. Unlike the interval metrics above, these values are instantaneous scrape-time socket state and can reset when the TCP connection is re-established.

| Metric | Unit | Meaning |
| --- | --- | --- |
| `iperf_exporter_tcp_socket_recv_queue_bytes` | bytes | Bytes currently queued in the TCP receive queue on the exporter host. |
| `iperf_exporter_tcp_socket_send_queue_bytes` | bytes | Bytes currently queued in the TCP send queue on the exporter host. |
| `iperf_exporter_tcp_socket_info` | info | Gauge with constant value `1`. Labels carry stable negotiated socket properties from `ss`: `congestion_algorithm`, `socket_state`, `mss_bytes`, `pmtu_bytes`, `rcvmss_bytes`, `advmss_bytes`, `send_wscale` and `rcv_wscale`. |
| `iperf_exporter_tcp_socket_app_limited` | bool | `1` when `ss` reports the socket as `app_limited`, otherwise `0`. |
| `iperf_exporter_tcp_socket_rto_milliseconds` | ms | TCP retransmission timeout from `ss`. |
| `iperf_exporter_tcp_socket_rtt_milliseconds` | ms | Smoothed TCP RTT from `ss`. |
| `iperf_exporter_tcp_socket_rttvar_milliseconds` | ms | TCP RTT variation from `ss`. |
| `iperf_exporter_tcp_socket_ato_milliseconds` | ms | TCP delayed ACK timeout from `ss`. |
| `iperf_exporter_tcp_socket_mss_bytes` | bytes | Maximum segment size from `ss`. |
| `iperf_exporter_tcp_socket_pmtu_bytes` | bytes | Path MTU from `ss`. |
| `iperf_exporter_tcp_socket_rcvmss_bytes` | bytes | Receive MSS from `ss`. |
| `iperf_exporter_tcp_socket_advmss_bytes` | bytes | Advertised MSS from `ss`. |
| `iperf_exporter_tcp_socket_cwnd_segments` | segments | Congestion window from `ss`. |
| `iperf_exporter_tcp_socket_bytes_sent` | bytes | Total bytes sent on the socket according to `ss`. |
| `iperf_exporter_tcp_socket_bytes_acked` | bytes | Total bytes acknowledged on the socket according to `ss`. |
| `iperf_exporter_tcp_socket_bytes_received` | bytes | Total bytes received on the socket according to `ss`. |
| `iperf_exporter_tcp_socket_bytes_retransmitted_total` | bytes | Total retransmitted bytes for the current socket according to `ss`. |
| `iperf_exporter_tcp_socket_retransmissions_total` | retransmissions | Total retransmissions for the current socket according to `ss`. |
| `iperf_exporter_tcp_socket_segs_out` | segments | Total TCP segments sent according to `ss`. |
| `iperf_exporter_tcp_socket_segs_in` | segments | Total TCP segments received according to `ss`. |
| `iperf_exporter_tcp_socket_data_segs_out` | segments | Total TCP data segments sent according to `ss`. |
| `iperf_exporter_tcp_socket_data_segs_in` | segments | Total TCP data segments received according to `ss`. |
| `iperf_exporter_tcp_socket_send_rate_bps` | bits/sec | Sender throughput estimate from `ss`. |
| `iperf_exporter_tcp_socket_pacing_rate_bps` | bits/sec | Kernel TCP pacing rate from `ss`. |
| `iperf_exporter_tcp_socket_delivery_rate_bps` | bits/sec | TCP delivery rate estimate from `ss`. |
| `iperf_exporter_tcp_socket_delivered` | packets | Delivered packets counter from `ss`. |
| `iperf_exporter_tcp_socket_rcv_rtt_milliseconds` | ms | Receiver-side RTT from `ss`. |
| `iperf_exporter_tcp_socket_rcv_space_bytes` | bytes | TCP receive space from `ss`. |
| `iperf_exporter_tcp_socket_rcv_ssthresh_bytes` | bytes | TCP receive slow-start threshold from `ss`. |
| `iperf_exporter_tcp_socket_min_rtt_milliseconds` | ms | Minimum RTT from `ss`. |
| `iperf_exporter_tcp_socket_lastsnd_milliseconds` | ms | Milliseconds since the last TCP send. |
| `iperf_exporter_tcp_socket_lastrcv_milliseconds` | ms | Milliseconds since the last TCP receive. |
| `iperf_exporter_tcp_socket_lastack_milliseconds` | ms | Milliseconds since the last TCP ACK. |
| `iperf_exporter_tcp_socket_snd_wnd_bytes` | bytes | Sender window size from `ss`. |
| `iperf_exporter_tcp_socket_rcv_wnd_bytes` | bytes | Receiver window size from `ss`. |
| `iperf_exporter_tcp_socket_send_wscale` | scale factor | Send window scale from `ss`. |
| `iperf_exporter_tcp_socket_rcv_wscale` | scale factor | Receive window scale from `ss`. |

TCP socket notes:

- These values come from `ss -tin`, not from `iperf` interval output. They represent current kernel socket state on the exporter host.
- Queue, RTT, pacing and window metrics are only emitted while a matching socket exists for the current `connection_pair`.
- Retransmission counters belong to a socket and reset when that socket is recreated. A useful per-stream ratio is `rate(iperf_exporter_tcp_socket_bytes_retransmitted_total[5m]) / clamp_min(rate(iperf_exporter_tcp_socket_bytes_sent[5m]), 1)`.
- The exporter is best-effort here: if `ss` is unavailable or returns no matching row, the scrape still succeeds and only the socket metrics are absent.

## Exporter health and lifecycle metrics

These metrics describe the supervised child `iperf` process, data freshness, test
outcomes and best-effort collectors. Runtime metrics include the `proto` and
optional operator context labels. Collector errors use bounded `collector` and
`reason` labels.

| Metric | Labels | Meaning |
| --- | --- | --- |
| `iperf_exporter_iperf_process_up` | `mode`, `proto` | `1` when the supervised `iperf` process is alive, `0` when it is not. |
| `iperf_exporter_iperf_process_restarts_total` | `mode`, `proto` | Number of automatic restarts performed by the exporter watchdog. |
| `iperf_exporter_iperf_process_last_exit_code` | `mode`, `proto` | Last observed child process exit code. This metric appears after the first observed exit. |
| `iperf_exporter_active_streams` | `proto` | Number of peer streams currently retained by the exporter. |
| `iperf_exporter_connections_total` | `proto` | Client connections observed by the `iperf` server. |
| `iperf_exporter_samples_total` | `proto` | Valid interval reports parsed from `iperf` output. |
| `iperf_exporter_parse_errors_total` | `proto` | Interval or histogram lines that could not be parsed safely. |
| `iperf_exporter_samples_evicted_total` | `proto`, `reason` | Retained stream samples removed from memory. `ttl` is currently the active reason. |
| `iperf_exporter_test_runs_total` | `proto`, `result` | Observed outcomes. `success` is the first valid report for a connection, `timeout` is TTL eviction before any valid report, and `error` is an `iperf` child restart. |
| `iperf_exporter_test_duration_seconds` | stream labels | Elapsed duration from the latest `iperf` interval report for each retained stream. |
| `iperf_exporter_sample_timestamp_seconds` | `proto` | Unix timestamp of the latest valid interval report. |
| `iperf_exporter_test_last_success_timestamp_seconds` | `proto` | Unix timestamp of the latest connection that produced its first valid report. |
| `iperf_exporter_last_connection_timestamp_seconds` | `proto` | Unix timestamp of the latest client connection. |
| `iperf_exporter_start_time_seconds` | `proto` | Unix timestamp when the exporter collector started. |
| `iperf_exporter_collector_duration_seconds` | `collector` | Duration of the latest `iperf`, `socket`, `path_trace`, or complete exporter collection. |
| `iperf_exporter_collector_errors_total` | `collector`, `reason` | Collector failures grouped by a bounded reason such as `timeout`, `unavailable`, `command`, or `exception`. |
| `iperf_exporter_collector_last_success_timestamp_seconds` | `collector` | Unix timestamp of the latest successful collector execution. |
| `iperf_exporter_path_trace_duration_seconds` | `proto` | Duration of the latest completed background `tracepath` execution. |
| `iperf_exporter_path_trace_failures_total` | `proto`, `reason` | Background trace failures grouped by `unavailable`, `timeout`, `command`, `parse`, `unreachable`, or `worker`. |
| `iperf_exporter_path_trace_last_success_timestamp_seconds` | `proto` | Unix timestamp of the latest trace that reached its destination. |
| `iperf_exporter_path_trace_in_flight` | `proto` | Number of background traces currently running. |
| `iperf_exporter_build_info` | `version`, `python_version` | Constant `1` with build and Python runtime information. |

The server-side exporter cannot know the exact Kubernetes Job completion time.
For one-shot probes, use `iperf_operator_probe_duration_seconds` and
`iperf_operator_probe_runs_total` from the operator endpoint.
