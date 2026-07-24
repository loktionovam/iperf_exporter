import subprocess
from unittest import TestCase

from iperf_exporter.socket_stats import SocketStatsCollector, TCPSocketSnapshot


class FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class TestSocketStatsCollector(TestCase):
    def test_timeout_returns_no_metrics(self):
        collector = SocketStatsCollector(
            port=5001,
            proto="tcp",
            timeout=0.01,
            runner=lambda command, **kwargs: (_ for _ in ()).throw(
                subprocess.TimeoutExpired(command, kwargs["timeout"])
            ),
        )

        self.assertEqual(collector.collect(), {})

    def test_collect_udp_socket_queues(self):
        collector = SocketStatsCollector(
            port=5001,
            proto="udp",
            runner=lambda *args, **kwargs: FakeCompletedProcess(
                stdout=(
                    "Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
                    "0      0       172.31.240.2:5001 172.31.240.4:56729\n"
                    "4      8       172.31.240.2:6001 172.31.240.5:12345\n"
                )
            ),
        )

        snapshots = collector.collect()

        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[("172.31.240.2", "5001", "172.31.240.4", "56729")]
        self.assertEqual(snapshot.recv_queue, 0.0)
        self.assertEqual(snapshot.send_queue, 0.0)

    def test_collect_tcp_socket_stats(self):
        collector = SocketStatsCollector(
            port=5001,
            proto="tcp",
            runner=lambda *args, **kwargs: FakeCompletedProcess(
                stdout=(
                    "State Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
                    "ESTAB 0 0 172.31.240.2:5001 172.31.240.4:56729\n"
                    " cubic wscale:10,10 rto:201 rtt:0.024/0.014 ato:40 "
                    "mss:1448 pmtu:1500 rcvmss:1448 advmss:1448 cwnd:10 "
                    "bytes_sent:28 bytes_acked:28 bytes_received:249430080 "
                    "bytes_retrans:4096 retrans:0/3 "
                    "segs_out:8119 segs_in:173177 data_segs_out:1 "
                    "data_segs_in:173174 send 4.826666667Gbps "
                    "lastsnd:1902737 lastrcv:736 lastack:736 pacing_rate "
                    "9.31376884Gbps delivery_rate 3.861333328Gbps delivered:2 "
                    "app_limited rcv_rtt:1 rcv_space:131072 "
                    "rcv_ssthresh:257420 minrtt:0.003 snd_wnd:64512 "
                    "rcv_wnd:161792\n"
                    "ESTAB 0 0 172.31.240.2:6001 172.31.240.5:43210\n"
                    " cubic cwnd:10\n"
                )
            ),
        )

        snapshots = collector.collect()

        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[("172.31.240.2", "5001", "172.31.240.4", "56729")]
        self.assertIsInstance(snapshot, TCPSocketSnapshot)
        self.assertEqual(snapshot.congestion_algorithm, "cubic")
        self.assertTrue(snapshot.app_limited)
        self.assertEqual(snapshot.metrics["rto_milliseconds"], 201.0)
        self.assertEqual(snapshot.metrics["rtt_milliseconds"], 0.024)
        self.assertEqual(snapshot.metrics["rttvar_milliseconds"], 0.014)
        self.assertEqual(snapshot.metrics["send_rate_bps"], 4_826_666_667.0)
        self.assertEqual(snapshot.metrics["pacing_rate_bps"], 9_313_768_840.0)
        self.assertEqual(snapshot.metrics["delivery_rate_bps"], 3_861_333_328.0)
        self.assertEqual(snapshot.metrics["send_wscale"], 10.0)
        self.assertEqual(snapshot.metrics["rcv_wscale"], 10.0)
        self.assertEqual(snapshot.metrics["snd_wnd_bytes"], 64_512.0)
        self.assertEqual(snapshot.metrics["rcv_wnd_bytes"], 161_792.0)
        self.assertEqual(snapshot.metrics["bytes_retransmitted_total"], 4096.0)
        self.assertEqual(snapshot.metrics["retransmissions_total"], 3.0)

    def test_health_snapshot_records_bounded_failure_reason(self):
        collector = SocketStatsCollector(
            port=5001,
            proto="tcp",
            timeout=0.01,
            runner=lambda command, **kwargs: (_ for _ in ()).throw(
                subprocess.TimeoutExpired(command, kwargs["timeout"])
            ),
        )

        collector.collect()
        health = collector.health_snapshot()

        self.assertEqual(health["error_counts"], {"timeout": 1})
        self.assertGreaterEqual(health["last_duration_seconds"], 0)
        self.assertIsNone(health["last_success_timestamp_seconds"])
