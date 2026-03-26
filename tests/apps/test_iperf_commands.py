from unittest import TestCase

from iperf_exporter.iperf import IPerfClient, IPerfServer


class TestIPerfCommands(TestCase):
    def test_udp_commands_include_udp_flag(self):
        client = IPerfClient(port=5001, proto="udp", bandwidth="1M", peer="127.0.0.1")
        server = IPerfServer(port=5001, proto="udp", len=1280, metric_ttl=60)

        self.assertIn("--udp", client.command)
        self.assertIn("--udp", server.command)
        self.assertIn("--bandwidth", client.command)

    def test_udp_zero_bandwidth_is_kept(self):
        client = IPerfClient(port=5001, proto="udp", bandwidth="0", peer="127.0.0.1")

        self.assertIn("--bandwidth", client.command)
        self.assertIn("0", client.command)

    def test_tcp_commands_do_not_include_fake_tcp_flag(self):
        client = IPerfClient(port=5001, proto="tcp", bandwidth="1M", peer="127.0.0.1")
        server = IPerfServer(port=5001, proto="tcp", len=1280, metric_ttl=60)

        self.assertNotIn("--tcp", client.command)
        self.assertNotIn("--tcp", server.command)

    def test_tcp_positive_bandwidth_is_applied(self):
        client = IPerfClient(port=5001, proto="tcp", bandwidth="100M", peer="127.0.0.1")

        self.assertIn("--bandwidth", client.command)
        self.assertIn("100M", client.command)

    def test_tcp_zero_bandwidth_is_omitted(self):
        client = IPerfClient(port=5001, proto="tcp", bandwidth="0", peer="127.0.0.1")

        self.assertNotIn("--bandwidth", client.command)

    def test_additional_params_are_appended(self):
        client = IPerfClient(
            port=5001,
            proto="tcp",
            bandwidth="1M",
            peer="127.0.0.1",
            additional_params="--trip-times",
        )
        server = IPerfServer(
            port=5001,
            proto="tcp",
            len=8192,
            metric_ttl=60,
            additional_params="--histograms=100u,20",
        )

        self.assertIn("--trip-times", client.command)
        self.assertIn("--histograms=100u,20", server.command)

    def test_client_ensure_running_restarts_dead_process(self):
        class Stream:
            def readlines(self):
                return []

            def close(self):
                pass

        class Process:
            def __init__(self, exit_code=None):
                self.exit_code = exit_code
                self.stdout = Stream()
                self.stderr = Stream()

            def poll(self):
                return self.exit_code

        processes = [Process(exit_code=1), Process(exit_code=None)]
        client = IPerfClient(
            port=5001,
            proto="tcp",
            bandwidth="1M",
            peer="127.0.0.1",
            process_factory=lambda *args, **kwargs: processes.pop(0),
        )

        client.run()
        client.ensure_running()

        self.assertEqual(client.restart_count, 1)
        self.assertEqual(client.last_exit_code, 1)
        self.assertTrue(client.is_running())
