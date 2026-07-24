import re
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field

from iperf_exporter.logger import log


def _normalize_address(value: str) -> str:
    address = value.strip().strip("[]")
    if "%" in address:
        address = address.split("%", 1)[0]
    if address.startswith("::ffff:"):
        address = address[len("::ffff:") :]
    return address


def _parse_endpoint(value: str) -> tuple[str, str]:
    endpoint = value.strip()
    if endpoint.startswith("[") and "]:" in endpoint:
        address, port = endpoint[1:].rsplit("]:", 1)
        return _normalize_address(address), port
    if ":" not in endpoint:
        return _normalize_address(endpoint), ""
    address, port = endpoint.rsplit(":", 1)
    return _normalize_address(address), port


def _parse_rate_bps(value: str) -> float:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMGT]?)(?:bps)", value)
    if match is None:
        raise ValueError(f"Unsupported rate format: {value}")

    amount = float(match.group(1))
    suffix = match.group(2)
    multipliers = {
        "": 1,
        "K": 1_000,
        "M": 1_000_000,
        "G": 1_000_000_000,
        "T": 1_000_000_000_000,
    }
    return amount * multipliers[suffix]


def _parse_socket_row(line: str):
    tokens = line.split()
    if not tokens or tokens[0] in {"State", "Recv-Q"}:
        return None

    if len(tokens) >= 4 and tokens[0].isdigit() and tokens[1].isdigit():
        return {
            "state": "",
            "recv_queue": float(tokens[0]),
            "send_queue": float(tokens[1]),
            "local_endpoint": tokens[2],
            "peer_endpoint": tokens[3],
        }

    if len(tokens) >= 5 and tokens[1].isdigit() and tokens[2].isdigit():
        return {
            "state": tokens[0],
            "recv_queue": float(tokens[1]),
            "send_queue": float(tokens[2]),
            "local_endpoint": tokens[3],
            "peer_endpoint": tokens[4],
        }

    return None


def _parse_tcp_detail_line(line: str) -> tuple[str, bool, dict[str, float]]:
    metric_values = {}
    congestion_algorithm = ""
    app_limited = False
    tokens = line.strip().split()
    index = 0
    direct_rate_metrics = {
        "send": "send_rate_bps",
        "pacing_rate": "pacing_rate_bps",
        "delivery_rate": "delivery_rate_bps",
    }
    direct_metrics = {
        "rto": "rto_milliseconds",
        "ato": "ato_milliseconds",
        "mss": "mss_bytes",
        "pmtu": "pmtu_bytes",
        "rcvmss": "rcvmss_bytes",
        "advmss": "advmss_bytes",
        "cwnd": "cwnd_segments",
        "bytes_sent": "bytes_sent",
        "bytes_acked": "bytes_acked",
        "bytes_received": "bytes_received",
        "bytes_retrans": "bytes_retransmitted_total",
        "segs_out": "segs_out",
        "segs_in": "segs_in",
        "data_segs_out": "data_segs_out",
        "data_segs_in": "data_segs_in",
        "lastsnd": "lastsnd_milliseconds",
        "lastrcv": "lastrcv_milliseconds",
        "lastack": "lastack_milliseconds",
        "delivered": "delivered",
        "rcv_rtt": "rcv_rtt_milliseconds",
        "rcv_space": "rcv_space_bytes",
        "rcv_ssthresh": "rcv_ssthresh_bytes",
        "minrtt": "min_rtt_milliseconds",
        "snd_wnd": "snd_wnd_bytes",
        "rcv_wnd": "rcv_wnd_bytes",
    }
    while index < len(tokens):
        token = tokens[index]
        if token == "app_limited":
            app_limited = True
            index += 1
            continue

        if token in direct_rate_metrics and index + 1 < len(tokens):
            metric_values[direct_rate_metrics[token]] = _parse_rate_bps(
                tokens[index + 1]
            )
            index += 2
            continue

        if ":" in token:
            key, value = token.split(":", 1)
            if key == "wscale":
                send_wscale, recv_wscale = value.split(",", 1)
                metric_values["send_wscale"] = float(send_wscale)
                metric_values["rcv_wscale"] = float(recv_wscale)
            elif key == "rtt":
                rtt, rttvar = value.split("/", 1)
                metric_values["rtt_milliseconds"] = float(rtt)
                metric_values["rttvar_milliseconds"] = float(rttvar)
            elif key == "retrans":
                _, retransmissions_total = value.split("/", 1)
                metric_values["retransmissions_total"] = float(retransmissions_total)
            elif key in direct_metrics:
                metric_values[direct_metrics[key]] = float(value)
            index += 1
            continue

        if not congestion_algorithm:
            congestion_algorithm = token
        index += 1

    return congestion_algorithm, app_limited, metric_values


@dataclass
class SocketSnapshot:
    local_address: str
    local_port: str
    peer_address: str
    peer_port: str
    recv_queue: float
    send_queue: float


@dataclass
class TCPSocketSnapshot(SocketSnapshot):
    state: str = ""
    congestion_algorithm: str = ""
    app_limited: bool = False
    metrics: dict[str, float] = field(default_factory=dict)


class SocketStatsCollector:
    def __init__(
        self,
        port,
        proto,
        runner=subprocess.run,
        ss_binary="ss",
        timeout=2,
    ):
        self.port = str(port)
        self.proto = proto
        self.runner = runner
        self.command = [ss_binary, "-tin" if proto == "tcp" else "-uin"]
        self.timeout = timeout
        self._availability_warning_sent = False
        self._execution_warning_sent = False
        self.error_counts = Counter()
        self.last_duration_seconds = 0.0
        self.last_success_timestamp_seconds = None

    def _record_duration(self, started_at: float) -> None:
        self.last_duration_seconds = time.monotonic() - started_at

    def _record_failure(self, started_at: float, reason: str) -> None:
        self._record_duration(started_at)
        self.error_counts[reason] += 1

    def collect(self):
        started_at = time.monotonic()
        try:
            result = self.runner(
                self.command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            self._record_failure(started_at, "unavailable")
            if not self._availability_warning_sent:
                log.warning(
                    f"Socket metrics are disabled because {' '.join(self.command)} is unavailable"
                )
                self._availability_warning_sent = True
            return {}
        except subprocess.TimeoutExpired:
            self._record_failure(started_at, "timeout")
            if not self._execution_warning_sent:
                log.warning(
                    "Socket metrics are disabled because %s timed out after %ss",
                    " ".join(self.command),
                    self.timeout,
                )
                self._execution_warning_sent = True
            return {}

        if result.returncode != 0:
            self._record_failure(started_at, "command")
            if not self._execution_warning_sent:
                stderr = (result.stderr or "").strip()
                log.warning(
                    f"Socket metrics are disabled because {' '.join(self.command)} failed: {stderr}"
                )
                self._execution_warning_sent = True
            return {}

        self._execution_warning_sent = False
        self._record_duration(started_at)
        self.last_success_timestamp_seconds = time.time()
        return self._parse_output(result.stdout)

    def health_snapshot(self) -> dict:
        return {
            "error_counts": dict(self.error_counts),
            "last_duration_seconds": self.last_duration_seconds,
            "last_success_timestamp_seconds": self.last_success_timestamp_seconds,
        }

    def _parse_output(self, raw_output: str):
        snapshots = {}
        lines = [line.rstrip("\n") for line in raw_output.splitlines()]
        index = 0
        while index < len(lines):
            row = _parse_socket_row(lines[index].strip())
            if row is None:
                index += 1
                continue

            local_address, local_port = _parse_endpoint(row["local_endpoint"])
            peer_address, peer_port = _parse_endpoint(row["peer_endpoint"])
            detail_line = None
            if self.proto == "tcp" and index + 1 < len(lines):
                next_line = lines[index + 1].strip()
                if next_line and _parse_socket_row(next_line) is None:
                    detail_line = next_line
                    index += 1

            index += 1
            if local_port != self.port:
                continue

            key = (local_address, local_port, peer_address, peer_port)
            if self.proto == "tcp":
                (
                    congestion_algorithm,
                    app_limited,
                    metric_values,
                ) = _parse_tcp_detail_line(detail_line or "")
                snapshots[key] = TCPSocketSnapshot(
                    local_address=local_address,
                    local_port=local_port,
                    peer_address=peer_address,
                    peer_port=peer_port,
                    recv_queue=row["recv_queue"],
                    send_queue=row["send_queue"],
                    state=row["state"],
                    congestion_algorithm=congestion_algorithm,
                    app_limited=app_limited,
                    metrics=metric_values,
                )
                continue

            snapshots[key] = SocketSnapshot(
                local_address=local_address,
                local_port=local_port,
                peer_address=peer_address,
                peer_port=peer_port,
                recv_queue=row["recv_queue"],
                send_queue=row["send_queue"],
            )

        return snapshots
