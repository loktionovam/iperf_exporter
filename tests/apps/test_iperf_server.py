from time import sleep
from unittest import TestCase

from iperf_exporter.iperf import IPerfServer


class StdOutProcess:
    def __init__(self, file):
        self.stdout = open(file, "r")

    def close(self):
        self.stdout.close()


class EmptyStream:
    def __init__(self):
        self.closed = False

    def readlines(self):
        return []

    def close(self):
        self.closed = True


class PollProcess:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code
        self.stdout = EmptyStream()
        self.stderr = EmptyStream()
        self.terminated = False

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True
        self.exit_code = 0


class TestIPerfServer(TestCase):
    def setUp(self) -> None:
        self.processes = []

    def tearDown(self) -> None:
        for process in self.processes:
            process.close()

    def new_process(self, path):
        process = StdOutProcess(path)
        self.processes.append(process)
        return process

    def test_iperf_server_new_udp_client(self):
        server = IPerfServer("5001", "udp", "1200", 604800)
        server._process = self.new_process("tests/apps/data/new_client.log")

        server.read_output()

        self.assertEqual(getattr(server.output["3"], "peer_id"), "3")
        self.assertEqual(getattr(server.output["3"], "local_address"), "127.0.0.1")
        self.assertEqual(getattr(server.output["3"], "interface_name"), "eth0")
        self.assertEqual(getattr(server.output["3"], "local_port"), "5001")
        self.assertEqual(getattr(server.output["3"], "peer_address"), "127.0.0.2")
        self.assertEqual(getattr(server.output["3"], "peer_port"), "52370")
        self.assertEqual(getattr(server.output["3"], "interval_start"), "5515.00")
        self.assertEqual(getattr(server.output["3"], "interval_end"), "5516.00")
        self.assertEqual(getattr(server.output["3"], "transfer"), "20400")
        self.assertEqual(getattr(server.output["3"], "bandwidth"), "163200")
        self.assertEqual(getattr(server.output["3"], "jitter"), "0.131")
        self.assertEqual(getattr(server.output["3"], "lost"), "0")
        self.assertEqual(getattr(server.output["3"], "total"), "17")
        self.assertEqual(getattr(server.output["3"], "lost_percentage"), "0")
        self.assertEqual(getattr(server.output["3"], "latency_avg"), "1.857")
        self.assertEqual(getattr(server.output["3"], "latency_min"), "1.769")
        self.assertEqual(getattr(server.output["3"], "latency_max"), "1.911")
        self.assertEqual(getattr(server.output["3"], "latency_stdev"), "0.033")
        self.assertEqual(getattr(server.output["3"], "pps"), "17")
        self.assertEqual(getattr(server.output["3"], "netpwr"), "10.98")
        self.assertEqual(server.runtime_settings.listen_port, "5001")
        self.assertEqual(server.runtime_settings.datagram_size_bytes, "1280")
        self.assertEqual(server.runtime_settings.udp_buffer_bytes, "212992")

    def test_iperf_server_udp_triptime_variant_metrics(self):
        server = IPerfServer("5001", "udp", "1200", 604800)
        server._raw_stdout = (
            "[  3] local 127.0.0.1%eth0 port 5001 connected with 127.0.0.2 port 52370"
        )
        server.parse_output()
        server._raw_stdout = (
            "[  3] 5516.00-5517.00 sec  20400 Bytes  163200 bits/sec   0.086 ms "
            "0/17 (0%) 7.049/7.183/6.845/0.085 ms 17 pps 17/2.13 MByte 1/0/0 2.894221"
        )

        server.parse_output()

        self.assertEqual(getattr(server.output["3"], "interval_start"), "5516.00")
        self.assertEqual(getattr(server.output["3"], "interval_end"), "5517.00")
        self.assertEqual(getattr(server.output["3"], "latency_avg"), "7.049")
        self.assertEqual(getattr(server.output["3"], "latency_stdev"), "0.085")
        self.assertEqual(getattr(server.output["3"], "pps"), "17")
        self.assertEqual(getattr(server.output["3"], "netpwr"), "2.894221")

    def test_iperf_server_new_tcp_client(self):
        server = IPerfServer("5001", "tcp", "8192", 604800)
        server._process = self.new_process("tests/apps/data/new_client_tcp.log")

        server.read_output()

        self.assertEqual(getattr(server.output["4"], "peer_id"), "4")
        self.assertEqual(getattr(server.output["4"], "local_address"), "45.33.58.123")
        self.assertEqual(getattr(server.output["4"], "interface_name"), "eth0")
        self.assertEqual(getattr(server.output["4"], "local_port"), "5001")
        self.assertEqual(getattr(server.output["4"], "peer_address"), "45.56.85.133")
        self.assertEqual(getattr(server.output["4"], "peer_port"), "49960")
        self.assertEqual(getattr(server.output["4"], "interval_start"), "0.00")
        self.assertEqual(getattr(server.output["4"], "interval_end"), "1.00")
        self.assertEqual(getattr(server.output["4"], "transfer"), "124000000")
        self.assertEqual(getattr(server.output["4"], "bandwidth"), "1040000000")
        self.assertEqual(getattr(server.output["4"], "reads"), "22249")
        self.assertEqual(getattr(server.output["4"], "read_bin_0"), "798")
        self.assertEqual(getattr(server.output["4"], "read_bin_7"), "11669")
        self.assertEqual(getattr(server.output["4"], "peer_version"), "2.2.1-rc")
        self.assertEqual(getattr(server.output["4"], "trip_times_enabled"), "false")
        self.assertEqual(server.runtime_settings.read_buffer_bytes, "8192")
        self.assertEqual(server.runtime_settings.read_dist_bin_width_bytes, "1024")
        self.assertEqual(server.runtime_settings.tcp_window_bytes, "131072")
        self.assertEqual(server.runtime_settings.congestion_control_default, "cubic")

    def test_iperf_server_tcp_trip_times_metrics(self):
        server = IPerfServer("6011", "tcp", "8192", 604800)
        server._process = self.new_process(
            "tests/apps/data/new_client_tcp_trip_times.log"
        )

        server.read_output()

        self.assertEqual(getattr(server.output["1"], "peer_id"), "1")
        self.assertEqual(getattr(server.output["1"], "local_address"), "127.0.0.1")
        self.assertEqual(getattr(server.output["1"], "interface_name"), "lo0")
        self.assertEqual(getattr(server.output["1"], "local_port"), "6011")
        self.assertEqual(getattr(server.output["1"], "peer_address"), "127.0.0.1")
        self.assertEqual(getattr(server.output["1"], "peer_port"), "65031")
        self.assertEqual(getattr(server.output["1"], "interval_start"), "0.00")
        self.assertEqual(getattr(server.output["1"], "interval_end"), "2.00")
        self.assertEqual(getattr(server.output["1"], "transfer"), "5486411856")
        self.assertEqual(getattr(server.output["1"], "bandwidth"), "21940085612")
        self.assertEqual(getattr(server.output["1"], "reads"), "678097")
        self.assertEqual(getattr(server.output["1"], "burst_latency_avg"), "0.858")
        self.assertEqual(getattr(server.output["1"], "burst_latency_min"), "0.034")
        self.assertEqual(getattr(server.output["1"], "burst_latency_max"), "40.291")
        self.assertEqual(getattr(server.output["1"], "burst_latency_stdev"), "1.222")
        self.assertEqual(getattr(server.output["1"], "burst_count"), "41858")
        self.assertEqual(getattr(server.output["1"], "burst_size"), "131072")
        self.assertEqual(getattr(server.output["1"], "inprogress_bytes"), "7707033.6")
        self.assertEqual(getattr(server.output["1"], "netpwr"), "3195152")
        self.assertEqual(getattr(server.output["1"], "read_bin_0"), "8369")
        self.assertEqual(getattr(server.output["1"], "read_bin_6"), "3")
        self.assertEqual(getattr(server.output["1"], "read_bin_7"), "627867")
        self.assertEqual(getattr(server.output["1"], "peer_version"), "2.1.9")
        self.assertEqual(getattr(server.output["1"], "trip_times_enabled"), "true")
        self.assertEqual(getattr(server.output["1"], "initial_cwnd_segments"), "159")
        self.assertEqual(getattr(server.output["1"], "initial_mss_bytes"), "16332")
        self.assertEqual(
            getattr(server.output["1"], "initial_rtt_microseconds"), "1000"
        )
        self.assertIn("1:x8(f)", server.tcp_histograms)
        self.assertEqual(server.tcp_histograms["1:x8(f)"].histogram_name, "x8(f)")
        self.assertEqual(server.tcp_histograms["1:x8(f)"].sample_count, 41858)
        self.assertEqual(server.tcp_histograms["1:x8(f)"].bin_width_seconds, 0.0001)
        self.assertEqual(server.tcp_histograms["1:x8(f)"].bins[0], (1, 37))
        self.assertEqual(server.tcp_histograms["1:x8(f)"].bins[-1], (20, 11))
        self.assertEqual(server.runtime_settings.histogram_bin_width_ms, "0.100")
        self.assertEqual(server.runtime_settings.histogram_bin_count, "20")

    def test_iperf_server_ignores_suppressed_udp_line_without_resetting_metrics(self):
        server = IPerfServer("5001", "udp", "1200", 604800)
        server._process = self.new_process("tests/apps/data/new_client.log")
        server.read_output()

        interval_end = getattr(server.output["3"], "interval_end")
        current_metric_ttl = server.output["3"].current_metric_ttl
        server._raw_stdout = (
            "[  3] 5710.00-5711.00 sec  0.000 Bytes  0.000 bits/sec   0.000 ms "
            "0/0 (0%) -/-/-/- ms 0 pps"
        )

        server.parse_output()

        self.assertEqual(getattr(server.output["3"], "interval_end"), interval_end)
        self.assertEqual(server.output["3"].current_metric_ttl, current_metric_ttl)

    def test_iperf_server_dead_client_not_reach_limit(self):
        server = None
        try:
            server = IPerfServer(
                "5001",
                "udp",
                "1200",
                3,
                cleanup_startup_delay=0,
                cleanup_interval=0.05,
            )
            server._process = self.new_process("tests/apps/data/new_client.log")
            server.run()

            server.read_output()
            self.assertTrue("3" in server.output)

            server._process = self.new_process("tests/apps/data/dead_client.log")
            server.read_output()
            sleep(0.08)
            self.assertTrue("3" in server.output)
        finally:
            if server is not None:
                server.stop()

    def test_iperf_server_dead_client_reach_limit(self):
        server = None
        try:
            server = IPerfServer(
                "5001",
                "udp",
                "1200",
                3,
                cleanup_startup_delay=0,
                cleanup_interval=0.05,
            )
            server._process = self.new_process("tests/apps/data/new_client.log")
            server.run()

            server.read_output()
            self.assertTrue("3" in server.output)

            server._process = self.new_process("tests/apps/data/dead_client.log")
            server.read_output()
            sleep(0.25)
            self.assertFalse("3" in server.output)
        finally:
            if server is not None:
                server.stop()

    def test_iperf_server_dead_client_reset_limit(self):
        server = None
        try:
            server = IPerfServer(
                "5001",
                "udp",
                "1200",
                5,
                cleanup_startup_delay=0,
                cleanup_interval=0.05,
            )
            server._process = self.new_process("tests/apps/data/new_client.log")
            server.run()

            server.read_output()
            self.assertTrue("3" in server.output)
            sleep(0.11)
            current_metric_ttl = server.output["3"].current_metric_ttl

            server._process = self.new_process("tests/apps/data/new_client.log")
            server.read_output()

            self.assertTrue("3" in server.output)
            self.assertGreater(
                server.output["3"].current_metric_ttl, current_metric_ttl
            )
        finally:
            if server is not None:
                server.stop()

    def test_iperf_server_removes_tcp_histograms_for_dead_client(self):
        server = None
        try:
            server = IPerfServer(
                "6011",
                "tcp",
                "8192",
                2,
                cleanup_startup_delay=0,
                cleanup_interval=0.05,
            )
            server._process = self.new_process(
                "tests/apps/data/new_client_tcp_trip_times.log"
            )
            server.run()

            server.read_output()
            self.assertIn("1", server.output)
            self.assertIn("1:x8(f)", server.tcp_histograms)

            server._process = self.new_process("tests/apps/data/dead_client.log")
            server.read_output()
            sleep(0.15)

            self.assertFalse("1" in server.output)
            self.assertEqual(server.tcp_histograms, {})
        finally:
            if server is not None:
                server.stop()

    def test_iperf_server_watchdog_restarts_dead_process(self):
        processes = [PollProcess(exit_code=1), PollProcess(exit_code=None)]
        server = None
        try:
            server = IPerfServer(
                "5001",
                "udp",
                "1200",
                3,
                process_factory=lambda *args, **kwargs: processes.pop(0),
                cleanup_startup_delay=0,
                cleanup_interval=0.05,
                watchdog_interval=0.05,
            )

            server.run()
            sleep(0.12)

            self.assertEqual(server.restart_count, 1)
            self.assertEqual(server.last_exit_code, 1)
            self.assertTrue(server.is_running())
        finally:
            if server is not None:
                server.stop()
