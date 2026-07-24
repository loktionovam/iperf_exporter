import subprocess
import threading
import time
from types import SimpleNamespace
from unittest import TestCase

from iperf_exporter.path_trace import PathTraceCollector


class FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class TestPathTraceCollector(TestCase):
    def collect_until_snapshot(self, collector, output):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            snapshots = collector.collect(output)
            if snapshots:
                return snapshots
            time.sleep(0.01)
        self.fail("path trace worker did not publish a snapshot")

    def test_collect_tracepath_snapshot(self):
        commands = []
        collector = PathTraceCollector(
            proto="tcp",
            ttl=300,
            max_hops=8,
            timeout=5,
            runner=lambda command, **kwargs: (
                commands.append((command, kwargs))
                or FakeCompletedProcess(
                    stdout=(
                        " 1?: [LOCALHOST] pmtu 1500\n"
                        " 1:  172.31.240.10                                   0.131ms reached\n"
                        "     Resume: pmtu 1500 hops 1 back 1\n"
                    )
                )
            ),
        )

        output = {
            "4": SimpleNamespace(
                local_address="172.31.240.6",
                local_port="5002",
                peer_address="172.31.240.10",
                peer_port="50058",
            )
        }
        self.assertEqual(collector.collect(output), {})
        snapshots = self.collect_until_snapshot(collector, output)

        snapshot = snapshots[("172.31.240.6", "5002", "172.31.240.10", "50058")]
        self.assertEqual(snapshot.pmtu_bytes, 1500.0)
        self.assertEqual(snapshot.hops_total, 1.0)
        self.assertTrue(snapshot.success)
        self.assertEqual(len(snapshot.hops), 1)
        self.assertEqual(snapshot.hops[0].hop_index, 1)
        self.assertEqual(snapshot.hops[0].hop_address, "172.31.240.10")
        self.assertEqual(
            commands[0][0],
            ["tracepath", "-n", "-m", "8", "-p", "50058", "172.31.240.10"],
        )
        self.assertEqual(commands[0][1]["timeout"], 5)
        health = collector.health_snapshot()
        self.assertEqual(health["error_counts"], {})
        self.assertIsNotNone(health["last_success_timestamp_seconds"])
        self.assertGreaterEqual(health["last_duration_seconds"], 0)

    def test_collect_does_not_wait_for_background_trace(self):
        release_runner = threading.Event()

        def blocking_runner(*args, **kwargs):
            release_runner.wait(2)
            return FakeCompletedProcess()

        collector = PathTraceCollector(
            proto="tcp",
            ttl=300,
            runner=blocking_runner,
        )
        self.addCleanup(collector.close)
        output = {
            "4": SimpleNamespace(
                local_address="172.31.240.6",
                local_port="5002",
                peer_address="172.31.240.10",
                peer_port="50058",
            )
        }

        started = time.monotonic()
        snapshots = collector.collect(output)
        elapsed = time.monotonic() - started
        self.assertEqual(collector.health_snapshot()["in_flight"], 1)
        release_runner.set()

        self.assertEqual(snapshots, {})
        self.assertLess(elapsed, 0.1)

    def test_close_stops_in_flight_tracepath_process(self):
        started = threading.Event()
        released = threading.Event()

        class Process:
            returncode = None

            def communicate(self, timeout=None):
                started.set()
                released.wait(timeout)
                self.returncode = -15
                return "", ""

            def poll(self):
                return self.returncode

            def terminate(self):
                released.set()

            def wait(self, timeout):
                released.wait(timeout)
                self.returncode = -15
                return self.returncode

            def kill(self):
                released.set()

        process = Process()
        collector = PathTraceCollector(
            proto="tcp",
            ttl=300,
            timeout=10,
            process_factory=lambda *args, **kwargs: process,
        )
        output = {
            "4": SimpleNamespace(
                local_address="172.31.240.6",
                local_port="5002",
                peer_address="172.31.240.10",
                peer_port="50058",
            )
        }

        collector.collect(output)
        self.assertTrue(started.wait(1))
        collector.close()

        self.assertEqual(process.returncode, -15)

    def test_collect_uses_cache_until_ttl_expires(self):
        now = [100.0]
        runner_calls = []
        collector = PathTraceCollector(
            proto="udp",
            ttl=30,
            runner=lambda command, **kwargs: (
                runner_calls.append(command)
                or FakeCompletedProcess(
                    stdout=(
                        " 1?: [LOCALHOST] pmtu 1500\n"
                        " 1:  172.31.240.4                                   0.030ms reached\n"
                        "     Resume: pmtu 1500 hops 1 back 1\n"
                    )
                )
            ),
            time_fn=lambda: now[0],
        )
        output = {
            "3": SimpleNamespace(
                local_address="172.31.240.2",
                local_port="5001",
                peer_address="172.31.240.4",
                peer_port="56729",
            )
        }

        self.collect_until_snapshot(collector, output)
        collector.collect(output)
        now[0] = 131.0
        collector.collect(output)

        deadline = time.monotonic() + 2
        while len(runner_calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(runner_calls), 2)

    def test_collect_keeps_partial_route_when_destination_does_not_reply(self):
        collector = PathTraceCollector(
            proto="udp",
            ttl=300,
            runner=lambda *args, **kwargs: FakeCompletedProcess(
                stdout=(
                    " 1?: [LOCALHOST] pmtu 1500\n"
                    " 1:  172.31.240.1                                     0.201ms\n"
                    " 2:  no reply\n"
                    "     Resume: pmtu 1500 hops 2 back 1\n"
                ),
                returncode=1,
            ),
        )

        output = {
            "3": SimpleNamespace(
                local_address="172.31.240.2",
                local_port="5001",
                peer_address="172.31.240.4",
                peer_port="56729",
            )
        }
        snapshots = self.collect_until_snapshot(collector, output)

        snapshot = snapshots[("172.31.240.2", "5001", "172.31.240.4", "56729")]
        self.assertFalse(snapshot.success)
        self.assertEqual(snapshot.hops_total, 2.0)
        self.assertEqual(snapshot.hops[1].hop_address, "")

    def test_collect_caches_failed_tracepath_result_until_ttl_expires(self):
        now = [100.0]
        runner_calls = []

        def timeout_runner(command, **kwargs):
            runner_calls.append(command)
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        collector = PathTraceCollector(
            proto="tcp",
            ttl=30,
            timeout=5,
            runner=timeout_runner,
            time_fn=lambda: now[0],
        )
        output = {
            "5": SimpleNamespace(
                local_address="172.31.240.6",
                local_port="5001",
                peer_address="172.31.240.10",
                peer_port="50058",
            )
        }

        snapshots = self.collect_until_snapshot(collector, output)
        collector.collect(output)
        now[0] = 131.0
        collector.collect(output)

        deadline = time.monotonic() + 2
        while len(runner_calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        snapshot = snapshots[("172.31.240.6", "5001", "172.31.240.10", "50058")]
        self.assertFalse(snapshot.success)
        self.assertEqual(snapshot.hops_total, 0.0)
        self.assertEqual(len(runner_calls), 2)
        self.assertGreaterEqual(
            collector.health_snapshot()["error_counts"]["timeout"],
            1,
        )
