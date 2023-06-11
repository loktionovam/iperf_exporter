from unittest import TestCase
from iperf_exporter.iperf import IPerfServer
from time import sleep


class StdOut:
    def __init__(self, file):
        f = open(file, "r")
        self.stdout = f


class TestIPerfServer(TestCase):
    def setUp(self) -> None:
        self.new_client = StdOut("tests/apps/data/new_client.log")
        self.dead_client = StdOut("tests/apps/data/dead_client.log")

    def tearDown(self) -> None:
        self.new_client.stdout.close()
        self.dead_client.stdout.close()

    def test_iperf_server_new_client(self):
        server = IPerfServer("5001", "udp", "1200", 604800)

        server._process = self.new_client

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

    def test_iperf_server_dead_client_not_reach_limit(self):
        # this is a case when we suspect that client is "dead"
        server = None
        try:
            server = IPerfServer("5001", "udp", "1200", 3)
            server._process = self.new_client
            server.run()

            server.read_output()
            self.assertTrue("3" in server.output)

            server._process = self.dead_client
            server.read_output()
            sleep(1)
            self.assertTrue("3" in server.output)
        finally:
            if server is not None:
                server.stop()

    def test_iperf_server_dead_client_reach_limit(self):
        # this is a case when "dead" client is really dead and must be removed
        server = None
        try:
            server = IPerfServer("5001", "udp", "1200", 3)
            server._process = self.new_client
            server.run()

            server.read_output()
            self.assertTrue("3" in server.output)

            server._process = self.dead_client
            server.read_output()
            sleep(10)
            self.assertFalse("3" in server.output)
        finally:
            if server is not None:
                server.stop()

    def test_iperf_server_dead_client_reset_limit(self):
        # this is a case when candidate to "dead" client come back
        server = None
        try:
            server = IPerfServer("5001", "udp", "1200", 5)
            server._process = self.new_client
            server.run()

            server.read_output()
            self.assertTrue("3" in server.output)
            sleep(2)
            server._process = self.new_client

            server.read_output()
            # check if metric still exists
            self.assertTrue("3" in server.output)
            # and it current ttl is reset
            self.assertLess(2, server.output["3"].current_metric_ttl)
        finally:
            if server is not None:
                server.stop()
