from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

from iperf_exporter.iperf import (
    IPerfServer,
    IPerfServerTCPHistogramOutput,
    IPerfServerTCPOutput,
    IPerfServerUDPOutput,
)
from iperf_exporter.logger import log
from iperf_exporter.path_trace import PathTraceCollector, PathTraceSnapshot
from iperf_exporter.socket_stats import SocketStatsCollector, TCPSocketSnapshot

LABEL_NAMES = [
    "peer_id",
    "local_address",
    "interface_name",
    "local_port",
    "peer_address",
    "peer_port",
    "connection_pair",
]
PROCESS_LABEL_NAMES = ["mode", "proto"]
TCP_SOCKET_INFO_LABEL_NAMES = LABEL_NAMES + [
    "congestion_algorithm",
    "socket_state",
    "mss_bytes",
    "pmtu_bytes",
    "rcvmss_bytes",
    "advmss_bytes",
    "send_wscale",
    "rcv_wscale",
]
TCP_TEST_INFO_LABEL_NAMES = LABEL_NAMES + [
    "peer_version",
    "trip_times_enabled",
    "report_interval_seconds",
    "client_bandwidth_limit",
    "client_additional_params",
    "initial_cwnd_segments",
    "initial_mss_bytes",
    "initial_rtt_microseconds",
    "server_len_bytes",
    "server_window_bytes",
    "server_read_buffer_bytes",
    "server_read_dist_bin_width_bytes",
    "server_histogram_bin_width_ms",
    "server_histogram_bin_count",
    "server_congestion_control_default",
    "server_additional_params",
]
UDP_TEST_INFO_LABEL_NAMES = LABEL_NAMES + [
    "peer_version",
    "trip_times_enabled",
    "report_interval_seconds",
    "client_bandwidth_limit",
    "client_additional_params",
    "server_len_bytes",
    "server_udp_buffer_bytes",
    "server_additional_params",
]
PATH_TRACE_LABEL_NAMES = LABEL_NAMES + ["trace_direction"]
PATH_TRACE_HOP_LABEL_NAMES = PATH_TRACE_LABEL_NAMES + [
    "hop_index",
    "hop_address",
    "hop_summary",
]
TCP_HISTOGRAM_LABEL_NAMES = LABEL_NAMES + [
    "histogram_name",
    "upper_bound_seconds",
    "upper_bound_ms",
]
TCP_HISTOGRAM_INFO_LABEL_NAMES = LABEL_NAMES + ["histogram_name"]
TCP_HISTOGRAM_BUCKET_LABEL_NAMES = LABEL_NAMES + ["histogram_name", "le"]


def _connection_pair_label(out: IPerfServerUDPOutput | IPerfServerTCPOutput) -> str:
    return f"{out.peer_address}->{out.local_address}"


def _format_float_label(value: float) -> str:
    return f"{value:.12g}"


def _label_values(out: IPerfServerUDPOutput | IPerfServerTCPOutput) -> list[str]:
    return [
        out.peer_id,
        out.local_address,
        out.interface_name,
        out.local_port,
        out.peer_address,
        out.peer_port,
        _connection_pair_label(out),
    ]


def _socket_key(
    out: IPerfServerUDPOutput | IPerfServerTCPOutput,
) -> tuple[str, str, str, str]:
    return (
        out.local_address,
        out.local_port,
        out.peer_address,
        out.peer_port,
    )


def _find_socket_snapshot(
    out: IPerfServerUDPOutput | IPerfServerTCPOutput,
    socket_snapshots: dict[tuple[str, str, str, str], object],
):
    exact_key = _socket_key(out)
    if exact_key in socket_snapshots:
        return socket_snapshots[exact_key]

    for wildcard_local_address in ("0.0.0.0", "::", "*"):
        wildcard_key = (
            wildcard_local_address,
            out.local_port,
            out.peer_address,
            out.peer_port,
        )
        if wildcard_key in socket_snapshots:
            return socket_snapshots[wildcard_key]

    return None


def _label_value_or_empty(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _format_float_label(float(value))
    return str(value)


class IPerfMetricsBase:
    metrics_prefix = ""
    metric_names = []
    metric_descriptions = {}

    def __init__(self, output: dict[str, IPerfServerUDPOutput | IPerfServerTCPOutput]):
        self.data = {}
        for name in self.metric_names:
            metric_name = f"{self.metrics_prefix}_{name}"
            self.data[metric_name] = GaugeMetricFamily(
                metric_name,
                self.metric_descriptions.get(name, ""),
                labels=LABEL_NAMES,
            )

        for peer_id, out in output.items():
            label_values = _label_values(out)
            for name in self.metric_names:
                metric_name = f"{self.metrics_prefix}_{name}"
                metric_value = getattr(out, name, None)
                if metric_value is None:
                    log.debug(f"Client {peer_id = } doesn't have metric {name = }")
                    continue

                log.debug(f"Add metric {metric_name = } with {label_values = }")
                self.data[metric_name].add_metric(label_values, float(metric_value))

    def __iter__(self):
        for metric in self.data.values():
            yield metric


class IPerfUDPMetrics(IPerfMetricsBase):
    """
    The data class which represents iperf udp output in a prometheus format.
    """

    metrics_prefix = "iperf_exporter_udp"
    metric_names = [
        "transfer",
        "bandwidth",
        "jitter",
        "lost",
        "total",
        "lost_percentage",
        "latency_avg",
        "latency_min",
        "latency_max",
        "latency_stdev",
        "pps",
        "netpwr",
    ]
    metric_descriptions = {
        "transfer": "UDP bytes transferred during the reporting interval.",
        "bandwidth": "UDP bitrate reported by iperf for the interval, in bits per second.",
        "jitter": "UDP jitter reported by iperf, in milliseconds.",
        "lost": "UDP packets lost during the reporting interval.",
        "total": "Total UDP packets sent during the reporting interval.",
        "lost_percentage": "UDP packet loss percentage for the reporting interval.",
        "latency_avg": "Average UDP latency reported by iperf, in milliseconds.",
        "latency_min": "Minimum UDP latency reported by iperf, in milliseconds.",
        "latency_max": "Maximum UDP latency reported by iperf, in milliseconds.",
        "latency_stdev": "UDP latency standard deviation reported by iperf, in milliseconds.",
        "pps": "UDP packets per second reported by iperf for the interval.",
        "netpwr": "UDP net power value reported by iperf enhanced output.",
    }


class IPerfTCPMetrics(IPerfMetricsBase):
    """
    The data class which represents iperf tcp output in a prometheus format.
    """

    metrics_prefix = "iperf_exporter_tcp"
    metric_names = [
        "transfer",
        "bandwidth",
        "reads",
        "burst_latency_avg",
        "burst_latency_min",
        "burst_latency_max",
        "burst_latency_stdev",
        "burst_count",
        "burst_size",
        "inprogress_bytes",
        "netpwr",
        "read_bin_0",
        "read_bin_1",
        "read_bin_2",
        "read_bin_3",
        "read_bin_4",
        "read_bin_5",
        "read_bin_6",
        "read_bin_7",
    ]
    metric_descriptions = {
        "transfer": "TCP bytes transferred during the reporting interval.",
        "bandwidth": "TCP bitrate reported by iperf for the interval, in bits per second.",
        "reads": "Number of TCP read operations reported by the iperf server for the interval.",
        "burst_latency_avg": "Average TCP write-to-read latency reported by iperf2 trip-times output, in milliseconds.",
        "burst_latency_min": "Minimum TCP write-to-read latency reported by iperf2 trip-times output, in milliseconds.",
        "burst_latency_max": "Maximum TCP write-to-read latency reported by iperf2 trip-times output, in milliseconds.",
        "burst_latency_stdev": "Standard deviation of TCP write-to-read latency reported by iperf2 trip-times output, in milliseconds.",
        "burst_count": "Number of TCP bursts observed by iperf2 during the reporting interval.",
        "burst_size": "TCP burst size reported by iperf2 for the reporting interval, in bytes.",
        "inprogress_bytes": "Amount of TCP data reported by iperf2 as in-progress / queued at the receiver, in bytes.",
        "netpwr": "TCP net power value reported by iperf2 enhanced trip-times output.",
        "read_bin_0": "TCP Reads=Dist bin 0 count from iperf2 enhanced output. Bin boundaries depend on the server read buffer configuration.",
        "read_bin_1": "TCP Reads=Dist bin 1 count from iperf2 enhanced output. Bin boundaries depend on the server read buffer configuration.",
        "read_bin_2": "TCP Reads=Dist bin 2 count from iperf2 enhanced output. Bin boundaries depend on the server read buffer configuration.",
        "read_bin_3": "TCP Reads=Dist bin 3 count from iperf2 enhanced output. Bin boundaries depend on the server read buffer configuration.",
        "read_bin_4": "TCP Reads=Dist bin 4 count from iperf2 enhanced output. Bin boundaries depend on the server read buffer configuration.",
        "read_bin_5": "TCP Reads=Dist bin 5 count from iperf2 enhanced output. Bin boundaries depend on the server read buffer configuration.",
        "read_bin_6": "TCP Reads=Dist bin 6 count from iperf2 enhanced output. Bin boundaries depend on the server read buffer configuration.",
        "read_bin_7": "TCP Reads=Dist bin 7 count from iperf2 enhanced output. Bin boundaries depend on the server read buffer configuration.",
    }


class IPerfTCPHistogramMetrics:
    def __init__(self, output: dict[str, IPerfServerTCPHistogramOutput]):
        self.data = [
            GaugeMetricFamily(
                "iperf_exporter_tcp_latency_histogram_bin_count",
                "TCP latency histogram bin counts reported by iperf2 trip-times histogram output.",
                labels=TCP_HISTOGRAM_LABEL_NAMES,
            ),
            GaugeMetricFamily(
                "iperf_exporter_tcp_latency_histogram_sample_count",
                "Total TCP latency histogram samples reported by iperf2 for the histogram snapshot.",
                labels=TCP_HISTOGRAM_INFO_LABEL_NAMES,
            ),
            GaugeMetricFamily(
                "iperf_exporter_tcp_latency_histogram_bin_width_seconds",
                "Width of one TCP latency histogram bin in seconds.",
                labels=TCP_HISTOGRAM_INFO_LABEL_NAMES,
            ),
            GaugeMetricFamily(
                "iperf_exporter_tcp_latency_histogram_bucket",
                "Cumulative TCP latency histogram buckets in milliseconds, exported in Prometheus histogram-style form with the le label.",
                labels=TCP_HISTOGRAM_BUCKET_LABEL_NAMES,
            ),
        ]

        for histogram in output.values():
            label_values = [
                histogram.peer_id,
                histogram.local_address,
                histogram.interface_name,
                histogram.local_port,
                histogram.peer_address,
                histogram.peer_port,
                f"{histogram.peer_address}->{histogram.local_address}",
            ]
            info_labels = label_values + [histogram.histogram_name]
            self.data[1].add_metric(info_labels, float(histogram.sample_count))
            self.data[2].add_metric(info_labels, float(histogram.bin_width_seconds))

            cumulative_count = 0
            for bucket_index, count in histogram.bins:
                cumulative_count += count
                upper_bound_ms = (
                    histogram.bin_width_seconds * float(bucket_index) * 1000
                )
                self.data[0].add_metric(
                    info_labels
                    + [
                        _format_float_label(
                            histogram.bin_width_seconds * float(bucket_index)
                        ),
                        _format_float_label(upper_bound_ms),
                    ],
                    float(count),
                )
                self.data[3].add_metric(
                    info_labels + [_format_float_label(upper_bound_ms)],
                    float(cumulative_count),
                )

            self.data[3].add_metric(
                info_labels + ["+Inf"], float(histogram.sample_count)
            )

    def __iter__(self):
        for metric in self.data:
            yield metric


class IPerfProcessMetrics:
    def __init__(self, server, mode: str):
        label_values = [mode, getattr(server, "proto", "unknown")]
        self.data = [
            GaugeMetricFamily(
                "iperf_exporter_iperf_process_up",
                "Whether the supervised iperf process is currently running.",
                labels=PROCESS_LABEL_NAMES,
            ),
            CounterMetricFamily(
                "iperf_exporter_iperf_process_restarts_total",
                "Number of times the supervised iperf process was restarted by the exporter.",
                labels=PROCESS_LABEL_NAMES,
            ),
        ]
        is_running = server.is_running() if hasattr(server, "is_running") else False
        self.data[0].add_metric(label_values, float(is_running))
        self.data[1].add_metric(
            label_values, float(getattr(server, "restart_count", 0))
        )

        last_exit_code = getattr(server, "last_exit_code", None)
        if last_exit_code is not None:
            last_exit_metric = GaugeMetricFamily(
                "iperf_exporter_iperf_process_last_exit_code",
                "Last observed exit code of the supervised iperf process.",
                labels=PROCESS_LABEL_NAMES,
            )
            last_exit_metric.add_metric(label_values, float(last_exit_code))
            self.data.append(last_exit_metric)

    def __iter__(self):
        for metric in self.data:
            yield metric


class IPerfTestInfoMetrics:
    def __init__(
        self,
        server,
        output,
        proto: str,
        context_client_bandwidth: str = "",
        context_client_additional_params: str = "",
        report_interval_seconds: str = "1",
    ):
        runtime_settings = getattr(server, "runtime_settings", None)
        server_len = _label_value_or_empty(getattr(server, "len", ""))
        additional_params = _label_value_or_empty(
            getattr(server, "additional_params", "")
        )
        client_bandwidth = _label_value_or_empty(context_client_bandwidth)
        client_additional_params = _label_value_or_empty(
            context_client_additional_params
        )
        report_interval = _label_value_or_empty(report_interval_seconds)

        if proto == "tcp":
            label_names = TCP_TEST_INFO_LABEL_NAMES
            metric_name = "iperf_exporter_tcp_test_info"
            description = (
                "Static TCP test conditions for the selected stream, derived from "
                "iperf server startup output, connection metadata and optional "
                "configured client hints."
            )
        else:
            label_names = UDP_TEST_INFO_LABEL_NAMES
            metric_name = "iperf_exporter_udp_test_info"
            description = (
                "Static UDP test conditions for the selected stream, derived from "
                "iperf server startup output, connection metadata and optional "
                "configured client hints."
            )

        self.info_metric = GaugeMetricFamily(
            metric_name,
            description,
            labels=label_names,
        )

        for out in output.values():
            common_labels = _label_values(out)
            if proto == "tcp":
                self.info_metric.add_metric(
                    common_labels
                    + [
                        _label_value_or_empty(out.peer_version),
                        _label_value_or_empty(out.trip_times_enabled),
                        report_interval,
                        client_bandwidth,
                        client_additional_params,
                        _label_value_or_empty(out.initial_cwnd_segments),
                        _label_value_or_empty(out.initial_mss_bytes),
                        _label_value_or_empty(out.initial_rtt_microseconds),
                        server_len,
                        _label_value_or_empty(
                            getattr(runtime_settings, "tcp_window_bytes", "")
                        ),
                        _label_value_or_empty(
                            getattr(runtime_settings, "read_buffer_bytes", "")
                        ),
                        _label_value_or_empty(
                            getattr(runtime_settings, "read_dist_bin_width_bytes", "")
                        ),
                        _label_value_or_empty(
                            getattr(runtime_settings, "histogram_bin_width_ms", "")
                        ),
                        _label_value_or_empty(
                            getattr(runtime_settings, "histogram_bin_count", "")
                        ),
                        _label_value_or_empty(
                            getattr(
                                runtime_settings,
                                "congestion_control_default",
                                "",
                            )
                        ),
                        additional_params,
                    ],
                    1.0,
                )
                continue

            self.info_metric.add_metric(
                common_labels
                + [
                    _label_value_or_empty(out.peer_version),
                    _label_value_or_empty(out.trip_times_enabled),
                    report_interval,
                    client_bandwidth,
                    client_additional_params,
                    server_len,
                    _label_value_or_empty(
                        getattr(runtime_settings, "udp_buffer_bytes", "")
                    ),
                    additional_params,
                ],
                1.0,
            )

    def __iter__(self):
        yield self.info_metric


class IPerfSocketQueueMetrics:
    def __init__(
        self,
        output: dict[str, IPerfServerUDPOutput | IPerfServerTCPOutput],
        socket_snapshots: dict[tuple[str, str, str, str], object],
        proto: str,
    ):
        prefix = f"iperf_exporter_{proto}_socket"
        self.data = [
            GaugeMetricFamily(
                f"{prefix}_recv_queue_bytes",
                "Bytes currently queued in the kernel receive queue according to ss.",
                labels=LABEL_NAMES,
            ),
            GaugeMetricFamily(
                f"{prefix}_send_queue_bytes",
                "Bytes currently queued in the kernel send queue according to ss.",
                labels=LABEL_NAMES,
            ),
        ]

        for out in output.values():
            snapshot = _find_socket_snapshot(out, socket_snapshots)
            if snapshot is None:
                continue

            label_values = _label_values(out)
            self.data[0].add_metric(label_values, float(snapshot.recv_queue))
            self.data[1].add_metric(label_values, float(snapshot.send_queue))

    def __iter__(self):
        for metric in self.data:
            yield metric


class IPerfPathTraceMetrics:
    def __init__(
        self,
        output: dict[str, IPerfServerUDPOutput | IPerfServerTCPOutput],
        path_trace_snapshots: dict[tuple[str, str, str, str], PathTraceSnapshot],
        proto: str,
    ):
        prefix = f"iperf_exporter_{proto}_path_trace"
        self.data = [
            GaugeMetricFamily(
                f"{prefix}_success",
                "Whether the last cached tracepath run from the exporter/server namespace reached the peer/client address.",
                labels=PATH_TRACE_LABEL_NAMES,
            ),
            GaugeMetricFamily(
                f"{prefix}_pmtu_bytes",
                "Path MTU reported by tracepath for the route from exporter/server to peer/client.",
                labels=PATH_TRACE_LABEL_NAMES,
            ),
            GaugeMetricFamily(
                f"{prefix}_hops_total",
                "Hop count reported by tracepath for the route from exporter/server to peer/client.",
                labels=PATH_TRACE_LABEL_NAMES,
            ),
            GaugeMetricFamily(
                f"{prefix}_hop_info",
                "Gauge with constant value 1. Labels enumerate each hop seen in the last cached tracepath snapshot.",
                labels=PATH_TRACE_HOP_LABEL_NAMES,
            ),
        ]

        for out in output.values():
            snapshot = path_trace_snapshots.get(_socket_key(out))
            if snapshot is None:
                continue

            label_values = _label_values(out) + [snapshot.trace_direction]
            self.data[0].add_metric(label_values, float(snapshot.success))
            if snapshot.pmtu_bytes is not None:
                self.data[1].add_metric(label_values, float(snapshot.pmtu_bytes))
            if snapshot.hops_total is not None:
                self.data[2].add_metric(label_values, float(snapshot.hops_total))

            for hop in snapshot.hops:
                self.data[3].add_metric(
                    label_values
                    + [
                        str(hop.hop_index),
                        hop.hop_address,
                        hop.hop_summary,
                    ],
                    1.0,
                )

    def __iter__(self):
        for metric in self.data:
            yield metric


class IPerfTCPSocketMetrics:
    metric_descriptions = {
        "rto_milliseconds": "TCP retransmission timeout reported by ss, in milliseconds.",
        "rtt_milliseconds": "TCP smoothed round-trip time reported by ss, in milliseconds.",
        "rttvar_milliseconds": "TCP RTT variation reported by ss, in milliseconds.",
        "ato_milliseconds": "TCP delayed ACK timeout reported by ss, in milliseconds.",
        "mss_bytes": "TCP MSS reported by ss, in bytes.",
        "pmtu_bytes": "TCP path MTU reported by ss, in bytes.",
        "rcvmss_bytes": "TCP receive MSS reported by ss, in bytes.",
        "advmss_bytes": "TCP advertised MSS reported by ss, in bytes.",
        "cwnd_segments": "TCP congestion window reported by ss, in segments.",
        "bytes_sent": "Total TCP bytes sent reported by ss for the socket.",
        "bytes_acked": "Total TCP bytes acknowledged reported by ss for the socket.",
        "bytes_received": "Total TCP bytes received reported by ss for the socket.",
        "segs_out": "Total TCP segments sent reported by ss for the socket.",
        "segs_in": "Total TCP segments received reported by ss for the socket.",
        "data_segs_out": "Total TCP data segments sent reported by ss for the socket.",
        "data_segs_in": "Total TCP data segments received reported by ss for the socket.",
        "send_rate_bps": "TCP send rate reported by ss, in bits per second.",
        "pacing_rate_bps": "TCP pacing rate reported by ss, in bits per second.",
        "delivery_rate_bps": "TCP delivery rate reported by ss, in bits per second.",
        "delivered": "Total delivered TCP packets reported by ss for the socket.",
        "rcv_rtt_milliseconds": "Receiver-side TCP RTT reported by ss, in milliseconds.",
        "rcv_space_bytes": "TCP receive space reported by ss, in bytes.",
        "rcv_ssthresh_bytes": "TCP receive slow-start threshold reported by ss, in bytes.",
        "min_rtt_milliseconds": "Minimum TCP RTT reported by ss, in milliseconds.",
        "lastsnd_milliseconds": "Milliseconds since the last TCP send according to ss.",
        "lastrcv_milliseconds": "Milliseconds since the last TCP receive according to ss.",
        "lastack_milliseconds": "Milliseconds since the last TCP ACK according to ss.",
        "snd_wnd_bytes": "TCP sender window reported by ss, in bytes.",
        "rcv_wnd_bytes": "TCP receiver window reported by ss, in bytes.",
        "send_wscale": "TCP send window scale reported by ss.",
        "rcv_wscale": "TCP receive window scale reported by ss.",
        "app_limited": "Whether ss reports the TCP socket as application-limited.",
    }

    def __init__(
        self,
        output: dict[str, IPerfServerTCPOutput],
        socket_snapshots: dict[tuple[str, str, str, str], object],
    ):
        self.data = {
            metric_name: GaugeMetricFamily(
                f"iperf_exporter_tcp_socket_{metric_name}",
                description,
                labels=LABEL_NAMES,
            )
            for metric_name, description in self.metric_descriptions.items()
        }
        self.info_metric = GaugeMetricFamily(
            "iperf_exporter_tcp_socket_info",
            "Stable TCP socket conditions from ss, including congestion control, MSS, MTU and negotiated window scaling.",
            labels=TCP_SOCKET_INFO_LABEL_NAMES,
        )

        for out in output.values():
            snapshot = _find_socket_snapshot(out, socket_snapshots)
            if snapshot is None or not isinstance(snapshot, TCPSocketSnapshot):
                continue

            label_values = _label_values(out)
            self.data["app_limited"].add_metric(
                label_values, float(snapshot.app_limited)
            )
            self.info_metric.add_metric(
                label_values
                + [
                    snapshot.congestion_algorithm or "unknown",
                    snapshot.state or "",
                    _label_value_or_empty(snapshot.metrics.get("mss_bytes")),
                    _label_value_or_empty(snapshot.metrics.get("pmtu_bytes")),
                    _label_value_or_empty(snapshot.metrics.get("rcvmss_bytes")),
                    _label_value_or_empty(snapshot.metrics.get("advmss_bytes")),
                    _label_value_or_empty(snapshot.metrics.get("send_wscale")),
                    _label_value_or_empty(snapshot.metrics.get("rcv_wscale")),
                ],
                1.0,
            )

            for metric_name, metric_value in snapshot.metrics.items():
                if metric_name not in self.data:
                    continue
                self.data[metric_name].add_metric(label_values, float(metric_value))

    def __iter__(self):
        yield self.info_metric
        for metric in self.data.values():
            yield metric


class IPerfCollector:
    """
    The custom prometheus collector which fetches metrics data from iperf output parse them and
    store in prometheus format. Instance of the class is used by a prometheus client registry.

    https://github.com/prometheus/client_python#custom-collectors
    """

    def __init__(
        self,
        port,
        proto,
        len,
        metric_ttl,
        additional_params="",
        context_client_bandwidth="",
        context_client_additional_params="",
        path_trace_ttl=300,
        path_trace_max_hops=16,
        path_trace_timeout=10,
        server_cls=IPerfServer,
        socket_stats_cls=SocketStatsCollector,
        path_trace_cls=PathTraceCollector,
    ):
        self.proto = proto
        self.context_client_bandwidth = context_client_bandwidth
        self.context_client_additional_params = context_client_additional_params
        self.server = server_cls(
            port,
            proto,
            len,
            metric_ttl,
            additional_params=additional_params,
        )
        self.server.run()
        self.socket_stats = socket_stats_cls(port, proto)
        self.path_trace = path_trace_cls(
            proto=proto,
            ttl=path_trace_ttl,
            max_hops=path_trace_max_hops,
            timeout=path_trace_timeout,
        )
        if self.proto == "udp":
            self.metrics_cls = IPerfUDPMetrics
        elif self.proto == "tcp":
            self.metrics_cls = IPerfTCPMetrics
        else:
            raise ValueError(f"Unsupported iperf protocol: {self.proto}")

    def collect(self):
        if hasattr(self.server, "ensure_running"):
            self.server.ensure_running()
        self.server.read_output()
        log.debug(self.server.output)
        for metric in IPerfProcessMetrics(self.server, mode="server"):
            yield metric
        for metric in IPerfTestInfoMetrics(
            self.server,
            self.server.output,
            self.proto,
            context_client_bandwidth=self.context_client_bandwidth,
            context_client_additional_params=self.context_client_additional_params,
        ):
            yield metric
        for metric in self.metrics_cls(self.server.output):
            yield metric
        path_trace_snapshots = self.path_trace.collect(self.server.output)
        for metric in IPerfPathTraceMetrics(
            self.server.output,
            path_trace_snapshots,
            self.proto,
        ):
            yield metric
        socket_snapshots = self.socket_stats.collect()
        for metric in IPerfSocketQueueMetrics(
            self.server.output,
            socket_snapshots,
            self.proto,
        ):
            yield metric
        if self.proto == "tcp":
            for metric in IPerfTCPSocketMetrics(
                self.server.output,
                socket_snapshots,
            ):
                yield metric
            for metric in IPerfTCPHistogramMetrics(
                getattr(self.server, "tcp_histograms", {})
            ):
                yield metric

    def stop(self):
        self.server.stop()
