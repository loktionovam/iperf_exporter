from unittest import TestCase
import responses
from iperf_exporter.collector import IPerfCollector
from prometheus_client.core import CollectorRegistry
import subprocess
from time import sleep
import platform
from iperf_exporter.iperf import IPerfClient


def get_loopback_iface():
    system = platform.system()

    if system == "Linux":
        return "lo"
    elif system == "Darwin":
        return "lo0"
    else:
        # Fallback to a generic loopback interface name
        return "lo"


class TestIPerfCollector(TestCase):
    def setUp(self):
        responses.mock.start()

    def tearDown(self):
        """Disable responses."""
        responses.mock.stop()
        responses.mock.reset()
        self.client._process.kill()
        self.collector.server._process.kill()

    def test_collect_200(self):

        self.registry = CollectorRegistry(auto_describe=True)
        self.collector = IPerfCollector(port=5001, proto="udp", len="1280")
        self.registry.register(self.collector)
        sleep(2)
        # label selectors doesn't work so we need to bind client to ip:port
        # https://github.com/prometheus/client_python/blob/8bbd16f34014d9b28fa53068eb2a1f87c45d34fc/prometheus_client/registry.py#L131
        self.client = IPerfClient(
            port=5001,
            proto="udp",
            bandwidth="1M",
            peer="127.0.0.1",
            additional_params=" --bind 127.0.0.1:50396",
        )
        self.client.run()
        sleep(3)
        labels = {
            "peer_id": "1",
            "local_address": "127.0.0.1",
            "interface_name": get_loopback_iface(),
            "local_port": "5001",
            "peer_address": "127.0.0.1",
            "peer_port": "50396",
        }

        self.assertLess(
            110000,
            float(
                self.registry.get_sample_value(
                    "iperf_exporter_udp_transfer", labels=labels
                )
            ),
        )

        self.assertLess(
            900000,
            float(
                self.registry.get_sample_value(
                    "iperf_exporter_udp_bandwidth", labels=labels
                )
            ),
        )

        self.assertLess(
            0,
            float(
                self.registry.get_sample_value(
                    "iperf_exporter_udp_jitter", labels=labels
                )
            ),
        )
        self.assertIsNotNone(
            (self.registry.get_sample_value("iperf_exporter_udp_lost", labels=labels)),
        )

        self.assertIsNotNone(
            (self.registry.get_sample_value("iperf_exporter_udp_total", labels=labels)),
        )

        self.assertIsNotNone(
            (
                self.registry.get_sample_value(
                    "iperf_exporter_udp_lost_percentage", labels=labels
                )
            ),
        )

        self.assertIsNotNone(
            (
                self.registry.get_sample_value(
                    "iperf_exporter_udp_latency_avg", labels=labels
                )
            ),
        )

        self.assertIsNotNone(
            (
                self.registry.get_sample_value(
                    "iperf_exporter_udp_latency_min", labels=labels
                )
            ),
        )

        self.assertIsNotNone(
            (
                self.registry.get_sample_value(
                    "iperf_exporter_udp_latency_max", labels=labels
                )
            ),
        )

        self.assertIsNotNone(
            (
                self.registry.get_sample_value(
                    "iperf_exporter_udp_latency_stdev", labels=labels
                )
            ),
        )

        self.assertIsNotNone(
            (self.registry.get_sample_value("iperf_exporter_udp_pps", labels=labels)),
        )

        self.assertIsNotNone(
            (
                self.registry.get_sample_value(
                    "iperf_exporter_udp_netpwr", labels=labels
                )
            ),
        )
        # self.assertEqual(
        #     15,
        #     self.registry.get_sample_value(
        #         "iperf_exporter_udp_transfer",
        #         {"peer_id": "1", "local_address": "127.0.0.1", "interface_name": "lo0"},
        #     ),
        # )
