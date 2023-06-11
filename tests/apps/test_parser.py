from unittest import TestCase
from iperf_exporter.iperf import (
    IPerfParserUsualEntry,
    IPerfParserNewConnection,
)


class TestIPerfParser(TestCase):
    def test_parser_usual_entry_match(self):
        pattern1 = "[  3] 1075.00-1076.00 sec  21600 Bytes  172800 bits/sec   0.072 ms 0/18 (0%) -0.057/-0.207/0.039/0.063 ms 17 pps 18/0(0) pkts -378.578384"
        pattern2 = "[  100] 4432.00-4433.00 sec  20400 Bytes  163200 bits/sec   0.086 ms 0/17 (0%) 7.049/7.183/6.845/0.085 ms 17 pps 17/0(0) pkts 2.894221"
        pattern3 = "[ 14] 555.00-556.00 sec  51600 Bytes  412800 bits/sec   0.055 ms 0/43 (0%) -1.842/-1.904/-1.732/0.042 ms 44 pps -28.013737"
        self.assertIsNotNone(IPerfParserUsualEntry(pattern1).match())
        self.assertIsNotNone(IPerfParserUsualEntry(pattern2).match())
        self.assertIsNotNone(IPerfParserUsualEntry(pattern3).match())

    def test_parser_usual_entry_not_match(self):
        pattern1 = "[  2] 75568.00-75569.00 sec  0.000 Bytes  0.000 bits/sec   0.000 ms 0/0 (0%) -/-/-/- ms 0 pps"
        pattern2 = "[SUM] 75763.00-75764.00 sec  21600 Bytes  172800 bits/sec  0/18       17 pps"
        self.assertIsNone(IPerfParserUsualEntry(pattern1).match())
        self.assertIsNone(IPerfParserUsualEntry(pattern2).match())

    def test_parser_new_connection_match(self):
        pattern1 = "[  4] local 127.0.0.1%eth0 port 5001 connected with 127.0.0.1 port 57191 (sock=6) (peer 2.1.8) on 2023-05-02 08:45:12 (UTC)"
        pattern2 = "[  3] local 127.0.0.1%eth0 port 5001 connected with 127.0.0.1 port 52370"
        self.assertIsNotNone(IPerfParserNewConnection(pattern1).match())
        self.assertIsNotNone(IPerfParserNewConnection(pattern2).match())
