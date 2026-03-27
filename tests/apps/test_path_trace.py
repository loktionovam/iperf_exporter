import subprocess
from types import SimpleNamespace
from unittest import TestCase

from iperf_exporter.path_trace import PathTraceCollector


class FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class TestPathTraceCollector(TestCase):
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

        snapshots = collector.collect(
            {
                "4": SimpleNamespace(
                    local_address="172.31.240.6",
                    local_port="5002",
                    peer_address="172.31.240.10",
                    peer_port="50058",
                )
            }
        )

        snapshot = snapshots[("172.31.240.6", "5002", "172.31.240.10", "50058")]
        self.assertEqual(snapshot.pmtu_bytes, 1500.0)
        self.assertEqual(snapshot.hops_total, 1.0)
        self.assertTrue(snapshot.success)
        self.assertEqual(len(snapshot.hops), 1)
        self.assertEqual(snapshot.hops[0].hop_index, 1)
        self.assertEqual(snapshot.hops[0].hop_address, "172.31.240.10")
        self.assertEqual(snapshot.hops[0].hop_summary, "0.131ms reached")
        self.assertEqual(
            commands[0][0],
            ["tracepath", "-n", "-m", "8", "-p", "50058", "172.31.240.10"],
        )
        self.assertEqual(commands[0][1]["timeout"], 5)

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

        collector.collect(output)
        collector.collect(output)
        now[0] = 131.0
        collector.collect(output)

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

        snapshots = collector.collect(
            {
                "3": SimpleNamespace(
                    local_address="172.31.240.2",
                    local_port="5001",
                    peer_address="172.31.240.4",
                    peer_port="56729",
                )
            }
        )

        snapshot = snapshots[("172.31.240.2", "5001", "172.31.240.4", "56729")]
        self.assertFalse(snapshot.success)
        self.assertEqual(snapshot.hops_total, 2.0)
        self.assertEqual(snapshot.hops[1].hop_summary, "no reply")

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

        snapshots = collector.collect(output)
        collector.collect(output)
        now[0] = 131.0
        collector.collect(output)

        snapshot = snapshots[("172.31.240.6", "5001", "172.31.240.10", "50058")]
        self.assertFalse(snapshot.success)
        self.assertEqual(snapshot.hops_total, 0.0)
        self.assertEqual(len(runner_calls), 2)
