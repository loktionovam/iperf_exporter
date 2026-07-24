import subprocess
from unittest import TestCase

from iperf_exporter.iperf import IPerfClient, IPerfServer


class TestIPerfCommands(TestCase):
    def test_udp_commands_include_udp_flag(self):
        client = IPerfClient(
            port=5001,
            proto="udp",
            interval=1,
            bandwidth="1M",
            duration=315360000,
            peer="127.0.0.1",
        )
        server = IPerfServer(
            port=5001, proto="udp", len=1280, interval=1, metric_ttl=60
        )

        self.assertIn("--udp", client.command)
        self.assertIn("--udp", server.command)
        self.assertIn("--bandwidth", client.command)

    def test_udp_zero_bandwidth_is_kept(self):
        client = IPerfClient(
            port=5001,
            proto="udp",
            interval=1,
            bandwidth="0",
            duration=315360000,
            peer="127.0.0.1",
        )

        self.assertIn("--bandwidth", client.command)
        self.assertIn("0", client.command)

    def test_tcp_commands_do_not_include_fake_tcp_flag(self):
        client = IPerfClient(
            port=5001,
            proto="tcp",
            interval=1,
            bandwidth="1M",
            duration=315360000,
            peer="127.0.0.1",
        )
        server = IPerfServer(
            port=5001, proto="tcp", len=1280, interval=1, metric_ttl=60
        )

        self.assertNotIn("--tcp", client.command)
        self.assertNotIn("--tcp", server.command)

    def test_tcp_positive_bandwidth_is_applied(self):
        client = IPerfClient(
            port=5001,
            proto="tcp",
            interval=1,
            bandwidth="100M",
            duration=315360000,
            peer="127.0.0.1",
        )

        self.assertIn("--bandwidth", client.command)
        self.assertIn("100M", client.command)

    def test_tcp_zero_bandwidth_is_omitted(self):
        client = IPerfClient(
            port=5001,
            proto="tcp",
            interval=1,
            bandwidth="0",
            duration=315360000,
            peer="127.0.0.1",
        )

        self.assertNotIn("--bandwidth", client.command)

    def test_additional_params_are_appended(self):
        client = IPerfClient(
            port=5001,
            proto="tcp",
            interval=1,
            bandwidth="1M",
            duration=315360000,
            peer="127.0.0.1",
            additional_params="--trip-times",
        )
        server = IPerfServer(
            port=5001,
            proto="tcp",
            len=8192,
            interval=1,
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
            interval=1,
            bandwidth="1M",
            duration=315360000,
            peer="127.0.0.1",
            process_factory=lambda *args, **kwargs: processes.pop(0),
        )

        client.run()
        client.ensure_running()

        self.assertEqual(client.restart_count, 1)
        self.assertEqual(client.last_exit_code, 1)
        self.assertTrue(client.is_running())

    def test_custom_interval_and_duration_are_applied(self):
        client = IPerfClient(
            port=5001,
            proto="tcp",
            interval=3,
            bandwidth="1M",
            duration=45,
            peer="127.0.0.1",
        )
        server = IPerfServer(
            port=5001, proto="tcp", len=8192, interval=3, metric_ttl=60
        )

        self.assertIn("--interval", client.command)
        self.assertIn("3", client.command)
        self.assertIn("45", client.command)
        self.assertIn("--interval", server.command)
        self.assertIn("3", server.command)

    def test_process_combines_stderr_and_waits_during_shutdown(self):
        class Stream:
            def readlines(self):
                return []

            def close(self):
                pass

        process = type(
            "Process",
            (),
            {
                "stdout": Stream(),
                "stderr": None,
                "poll": lambda self: None,
                "terminate": lambda self: setattr(self, "terminated", True),
                "wait": lambda self, timeout: 0,
            },
        )()
        process_kwargs = {}

        def process_factory(*args, **kwargs):
            process_kwargs.update(kwargs)
            return process

        client = IPerfClient(
            port=5001,
            proto="tcp",
            interval=1,
            bandwidth="1M",
            duration=2,
            peer="127.0.0.1",
            process_factory=process_factory,
        )

        client.run()
        client.stop()

        self.assertIs(process_kwargs["stderr"], subprocess.STDOUT)
        self.assertTrue(process.terminated)
        self.assertFalse(client.is_running())

    def test_hung_process_is_killed_after_shutdown_timeout(self):
        class Process:
            stdout = None
            stderr = None

            def __init__(self):
                self.wait_calls = 0
                self.killed = False

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, timeout):
                self.wait_calls += 1
                if self.wait_calls == 1:
                    raise subprocess.TimeoutExpired("iperf", timeout)
                return -9

            def kill(self):
                self.killed = True

        process = Process()
        client = IPerfClient(
            port=5001,
            proto="tcp",
            interval=1,
            bandwidth="1M",
            duration=2,
            peer="127.0.0.1",
            process_factory=lambda *args, **kwargs: process,
        )

        client.run()
        client.stop(timeout=0.01)

        self.assertTrue(process.killed)
        self.assertEqual(process.wait_calls, 2)
