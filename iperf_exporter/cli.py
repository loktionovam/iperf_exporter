import os
import sys
import time

import configargparse
from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY

from iperf_exporter.collector import IPerfCollector
from iperf_exporter.iperf import IPerfClient
from iperf_exporter.logger import log


def parse_args(args):
    parser = configargparse.ArgParser(
        description="IPerf exporter args",
    )

    parser.add(
        "-m",
        "--iperf_exporter_mode",
        metavar="iperf_exporter_mode",
        choices=["server", "client"],
        help="IPerf exporter mode: server/client",
        default=os.environ.get("IPERF_EXPORTER_MODE", "server"),
    )
    parser.add(
        "-p",
        "--iperf_exporter_port",
        metavar="iperf_exporter_port",
        type=int,
        help="IPerf server/client listen port",
        default=int(os.environ.get("IPERF_EXPORTER_PORT", "5001")),
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
        choices=["tcp", "udp"],
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
        "-t",
        "--iperf_exporter_metric_ttl",
        metavar="iperf_exporter_metric_ttl",
        help="Lifetime of inactive clients",
        type=int,
        default=int(os.environ.get("IPERF_EXPORTER_METRIC_TTL", "604800")),
    )

    parser.add(
        "-v",
        "--iperf_exporter_debug",
        metavar="iperf_exporter_debug",
        help="Debug mode on/off (1/0)",
        default=os.environ.get("DEBUG", "0"),
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
    parser.add(
        "--iperf_exporter_server_additional_params",
        metavar="iperf_exporter_server_additional_params",
        help="Additional iperf server parameters appended to the iperf command",
        default=os.environ.get("IPERF_EXPORTER_SERVER_ADDITIONAL_PARAMS", ""),
    )
    parser.add(
        "--iperf_exporter_client_additional_params",
        metavar="iperf_exporter_client_additional_params",
        help="Additional iperf client parameters appended to the iperf command",
        default=os.environ.get("IPERF_EXPORTER_CLIENT_ADDITIONAL_PARAMS", ""),
    )
    parser.add(
        "--iperf_exporter_context_client_bandwidth",
        metavar="iperf_exporter_context_client_bandwidth",
        help="Optional client bandwidth hint exported by server-mode dashboards",
        default=os.environ.get(
            "IPERF_EXPORTER_CONTEXT_CLIENT_BANDWIDTH",
            os.environ.get("IPERF_EXPORTER_CLIENT_BANDWIDTH", ""),
        ),
    )
    parser.add(
        "--iperf_exporter_context_client_additional_params",
        metavar="iperf_exporter_context_client_additional_params",
        help="Optional client additional params hint exported by server-mode dashboards",
        default=os.environ.get(
            "IPERF_EXPORTER_CONTEXT_CLIENT_ADDITIONAL_PARAMS",
            os.environ.get("IPERF_EXPORTER_CLIENT_ADDITIONAL_PARAMS", ""),
        ),
    )
    parser.add(
        "--iperf_exporter_path_trace_ttl",
        metavar="iperf_exporter_path_trace_ttl",
        type=int,
        help="Seconds to cache tracepath snapshots; set to 0 to disable path tracing",
        default=int(os.environ.get("IPERF_EXPORTER_PATH_TRACE_TTL", "300")),
    )
    parser.add(
        "--iperf_exporter_path_trace_max_hops",
        metavar="iperf_exporter_path_trace_max_hops",
        type=int,
        help="Maximum hop count used by tracepath",
        default=int(os.environ.get("IPERF_EXPORTER_PATH_TRACE_MAX_HOPS", "16")),
    )
    parser.add(
        "--iperf_exporter_path_trace_timeout",
        metavar="iperf_exporter_path_trace_timeout",
        type=int,
        help="Subprocess timeout in seconds for one tracepath execution",
        default=int(os.environ.get("IPERF_EXPORTER_PATH_TRACE_TIMEOUT", "10")),
    )
    return parser.parse_args(args)


def wait_forever():
    while True:
        time.sleep(1)


def stream_client_output(iperf_client, sleep_fn=time.sleep):
    while True:
        iperf_client.ensure_running()
        iperf_client.read_output()
        sleep_fn(1)


def setup_exporter(
    args,
    collector_cls=IPerfCollector,
    registry=REGISTRY,
    http_server_factory=start_http_server,
):
    log.info(
        f"Start iperf exporter in {args.iperf_exporter_mode} mode ({args.iperf_exporter_proto})"
    )
    collector = collector_cls(
        port=args.iperf_exporter_port,
        proto=args.iperf_exporter_proto,
        len=args.iperf_exporter_len,
        metric_ttl=args.iperf_exporter_metric_ttl,
        additional_params=args.iperf_exporter_server_additional_params,
        context_client_bandwidth=args.iperf_exporter_context_client_bandwidth,
        context_client_additional_params=args.iperf_exporter_context_client_additional_params,
        path_trace_ttl=args.iperf_exporter_path_trace_ttl,
        path_trace_max_hops=args.iperf_exporter_path_trace_max_hops,
        path_trace_timeout=args.iperf_exporter_path_trace_timeout,
    )
    registry.register(collector)
    http_server_factory(args.iperf_exporter_bind_port)
    log.info(f"Serving at port: {args.iperf_exporter_bind_port}")
    return collector


def run_exporter(
    args,
    collector_cls=IPerfCollector,
    registry=REGISTRY,
    http_server_factory=start_http_server,
    idle_fn=wait_forever,
):
    collector = setup_exporter(
        args,
        collector_cls=collector_cls,
        registry=registry,
        http_server_factory=http_server_factory,
    )
    idle_fn()
    return collector


def setup_client(args, client_cls=IPerfClient):
    log.info(
        f"Start iperf in {args.iperf_exporter_mode} mode ({args.iperf_exporter_proto})"
    )

    iperf_client = client_cls(
        port=args.iperf_exporter_port,
        proto=args.iperf_exporter_proto,
        bandwidth=args.iperf_exporter_client_bandwidth,
        peer=args.iperf_exporter_client_peer,
        additional_params=args.iperf_exporter_client_additional_params,
    )

    iperf_client.run()
    return iperf_client


def run_client(args, client_cls=IPerfClient, output_loop_fn=stream_client_output):
    iperf_client = setup_client(args, client_cls=client_cls)
    output_loop_fn(iperf_client)
    return iperf_client


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.iperf_exporter_mode == "server":
        run_exporter(args)
        return 0
    if args.iperf_exporter_mode == "client":
        run_client(args)
        return 0
    raise ValueError(f"Unsupported mode: {args.iperf_exporter_mode}")


if __name__ == "__main__":
    main()
