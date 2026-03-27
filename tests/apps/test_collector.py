from unittest import TestCase
from types import SimpleNamespace

from prometheus_client.core import CollectorRegistry

from iperf_exporter.collector import IPerfCollector
from iperf_exporter.iperf import IPerfServer
from iperf_exporter.path_trace import PathTraceHop, PathTraceSnapshot
from iperf_exporter.socket_stats import SocketSnapshot, TCPSocketSnapshot

EMPTY_CONTEXT_LABELS = {
    "measurement_id": "",
    "profile_ref": "",
    "session_id": "",
    "execution_mode": "",
    "direction": "",
    "network_mode": "",
    "src_node": "",
    "dst_node": "",
    "src_cluster": "",
    "dst_cluster": "",
}

K8S_CONTEXT_LABELS = {
    "measurement_id": "tcp-demo",
    "profile_ref": "tcp-quality",
    "session_id": "tcp-demo-service-sourcetodestination",
    "execution_mode": "continuous",
    "direction": "sourceToDestination",
    "network_mode": "service",
    "src_node": "worker-a",
    "dst_node": "worker-b",
    "src_cluster": "local",
    "dst_cluster": "local",
}


class StdOutProcess:
    def __init__(self, file):
        self.stdout = open(file, "r")

    def close(self):
        self.stdout.close()


class FakeServer:
    def __init__(
        self,
        output,
        tcp_histograms=None,
        proto="udp",
        running=True,
        restart_count=0,
        last_exit_code=None,
        runtime_settings=None,
        len_value="",
        additional_params="",
    ):
        self.output = output
        self.tcp_histograms = tcp_histograms or {}
        self.proto = proto
        self.running = running
        self.restart_count = restart_count
        self.last_exit_code = last_exit_code
        self.runtime_settings = runtime_settings or SimpleNamespace()
        self.len = len_value
        self.additional_params = additional_params
        self.run_called = False
        self.ensure_running_called = False
        self.read_output_called = False
        self.stop_called = False

    def run(self):
        self.run_called = True

    def ensure_running(self):
        self.ensure_running_called = True

    def is_running(self):
        return self.running

    def read_output(self):
        self.read_output_called = True

    def stop(self):
        self.stop_called = True


class FakeSocketStatsCollector:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.collect_called = False

    def collect(self):
        self.collect_called = True
        return self.snapshots


class FakePathTraceCollector:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.collect_called = False

    def collect(self, output):
        self.collect_called = True
        return self.snapshots


class TestIPerfCollector(TestCase):
    def setUp(self):
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            process.close()

    def new_process(self, path):
        process = StdOutProcess(path)
        self.processes.append(process)
        return process

    def test_collect_udp_metrics(self):
        server = IPerfServer("5001", "udp", "1280", 1, 604800)
        server._process = self.new_process("tests/apps/data/new_client.log")
        server.read_output()
        fake_server = FakeServer(
            server.output,
            proto="udp",
            runtime_settings=server.runtime_settings,
            len_value="1280",
        )
        fake_socket_stats = FakeSocketStatsCollector(
            {
                ("127.0.0.1", "5001", "127.0.0.2", "52370"): SocketSnapshot(
                    local_address="127.0.0.1",
                    local_port="5001",
                    peer_address="127.0.0.2",
                    peer_port="52370",
                    recv_queue=0.0,
                    send_queue=32.0,
                )
            }
        )
        fake_path_trace = FakePathTraceCollector(
            {
                ("127.0.0.1", "5001", "127.0.0.2", "52370"): PathTraceSnapshot(
                    local_address="127.0.0.1",
                    local_port="5001",
                    peer_address="127.0.0.2",
                    peer_port="52370",
                    success=True,
                    pmtu_bytes=1500.0,
                    hops_total=1.0,
                    hops=[
                        PathTraceHop(
                            hop_index=1,
                            hop_address="127.0.0.2",
                            hop_summary="0.031ms reached",
                        )
                    ],
                )
            }
        )
        registry = CollectorRegistry(auto_describe=True)

        collector = IPerfCollector(
            port=5001,
            proto="udp",
            len="1280",
            interval=1,
            metric_ttl=604800,
            server_cls=lambda *args, **kwargs: fake_server,
            socket_stats_cls=lambda *args, **kwargs: fake_socket_stats,
            path_trace_cls=lambda *args, **kwargs: fake_path_trace,
        )
        registry.register(collector)

        labels = {
            "peer_id": "3",
            "local_address": "127.0.0.1",
            "interface_name": "eth0",
            "local_port": "5001",
            "peer_address": "127.0.0.2",
            "peer_port": "52370",
            "connection_pair": "127.0.0.2->127.0.0.1",
            **EMPTY_CONTEXT_LABELS,
        }

        self.assertTrue(fake_server.run_called)
        self.assertEqual(
            20400.0,
            registry.get_sample_value("iperf_exporter_udp_transfer", labels=labels),
        )
        self.assertEqual(
            163200.0,
            registry.get_sample_value("iperf_exporter_udp_bandwidth", labels=labels),
        )
        self.assertEqual(
            10.98,
            registry.get_sample_value("iperf_exporter_udp_netpwr", labels=labels),
        )
        self.assertEqual(
            1.0,
            registry.get_sample_value(
                "iperf_exporter_iperf_process_up",
                labels={"mode": "server", "proto": "udp", **EMPTY_CONTEXT_LABELS},
            ),
        )
        self.assertEqual(
            0.0,
            registry.get_sample_value(
                "iperf_exporter_iperf_process_restarts_total",
                labels={"mode": "server", "proto": "udp", **EMPTY_CONTEXT_LABELS},
            ),
        )
        self.assertEqual(
            0.0,
            registry.get_sample_value(
                "iperf_exporter_udp_socket_recv_queue_bytes",
                labels=labels,
            ),
        )
        self.assertEqual(
            32.0,
            registry.get_sample_value(
                "iperf_exporter_udp_socket_send_queue_bytes",
                labels=labels,
            ),
        )
        self.assertEqual(
            1.0,
            registry.get_sample_value(
                "iperf_exporter_udp_test_info",
                labels={
                    **labels,
                    "peer_version": "",
                    "trip_times_enabled": "false",
                    "report_interval_seconds": "1",
                    "client_bandwidth_limit": "",
                    "client_additional_params": "",
                    "server_len_bytes": "1280",
                    "server_udp_buffer_bytes": "212992",
                    "server_additional_params": "",
                },
            ),
        )
        self.assertEqual(
            1500.0,
            registry.get_sample_value(
                "iperf_exporter_udp_path_trace_pmtu_bytes",
                labels={**labels, "trace_direction": "server_to_client"},
            ),
        )
        self.assertEqual(
            1.0,
            registry.get_sample_value(
                "iperf_exporter_udp_path_trace_hop_info",
                labels={
                    **labels,
                    "trace_direction": "server_to_client",
                    "hop_index": "1",
                    "hop_address": "127.0.0.2",
                    "hop_summary": "0.031ms reached",
                },
            ),
        )
        self.assertTrue(fake_server.ensure_running_called)
        self.assertTrue(fake_server.read_output_called)
        self.assertTrue(fake_socket_stats.collect_called)
        self.assertTrue(fake_path_trace.collect_called)

    def test_collect_tcp_metrics(self):
        server = IPerfServer("5001", "tcp", "8192", 1, 604800)
        server._process = self.new_process("tests/apps/data/new_client_tcp.log")
        server.read_output()
        fake_server = FakeServer(
            server.output,
            proto="tcp",
            runtime_settings=server.runtime_settings,
            len_value="8192",
        )
        fake_socket_stats = FakeSocketStatsCollector(
            {
                ("45.33.58.123", "5001", "45.56.85.133", "49960"): TCPSocketSnapshot(
                    local_address="45.33.58.123",
                    local_port="5001",
                    peer_address="45.56.85.133",
                    peer_port="49960",
                    recv_queue=64.0,
                    send_queue=16.0,
                    state="ESTAB",
                    congestion_algorithm="cubic",
                    app_limited=True,
                    metrics={
                        "rtt_milliseconds": 0.024,
                        "rttvar_milliseconds": 0.014,
                        "rto_milliseconds": 201.0,
                        "cwnd_segments": 10.0,
                        "mss_bytes": 1448.0,
                        "pmtu_bytes": 1500.0,
                        "rcvmss_bytes": 1448.0,
                        "advmss_bytes": 1448.0,
                        "bytes_received": 249430080.0,
                        "send_rate_bps": 4_826_666_667.0,
                        "pacing_rate_bps": 9_313_768_840.0,
                        "delivery_rate_bps": 3_861_333_328.0,
                        "send_wscale": 10.0,
                        "rcv_wscale": 10.0,
                        "snd_wnd_bytes": 64512.0,
                        "rcv_wnd_bytes": 161792.0,
                    },
                )
            }
        )
        fake_path_trace = FakePathTraceCollector(
            {
                ("45.33.58.123", "5001", "45.56.85.133", "49960"): PathTraceSnapshot(
                    local_address="45.33.58.123",
                    local_port="5001",
                    peer_address="45.56.85.133",
                    peer_port="49960",
                    success=True,
                    pmtu_bytes=1500.0,
                    hops_total=2.0,
                    hops=[
                        PathTraceHop(
                            hop_index=1,
                            hop_address="10.0.0.1",
                            hop_summary="0.102ms",
                        ),
                        PathTraceHop(
                            hop_index=2,
                            hop_address="45.56.85.133",
                            hop_summary="0.244ms reached",
                        ),
                    ],
                )
            }
        )
        registry = CollectorRegistry(auto_describe=True)

        collector = IPerfCollector(
            port=5001,
            proto="tcp",
            len="8192",
            interval=1,
            metric_ttl=604800,
            context_client_bandwidth="100M",
            context_client_additional_params="--trip-times",
            context_labels=K8S_CONTEXT_LABELS,
            server_cls=lambda *args, **kwargs: fake_server,
            socket_stats_cls=lambda *args, **kwargs: fake_socket_stats,
            path_trace_cls=lambda *args, **kwargs: fake_path_trace,
        )
        registry.register(collector)

        labels = {
            "peer_id": "4",
            "local_address": "45.33.58.123",
            "interface_name": "eth0",
            "local_port": "5001",
            "peer_address": "45.56.85.133",
            "peer_port": "49960",
            "connection_pair": "45.56.85.133->45.33.58.123",
            **K8S_CONTEXT_LABELS,
        }

        self.assertEqual(
            124000000.0,
            registry.get_sample_value("iperf_exporter_tcp_transfer", labels=labels),
        )
        self.assertEqual(
            1040000000.0,
            registry.get_sample_value("iperf_exporter_tcp_bandwidth", labels=labels),
        )
        self.assertEqual(
            22249.0,
            registry.get_sample_value("iperf_exporter_tcp_reads", labels=labels),
        )
        self.assertEqual(
            798.0,
            registry.get_sample_value("iperf_exporter_tcp_read_bin_0", labels=labels),
        )
        self.assertEqual(
            11669.0,
            registry.get_sample_value("iperf_exporter_tcp_read_bin_7", labels=labels),
        )
        self.assertEqual(
            64.0,
            registry.get_sample_value(
                "iperf_exporter_tcp_socket_recv_queue_bytes",
                labels=labels,
            ),
        )
        self.assertEqual(
            16.0,
            registry.get_sample_value(
                "iperf_exporter_tcp_socket_send_queue_bytes",
                labels=labels,
            ),
        )
        self.assertEqual(
            0.024,
            registry.get_sample_value(
                "iperf_exporter_tcp_socket_rtt_milliseconds",
                labels=labels,
            ),
        )
        self.assertEqual(
            10.0,
            registry.get_sample_value(
                "iperf_exporter_tcp_socket_cwnd_segments",
                labels=labels,
            ),
        )
        self.assertEqual(
            1.0,
            registry.get_sample_value(
                "iperf_exporter_tcp_socket_app_limited",
                labels=labels,
            ),
        )
        self.assertEqual(
            1.0,
            registry.get_sample_value(
                "iperf_exporter_tcp_socket_info",
                labels={
                    **labels,
                    "congestion_algorithm": "cubic",
                    "socket_state": "ESTAB",
                    "mss_bytes": "1448",
                    "pmtu_bytes": "1500",
                    "rcvmss_bytes": "1448",
                    "advmss_bytes": "1448",
                    "send_wscale": "10",
                    "rcv_wscale": "10",
                },
            ),
        )
        self.assertEqual(
            1.0,
            registry.get_sample_value(
                "iperf_exporter_tcp_test_info",
                labels={
                    **labels,
                    "peer_version": "2.2.1-rc",
                    "trip_times_enabled": "false",
                    "report_interval_seconds": "1",
                    "client_bandwidth_limit": "100M",
                    "client_additional_params": "--trip-times",
                    "initial_cwnd_segments": "",
                    "initial_mss_bytes": "",
                    "initial_rtt_microseconds": "",
                    "server_len_bytes": "8192",
                    "server_window_bytes": "131072",
                    "server_read_buffer_bytes": "8192",
                    "server_read_dist_bin_width_bytes": "1024",
                    "server_histogram_bin_width_ms": "",
                    "server_histogram_bin_count": "",
                    "server_congestion_control_default": "cubic",
                    "server_additional_params": "",
                },
            ),
        )
        self.assertEqual(
            2.0,
            registry.get_sample_value(
                "iperf_exporter_tcp_path_trace_hops_total",
                labels={**labels, "trace_direction": "server_to_client"},
            ),
        )
        self.assertEqual(
            1.0,
            registry.get_sample_value(
                "iperf_exporter_tcp_path_trace_hop_info",
                labels={
                    **labels,
                    "trace_direction": "server_to_client",
                    "hop_index": "2",
                    "hop_address": "45.56.85.133",
                    "hop_summary": "0.244ms reached",
                },
            ),
        )
        self.assertTrue(fake_server.ensure_running_called)
        self.assertTrue(fake_socket_stats.collect_called)
        self.assertTrue(fake_path_trace.collect_called)

    def test_collect_tcp_trip_times_and_histogram_metrics(self):
        server = IPerfServer("6011", "tcp", "8192", 1, 604800)
        server._process = self.new_process(
            "tests/apps/data/new_client_tcp_trip_times.log"
        )
        server.read_output()
        fake_server = FakeServer(
            server.output,
            tcp_histograms=server.tcp_histograms,
            proto="tcp",
            runtime_settings=server.runtime_settings,
            len_value="8192",
        )
        registry = CollectorRegistry(auto_describe=True)

        collector = IPerfCollector(
            port=6011,
            proto="tcp",
            len="8192",
            interval=1,
            metric_ttl=604800,
            server_cls=lambda *args, **kwargs: fake_server,
            socket_stats_cls=lambda *args, **kwargs: FakeSocketStatsCollector({}),
            path_trace_cls=lambda *args, **kwargs: FakePathTraceCollector({}),
        )
        registry.register(collector)

        labels = {
            "peer_id": "1",
            "local_address": "127.0.0.1",
            "interface_name": "lo0",
            "local_port": "6011",
            "peer_address": "127.0.0.1",
            "peer_port": "65031",
            "connection_pair": "127.0.0.1->127.0.0.1",
            **EMPTY_CONTEXT_LABELS,
        }

        self.assertEqual(
            0.858,
            registry.get_sample_value(
                "iperf_exporter_tcp_burst_latency_avg", labels=labels
            ),
        )
        self.assertEqual(
            7707033.6,
            registry.get_sample_value(
                "iperf_exporter_tcp_inprogress_bytes", labels=labels
            ),
        )
        self.assertEqual(
            627867.0,
            registry.get_sample_value("iperf_exporter_tcp_read_bin_7", labels=labels),
        )
        histogram_labels = {
            **labels,
            "histogram_name": "x8(f)",
        }
        self.assertEqual(
            41858.0,
            registry.get_sample_value(
                "iperf_exporter_tcp_latency_histogram_sample_count",
                labels=histogram_labels,
            ),
        )
        self.assertEqual(
            0.0001,
            registry.get_sample_value(
                "iperf_exporter_tcp_latency_histogram_bin_width_seconds",
                labels=histogram_labels,
            ),
        )
        self.assertEqual(
            11.0,
            registry.get_sample_value(
                "iperf_exporter_tcp_latency_histogram_bin_count",
                labels={
                    **histogram_labels,
                    "upper_bound_seconds": "0.002",
                    "upper_bound_ms": "2",
                },
            ),
        )
        self.assertEqual(
            37.0,
            registry.get_sample_value(
                "iperf_exporter_tcp_latency_histogram_bucket",
                labels={
                    **histogram_labels,
                    "le": "0.1",
                },
            ),
        )
        self.assertEqual(
            41858.0,
            registry.get_sample_value(
                "iperf_exporter_tcp_latency_histogram_bucket",
                labels={
                    **histogram_labels,
                    "le": "+Inf",
                },
            ),
        )
        self.assertEqual(
            1.0,
            registry.get_sample_value(
                "iperf_exporter_tcp_test_info",
                labels={
                    **labels,
                    "peer_version": "2.1.9",
                    "trip_times_enabled": "true",
                    "report_interval_seconds": "1",
                    "client_bandwidth_limit": "",
                    "client_additional_params": "",
                    "initial_cwnd_segments": "159",
                    "initial_mss_bytes": "16332",
                    "initial_rtt_microseconds": "1000",
                    "server_len_bytes": "8192",
                    "server_window_bytes": "131072",
                    "server_read_buffer_bytes": "8192",
                    "server_read_dist_bin_width_bytes": "1024",
                    "server_histogram_bin_width_ms": "0.100",
                    "server_histogram_bin_count": "20",
                    "server_congestion_control_default": "",
                    "server_additional_params": "",
                },
            ),
        )

    def test_collect_process_health_metrics(self):
        fake_server = FakeServer(
            {},
            proto="tcp",
            running=True,
            restart_count=2,
            last_exit_code=1,
        )
        registry = CollectorRegistry(auto_describe=True)

        collector = IPerfCollector(
            port=5001,
            proto="tcp",
            len="8192",
            interval=1,
            metric_ttl=604800,
            server_cls=lambda *args, **kwargs: fake_server,
            socket_stats_cls=lambda *args, **kwargs: FakeSocketStatsCollector({}),
            path_trace_cls=lambda *args, **kwargs: FakePathTraceCollector({}),
        )
        registry.register(collector)

        self.assertEqual(
            1.0,
            registry.get_sample_value(
                "iperf_exporter_iperf_process_up",
                labels={"mode": "server", "proto": "tcp", **EMPTY_CONTEXT_LABELS},
            ),
        )
        self.assertEqual(
            2.0,
            registry.get_sample_value(
                "iperf_exporter_iperf_process_restarts_total",
                labels={"mode": "server", "proto": "tcp", **EMPTY_CONTEXT_LABELS},
            ),
        )
        self.assertEqual(
            1.0,
            registry.get_sample_value(
                "iperf_exporter_iperf_process_last_exit_code",
                labels={"mode": "server", "proto": "tcp", **EMPTY_CONTEXT_LABELS},
            ),
        )

    def test_collector_stop(self):
        fake_server = FakeServer({})
        collector = IPerfCollector(
            port=5001,
            proto="udp",
            len="1280",
            interval=1,
            metric_ttl=604800,
            server_cls=lambda *args, **kwargs: fake_server,
            socket_stats_cls=lambda *args, **kwargs: FakeSocketStatsCollector({}),
            path_trace_cls=lambda *args, **kwargs: FakePathTraceCollector({}),
        )

        collector.stop()

        self.assertTrue(fake_server.stop_called)
