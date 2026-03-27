from unittest import TestCase

from iperf_exporter.collector import (
    IPerfTCPHistogramMetrics,
    IPerfTCPMetrics,
    IPerfUDPMetrics,
)
from iperf_exporter.iperf import IPerfServer


class StdOutProcess:
    def __init__(self, file):
        self.stdout = open(file, "r")

    def close(self):
        self.stdout.close()


class TestIPerfMetrics(TestCase):
    def setUp(self) -> None:
        self.processes = []

    def tearDown(self) -> None:
        for process in self.processes:
            process.close()

    def new_process(self, path):
        process = StdOutProcess(path)
        self.processes.append(process)
        return process

    def test_empty_udp_client_metrics(self):
        server = IPerfServer("5001", "udp", "1200", 1, 604800)
        server._process = self.new_process("tests/apps/data/empty_client.log")
        server.read_output()
        metrics = IPerfUDPMetrics(server.output)

        self.assertEqual(len(list(metrics)), 12)

    def test_tcp_metrics(self):
        server = IPerfServer("5001", "tcp", "8192", 1, 604800)
        server._process = self.new_process("tests/apps/data/new_client_tcp.log")
        server.read_output()
        metrics = IPerfTCPMetrics(server.output)

        self.assertEqual(len(list(metrics)), 19)

    def test_tcp_histogram_metrics(self):
        server = IPerfServer("6011", "tcp", "8192", 1, 604800)
        server._process = self.new_process(
            "tests/apps/data/new_client_tcp_trip_times.log"
        )
        server.read_output()
        metrics = IPerfTCPHistogramMetrics(server.tcp_histograms)

        self.assertEqual(len(list(metrics)), 4)
