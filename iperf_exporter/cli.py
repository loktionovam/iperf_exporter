import os
import sys
import time
import configargparse
from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY

from iperf_exporter.collector import IPerfCollector
from iperf_exporter.logger import log
from iperf_exporter.iperf import IPerfClient


def parse_args(args):
    parser = configargparse.ArgParser(
        description="IPerf exporter args",
    )

    parser.add(
        "-m",
        "--iperf_exporter_mode",
        metavar="iperf_exporter_mode",
        help="IPerf exporter mode: server/client",
        default=os.environ.get("IPERF_EXPORTER_MODE", "server"),
    )
    parser.add(
        "-p",
        "--iperf_exporter_port",
        metavar="iperf_exporter_port",
        type=int,
        help="IPerf server/client listen port",
        default=os.environ.get("IPERF_EXPORTER_PORT", "5001"),
    )
    parser.add(
        "-i",
        "--iperf_exporter_interval",
        metavar="iperf_exporter_interval",
        type=int,
        help="Seconds between periodic bandwidth reports",
        default=int(os.environ.get("IPERF_EXPORTER_INTERVAL", "1")),
    )
    parser.add(
        "-r",
        "--iperf_exporter_proto",
        metavar="iperf_exporter_proto",
        help="Iperf protocol: tcp/udp",
        default=os.environ.get("IPERF_EXPORTER_PROTO", "udp"),
    )

    parser.add(
        "-l",
        "--iperf_exporter_len",
        metavar="iperf_exporter_len",
        type=int,
        help="Length of buffer in bytes to read or write",
        default=int(os.environ.get("IPERF_EXPORTER_LEN", "1280")),
    )
    parser.add(
        "-k",
        "--iperf_exporter_bind_port",
        metavar="iperf_exporter_bind_port",
        type=int,
        help="IPerf exporter bind port",
        default=int(os.environ.get("IPERF_EXPORTER_BIND_PORT", "9868")),
    )

    parser.add(
        "-b",
        "--iperf_exporter_client_bandwidth",
        metavar="iperf_exporter_client_bandwidth",
        help="IPerf client bandwidth",
        default=os.environ.get("IPERF_EXPORTER_CLIENT_BANDWIDTH", "1M"),
    )

    parser.add(
        "-a",
        "--iperf_exporter_client_peer",
        metavar="iperf_exporter_client_peer",
        help="IPerf server peer address where client connects to",
        default=os.environ.get("IPERF_EXPORTER_CLIENT_PEER", "127.0.0.1"),
    )
    return parser.parse_args(args)


def run_exporter(args):
    log.info(
        f"Start iperf exporter in {args.iperf_exporter_mode} mode ({args.iperf_exporter_proto})"
    )
    collector = IPerfCollector(
        port=args.iperf_exporter_port,
        proto=args.iperf_exporter_proto,
        len=args.iperf_exporter_len,
    )
    REGISTRY.register(collector)

    start_http_server(args.iperf_exporter_bind_port)
    log.info(f"Serving at port: {args.iperf_exporter_bind_port}")
    while True:
        time.sleep(1)


def run_client(args):
    log.info(
        f"Start iperf in {args.iperf_exporter_mode} mode ({args.iperf_exporter_proto})"
    )

    iperf_client = IPerfClient(
        port=args.iperf_exporter_port,
        proto=args.iperf_exporter_proto,
        bandwidth=args.iperf_exporter_client_bandwidth,
        peer=args.iperf_exporter_client_peer,
    )

    iperf_client.run()
    while True:
        time.sleep(1)


def main():
    args = parse_args(sys.argv[1:])
    if args.iperf_exporter_mode == "server":
        run_exporter(args)
    elif args.iperf_exporter_mode == "client":
        run_client(args)


if __name__ == "__main__":
    main()
