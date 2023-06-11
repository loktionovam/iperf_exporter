from unittest import TestCase
from iperf_exporter.collector import IPerfUDPMetrics
from iperf_exporter.iperf import IPerfServer


class StdOut:
    def __init__(self, file):
        f = open(file, "r")
        self.stdout = f


class TestIPerfMetrics(TestCase):
    def setUp(self) -> None:
        # an existing client without metrics
        self.empty_client = StdOut("tests/apps/data/empty_client.log")

    def tearDown(self) -> None:
        self.empty_client.stdout.close()

    def test_empty_client_metrics(self):
        server = IPerfServer("5001", "udp", "1200", 604800)
        server.run()
        server._process = self.empty_client
        server.read_output()
        server.stop()
        metrics = IPerfUDPMetrics(server.output)
