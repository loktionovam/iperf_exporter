from unittest import TestCase

from iperf_exporter.iperf import (
    IPerfParserNewConnection,
    IPerfParserTCPHistogramEntry,
    IPerfParserTripTimesTCPEntry,
    IPerfParserUsualTCPEntry,
    IPerfParserUsualUDPEntry,
)


class TestIPerfParser(TestCase):
    def test_parser_udp_entry_match(self):
        pattern1 = "[  3] 1075.00-1076.00 sec  21600 Bytes  172800 bits/sec   0.072 ms 0/18 (0%) -0.057/-0.207/0.039/0.063 ms 17 pps 18/0(0) pkts -378.578384"
        pattern2 = "[  100] 4432.00-4433.00 sec  20400 Bytes  163200 bits/sec   0.086 ms 0/17 (0%) 7.049/7.183/6.845/0.085 ms 17 pps 17/0(0) pkts 2.894221"
        pattern3 = "[ 14] 555.00-556.00 sec  51600 Bytes  412800 bits/sec   0.055 ms 0/43 (0%) -1.842/-1.904/-1.732/0.042 ms 44 pps 44/0(0) pkts -28.013737"
        pattern4 = "[ 1] 0.00-10.00 sec 459 MBytes 385 Mbits/sec 0.019 ms 0/500004 (0.23%) 0.123/0.050/1.288/0.034 ms 49999 pps 49999/0(2) pkts 0/0/0 391163"
        pattern5 = "[ 3] 1.00-2.00 sec  20400 Bytes  163200 bits/sec   0.086 ms 0/17 (0%) 7.049/7.183/6.845/0.085 ms 17 pps 17/2.13 MByte 1/0/0 2.894221"
        self.assertIsNotNone(IPerfParserUsualUDPEntry(pattern1).match())
        self.assertIsNotNone(IPerfParserUsualUDPEntry(pattern2).match())
        self.assertIsNotNone(IPerfParserUsualUDPEntry(pattern3).match())
        self.assertIsNotNone(IPerfParserUsualUDPEntry(pattern4).match())
        self.assertIsNotNone(IPerfParserUsualUDPEntry(pattern5).match())

    def test_parser_udp_entry_not_match(self):
        pattern1 = "[SUM] 75763.00-75764.00 sec  21600 Bytes  172800 bits/sec  0/18       17 pps"
        self.assertIsNone(IPerfParserUsualUDPEntry(pattern1).match())

    def test_parser_tcp_entry_match(self):
        pattern = "[ 4] 0.00-1.00 sec 124000000 Bytes 1040000000 bits/sec 22249=798:2637:2061:767:2165:1563:589:11669"
        match = IPerfParserUsualTCPEntry(pattern).match()
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).strip(), "4")
        self.assertEqual(match.group(6), "22249")
        self.assertEqual(match.group(7), "798:2637:2061:767:2165:1563:589:11669")

    def test_parser_tcp_trip_times_entry_match(self):
        pattern = "[  1] 0.00-2.00 sec  5486411856 Bytes  21940085612 bits/sec  0.858/0.034/40.291/1.222 ms (41858/131072) 7.35 MByte 3195152  678097=8369:0:0:0:0:0:3:627867"
        match = IPerfParserTripTimesTCPEntry(pattern).match()
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).strip(), "1")
        self.assertEqual(match.group(6), "0.858")
        self.assertEqual(match.group(12), "7.35 MByte")
        self.assertEqual(match.group(15), "8369:0:0:0:0:0:3:627867")

    def test_parser_tcp_histogram_entry_match(self):
        pattern = "[  1] 0.00-2.00 sec x8(f)-PDF: bin(w=100us):cnt(41858)=1:37,2:142,3:150,4:219,5:747,6:2620,7:6125,8:11964,9:11051,10:5532,11:2124,12:320,13:123,14:71,15:60,16:39,17:22,18:25,19:32,20:11 (5.00/95.00/99.7%=6/11/20,Outliers=11,obl/obu=0/394)"
        match = IPerfParserTCPHistogramEntry(pattern).match()
        self.assertIsNotNone(match)
        self.assertEqual(match.group(4), "x8(f)")
        self.assertEqual(match.group(5), "100us")
        self.assertEqual(match.group(6), "41858")

    def test_parser_new_connection_match(self):
        pattern1 = "[  4] local 127.0.0.1%eth0 port 5001 connected with 127.0.0.1 port 57191 (sock=6) (peer 2.1.8) on 2023-05-02 08:45:12 (UTC)"
        pattern2 = (
            "[  3] local 127.0.0.1%eth0 port 5001 connected with 127.0.0.1 port 52370"
        )
        pattern3 = (
            "[ 4] local 45.33.58.123 port 5001 connected with 45.56.85.133 port 49960"
        )
        pattern4 = (
            "[  1] local 127.0.0.1%lo0 port 6011 connected with 127.0.0.1 port 65031 "
            "(trip-times) (sock=4) (peer 2.1.9) (icwnd/mss/irtt=159/16332/1000) "
            "on 2026-03-26 21:08:53.571 (UTC)"
        )
        self.assertIsNotNone(IPerfParserNewConnection(pattern1).match())
        self.assertIsNotNone(IPerfParserNewConnection(pattern2).match())
        self.assertIsNotNone(IPerfParserNewConnection(pattern3).match())
        self.assertIsNotNone(IPerfParserNewConnection(pattern4).match())
