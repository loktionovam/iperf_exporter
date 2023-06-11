from prometheus_client.core import GaugeMetricFamily
from iperf_exporter.logger import log
from iperf_exporter.iperf import IPerfServer, IPerfServerUDPOutput
from iperf_exporter.logger import log


class IPerfUDPMetrics:
    """
    The data class which represents iperf udp output in a prometheus format.
    """

    def __init__(self, output: IPerfServerUDPOutput):
        self.metrics_prefix = "iperf_exporter_udp"
        self.data = {}
        label_names = [
            "peer_id",
            "local_address",
            "interface_name",
            "local_port",
            "peer_address",
            "peer_port",
        ]

        metric_names = [
            "transfer",
            "bandwidth",
            "jitter",
            "lost",
            "total",
            "lost_percentage",
            "latency_avg",
            "latency_min",
            "latency_max",
            "latency_stdev",
            "pps",
            "netpwr",
        ]
        for name in metric_names:
            metric_name = f"{self.metrics_prefix}_{name}"
            self.data[metric_name] = GaugeMetricFamily(
                metric_name, "", labels=label_names
            )

        for id, out in output.items():
            for name in metric_names:
                metric_name = f"{self.metrics_prefix}_{name}"
                label_values = [
                    id,
                    out.local_address,
                    out.interface_name,
                    out.local_port,
                    out.peer_address,
                    out.peer_port,
                ]
                log.debug(f"Add metric {metric_name = } with {label_values = }")
                try:
                    self.data[metric_name].add_metric(
                        label_values, str(getattr(out, name))
                    )
                except AttributeError:
                    log.info(f"Client {id = } doesn't have metric {name = }")

    def __iter__(self):
        for metric in self.data.values():
            yield metric


class IPerfCollector:
    """
    The custom prometheus collector which fetches metrics data from iperf output parse them and
    store in prometheus format. Instance of the class is used by a prometheus client registry.

    https://github.com/prometheus/client_python#custom-collectors
    """

    def __init__(self, port, proto, len, metric_ttl):
        """ """
        self.server = IPerfServer(port, proto, len, metric_ttl)
        self.server.run()
        self.metrics = None

    def collect(self):
        self.server.read_output()
        log.info(self.server.output)
        self.metrics = IPerfUDPMetrics(self.server.output)
        for metric in self.metrics:
            yield metric
