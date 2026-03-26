import asyncio
import os
import re
import shlex
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from iperf_exporter.logger import log

SUPPORTED_PROTOCOLS = ("udp", "tcp")


def _ensure_non_blocking(stream) -> None:
    if stream is None or not hasattr(stream, "fileno"):
        return

    try:
        os.set_blocking(stream.fileno(), False)
    except (AttributeError, OSError, ValueError):
        # Some test doubles and regular files do not support non-blocking mode.
        return


def _protocol_args(proto: str) -> list[str]:
    if proto == "udp":
        return ["--udp"]
    if proto == "tcp":
        return []
    raise ValueError(f"Unsupported iperf protocol: {proto}")


def _split_additional_params(params: str) -> list[str]:
    return shlex.split(params) if params else []


def _has_positive_numeric_prefix(value) -> bool:
    if value in (None, ""):
        return False

    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)", str(value))
    if match is None:
        return True

    return float(match.group(1)) > 0


def _parse_iperf_size_to_bytes(value: str) -> float:
    parts = value.strip().split()
    if len(parts) == 1:
        return float(parts[0])

    amount = float(parts[0])
    unit = parts[1]
    multipliers = {
        "Byte": 1,
        "Bytes": 1,
        "KByte": 1024,
        "KBytes": 1024,
        "MByte": 1024**2,
        "MBytes": 1024**2,
        "GByte": 1024**3,
        "GBytes": 1024**3,
        "TByte": 1024**4,
        "TBytes": 1024**4,
    }
    return amount * multipliers[unit]


def _parse_iperf_histogram_width_to_seconds(value: str) -> float:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(u|m)?s?", value.strip())
    if match is None:
        raise ValueError(f"Unsupported histogram width format: {value}")

    amount = float(match.group(1))
    suffix = match.group(2)
    if suffix == "u":
        return amount / 1_000_000
    if suffix == "m" or suffix is None:
        return amount / 1_000
    raise ValueError(f"Unsupported histogram width suffix: {value}")


def _parse_reads_distribution(distribution: str | None) -> list[int]:
    if not distribution:
        return [0] * 8

    values = [int(value) for value in distribution.split(":")]
    if len(values) < 8:
        values.extend([0] * (8 - len(values)))
    return values[:8]


def _parse_histogram_bins(raw_bins: str) -> list[tuple[int, int]]:
    bins = []
    for entry in raw_bins.split(","):
        bucket, count = entry.split(":")
        bins.append((int(bucket), int(count)))
    return bins


def _stringify_numeric(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _parse_udp_latency_field(value: str) -> tuple[str, str, str, str] | None:
    latency_value = value.strip()
    if latency_value.endswith(" ms"):
        latency_value = latency_value[:-3]

    parts = latency_value.split("/")
    if len(parts) != 4 or any(part == "-" for part in parts):
        return None

    return tuple(parts)


def _extract_trailing_numeric_value(value: str | None) -> str | None:
    if not value:
        return None

    last_token = value.strip().split()[-1]
    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)", last_token):
        return last_token

    return None


def _parse_connection_metadata(value: str | None) -> dict[str, str]:
    metadata = {
        "peer_version": "",
        "trip_times_enabled": "false",
        "initial_cwnd_segments": "",
        "initial_mss_bytes": "",
        "initial_rtt_microseconds": "",
    }
    if not value:
        return metadata

    connection_suffix = value.split(" on ", 1)[0]
    if "(trip-times)" in connection_suffix:
        metadata["trip_times_enabled"] = "true"

    peer_version_match = re.search(r"\(peer ([^)]+)\)", connection_suffix)
    if peer_version_match:
        metadata["peer_version"] = peer_version_match.group(1)

    init_stats_match = re.search(
        r"\(icwnd/mss/irtt=(\d+)/(\d+)/(\d+)\)",
        connection_suffix,
    )
    if init_stats_match:
        metadata["initial_cwnd_segments"] = init_stats_match.group(1)
        metadata["initial_mss_bytes"] = init_stats_match.group(2)
        metadata["initial_rtt_microseconds"] = init_stats_match.group(3)

    return metadata


class IPerf(ABC):
    def __init__(
        self,
        port: int,
        proto: str,
        additional_params: str,
        process_factory=subprocess.Popen,
    ):
        if proto not in SUPPORTED_PROTOCOLS:
            raise ValueError(f"Unsupported iperf protocol: {proto}")

        self.port = int(port)
        self.proto = proto
        self.additional_params = additional_params
        self.process_factory = process_factory
        self.command = self.build_command()
        self._process = None
        self._process_lock = threading.Lock()
        self._raw_stdout = None
        self._raw_stderr = None
        self.start_time = None
        self.last_exit_code = None
        self.last_restart_time = None
        self.restart_count = 0

    @abstractmethod
    def build_command(self) -> list[str]:
        pass

    @abstractmethod
    def run(self):
        pass

    @abstractmethod
    def read_output(self):
        pass

    def _close_process_streams(self, process) -> None:
        for stream_name in ("stdout", "stderr"):
            stream = getattr(process, stream_name, None)
            if stream is None or not hasattr(stream, "close"):
                continue
            try:
                stream.close()
            except OSError:
                log.debug(f"Failed to close iperf {stream_name} cleanly")

    def _spawn_process(self):
        self._process = self.process_factory(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True,
        )
        _ensure_non_blocking(getattr(self._process, "stdout", None))
        _ensure_non_blocking(getattr(self._process, "stderr", None))
        self.start_time = time.time()
        return self._process

    def _start_process(self):
        self.ensure_running()
        return self._process

    def ensure_running(self) -> bool:
        with self._process_lock:
            if self._process is None:
                self._spawn_process()
                return True

            if not hasattr(self._process, "poll"):
                return False

            exit_code = self._process.poll()
            if exit_code is None:
                return False

            self.last_exit_code = exit_code
            self.restart_count += 1
            self.last_restart_time = time.time()
            log.warning(
                f"Iperf {self.proto} process exited with code {exit_code}, restarting"
            )
            self._close_process_streams(self._process)
            self._process = None
            self._spawn_process()
            return True

    def is_running(self) -> bool:
        with self._process_lock:
            return self._process is not None and (
                not hasattr(self._process, "poll") or self._process.poll() is None
            )


@dataclass
class IPerfServerPeerOutput:
    peer_id: str
    local_address: str
    interface_name: str
    local_port: str
    peer_address: str
    peer_port: str
    metric_ttl: int = 604800
    current_metric_ttl: int = field(init=False)
    interval_start: str | None = None
    interval_end: str | None = None
    transfer: str | None = None
    bandwidth: str | None = None
    peer_version: str = ""
    trip_times_enabled: str = "false"
    initial_cwnd_segments: str = ""
    initial_mss_bytes: str = ""
    initial_rtt_microseconds: str = ""

    def __post_init__(self):
        self.current_metric_ttl = self.metric_ttl

    def update_common(
        self,
        interval_start: str,
        interval_end: str,
        transfer: str,
        bandwidth: str,
    ) -> None:
        self.interval_start = interval_start
        self.interval_end = interval_end
        self.transfer = transfer
        self.bandwidth = bandwidth
        self.reset_current_metric_ttl()

    def is_metric_ttl_exceeded(self):
        return self.current_metric_ttl == 0

    def reset_current_metric_ttl(self):
        self.current_metric_ttl = self.metric_ttl

    def decrease_current_metric_ttl(self):
        if self.current_metric_ttl > 0:
            self.current_metric_ttl -= 1
        else:
            log.debug(f"{self.peer_id = } is exceeded")

    def update_connection_metadata(self, **kwargs) -> None:
        for name, value in kwargs.items():
            if hasattr(self, name) and value is not None:
                setattr(self, name, value)

    def __iter__(self):
        for out in self.__dict__.items():
            yield out


@dataclass
class IPerfServerUDPOutput(IPerfServerPeerOutput):
    jitter: str | None = None
    lost: str | None = None
    total: str | None = None
    lost_percentage: str | None = None
    latency_avg: str | None = None
    latency_min: str | None = None
    latency_max: str | None = None
    latency_stdev: str | None = None
    pps: str | None = None
    netpwr: str | None = None

    def update(
        self,
        interval_start: str,
        interval_end: str,
        transfer: str,
        bandwidth: str,
        jitter: str,
        lost: str,
        total: str,
        lost_percentage: str,
        latency_avg: str,
        latency_min: str,
        latency_max: str,
        latency_stdev: str,
        pps: str,
        netpwr: str,
    ) -> None:
        self.update_common(interval_start, interval_end, transfer, bandwidth)
        self.jitter = jitter
        self.lost = lost
        self.total = total
        self.lost_percentage = lost_percentage
        self.latency_avg = latency_avg
        self.latency_min = latency_min
        self.latency_max = latency_max
        self.latency_stdev = latency_stdev
        self.pps = pps
        self.netpwr = netpwr


@dataclass
class IPerfServerTCPOutput(IPerfServerPeerOutput):
    reads: str | None = None
    burst_latency_avg: str | None = None
    burst_latency_min: str | None = None
    burst_latency_max: str | None = None
    burst_latency_stdev: str | None = None
    burst_count: str | None = None
    burst_size: str | None = None
    inprogress_bytes: str | None = None
    netpwr: str | None = None
    read_bin_0: str | None = None
    read_bin_1: str | None = None
    read_bin_2: str | None = None
    read_bin_3: str | None = None
    read_bin_4: str | None = None
    read_bin_5: str | None = None
    read_bin_6: str | None = None
    read_bin_7: str | None = None

    def update(
        self,
        interval_start: str,
        interval_end: str,
        transfer: str,
        bandwidth: str,
        reads: str,
        reads_distribution: str | None = None,
        burst_latency_avg: str | None = None,
        burst_latency_min: str | None = None,
        burst_latency_max: str | None = None,
        burst_latency_stdev: str | None = None,
        burst_count: str | None = None,
        burst_size: str | None = None,
        inprogress_bytes: str | None = None,
        netpwr: str | None = None,
    ) -> None:
        self.update_common(interval_start, interval_end, transfer, bandwidth)
        self.reads = reads
        self.burst_latency_avg = burst_latency_avg
        self.burst_latency_min = burst_latency_min
        self.burst_latency_max = burst_latency_max
        self.burst_latency_stdev = burst_latency_stdev
        self.burst_count = burst_count
        self.burst_size = burst_size
        self.inprogress_bytes = inprogress_bytes
        self.netpwr = netpwr

        for index, value in enumerate(_parse_reads_distribution(reads_distribution)):
            setattr(self, f"read_bin_{index}", str(value))


@dataclass
class IPerfServerTCPHistogramOutput:
    peer_id: str
    local_address: str
    interface_name: str
    local_port: str
    peer_address: str
    peer_port: str
    histogram_name: str
    bin_width_seconds: float
    sample_count: int
    bins: list[tuple[int, int]]


@dataclass
class IPerfServerRuntimeSettings:
    listen_port: str
    server_pid: str = ""
    datagram_size_bytes: str = ""
    udp_buffer_bytes: str = ""
    read_buffer_bytes: str = ""
    read_dist_bin_width_bytes: str = ""
    tcp_window_bytes: str = ""
    congestion_control_default: str = ""
    histogram_bin_width_ms: str = ""
    histogram_bin_count: str = ""


class IPerfClient(IPerf):
    def __init__(
        self,
        port,
        proto,
        bandwidth,
        peer,
        additional_params="",
        process_factory=subprocess.Popen,
    ):
        self.bandwidth = bandwidth
        self.peer = peer
        super().__init__(
            port, proto, additional_params, process_factory=process_factory
        )

    def build_command(self) -> list[str]:
        command = [
            "iperf",
            "--client",
            self.peer,
            "--interval",
            "1",
            "--port",
            str(self.port),
            "--enhanced",
            "-t",
            "315360000",
            "--utc",
        ]
        command.extend(_protocol_args(self.proto))
        if self.proto == "udp" and self.bandwidth not in (None, ""):
            command.extend(["--bandwidth", str(self.bandwidth)])
        elif self.proto == "tcp" and _has_positive_numeric_prefix(self.bandwidth):
            command.extend(["--bandwidth", str(self.bandwidth)])
        command.extend(_split_additional_params(self.additional_params))
        return command

    def run(self):
        return self._start_process()

    def read_output(self):
        lines = []
        with self._process_lock:
            if self._process is None or getattr(self._process, "stdout", None) is None:
                return lines

            for line in self._process.stdout.readlines():
                stripped_line = line.strip()
                if stripped_line:
                    log.info(stripped_line)
                    lines.append(stripped_line)
        return lines


class IPerfParser:
    def __init__(self, entry):
        self.entry = entry
        self.pattern = ""

    def match(self):
        return re.search(self.pattern, self.entry)


class IPerfParserUsualUDPEntry(IPerfParser):
    def __init__(self, entry):
        super().__init__(entry)
        self.pattern = (
            r"^\[\s*(\d+)\]\s+(\d+\.\d+)-(\d+\.\d+) sec\s+"
            r"([\d.]+ [KMGT]?Bytes)\s+([\d.]+ [KMGT]?bits/sec)\s+"
            r"([\d.]+ ms)\s+(\d+)/(\d+) \(([\d.]+)%\)\s+"
            r"((?:-|[-]?[\d.]+)/(?:-|[-]?[\d.]+)/(?:-|[-]?[\d.]+)/(?:-|[-]?[\d.]+) ms)\s+"
            r"(\d+) pps"
            r"(?:\s+(.*?))?$"
        )


class IPerfParserUsualTCPEntry(IPerfParser):
    def __init__(self, entry):
        super().__init__(entry)
        self.pattern = (
            r"^\[\s*(\d+)\]\s+(\d+\.\d+)-(\d+\.\d+) sec\s+"
            r"([\d.]+ [KMGT]?Bytes)\s+([\d.]+ [KMGT]?bits/sec)\s+"
            r"(\d+)(?:=([0-9:]+))?$"
        )


class IPerfParserTripTimesTCPEntry(IPerfParser):
    def __init__(self, entry):
        super().__init__(entry)
        self.pattern = (
            r"^\[\s*(\d+)\]\s+(\d+\.\d+)-(\d+\.\d+) sec\s+"
            r"([\d.]+ [KMGT]?Bytes?)\s+([\d.]+ [KMGT]?bits/sec)\s+"
            r"([-]?[\d.]+)/([-]?[\d.]+)/([-]?[\d.]+)/([-]?[\d.]+) ms\s+"
            r"\((\d+)/(\d+)\)\s+"
            r"([\d.]+ [KMGT]?Bytes?)\s+"
            r"([-]?[\d.]+)\s+"
            r"(\d+)(?:=([0-9:]+))?$"
        )


class IPerfParserTCPHistogramEntry(IPerfParser):
    def __init__(self, entry):
        super().__init__(entry)
        self.pattern = (
            r"^\[\s*(\d+)\]\s+(\d+\.\d+)-(\d+\.\d+) sec\s+"
            r"([^\s]+)-PDF:\s+bin\(w=([0-9.]+(?:u|m)?s?)\):cnt\((\d+)\)=([0-9:,]+)"
        )


class IPerfParserNewConnection(IPerfParser):
    def __init__(self, entry):
        super().__init__(entry)
        self.pattern = (
            r"^\[\s*(\d+)\]\s+local\s+([^\s%]+)(?:%([^\s]+))?\s+port\s+(\d+)\s+"
            r"connected with\s+([^\s]+)\s+port\s+(\d+)(?:\s+(.*))?$"
        )


class IPerfServer(IPerf):
    def __init__(
        self,
        port,
        proto,
        len,
        metric_ttl,
        additional_params="",
        process_factory=subprocess.Popen,
        cleanup_startup_delay=5,
        cleanup_interval=1,
        watchdog_interval=1,
    ):
        self.len = int(len)
        self.metric_ttl = int(metric_ttl)
        self.cleanup_startup_delay = cleanup_startup_delay
        self.cleanup_interval = cleanup_interval
        self.watchdog_interval = watchdog_interval
        self.output = {}
        self.tcp_histograms = {}
        self.runtime_settings = IPerfServerRuntimeSettings(listen_port=str(port))
        self._stop_cleanup = threading.Event()
        self._lock = threading.Lock()
        self._loop = None
        self.cleanup_thread = None
        self.watchdog_thread = None
        super().__init__(
            port, proto, additional_params, process_factory=process_factory
        )
        self.output_cls = (
            IPerfServerUDPOutput if self.proto == "udp" else IPerfServerTCPOutput
        )
        self.entry_parser_cls = (
            IPerfParserUsualUDPEntry
            if self.proto == "udp"
            else IPerfParserUsualTCPEntry
        )

    def build_command(self) -> list[str]:
        command = [
            "iperf",
            "--server",
            "--port",
            str(self.port),
            "--enhanced",
            "--len",
            str(self.len),
            "--interval",
            "1",
            "--format",
            "b",
            "--utc",
        ]
        command.extend(_protocol_args(self.proto))
        command.extend(_split_additional_params(self.additional_params))
        return command

    def run(self):
        self.ensure_running()
        if self.cleanup_thread is None or not self.cleanup_thread.is_alive():
            self._stop_cleanup.clear()
            self._loop = asyncio.new_event_loop()
            self.cleanup_thread = threading.Thread(
                target=self.start_async_loop,
                daemon=True,
            )
            self.cleanup_thread.start()
        if self.watchdog_thread is None or not self.watchdog_thread.is_alive():
            self.watchdog_thread = threading.Thread(
                target=self.watch_process,
                daemon=True,
            )
            self.watchdog_thread.start()
        return self._process

    def stop(self):
        self._stop_cleanup.set()

        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: None)

        if self.cleanup_thread is not None and self.cleanup_thread.is_alive():
            self.cleanup_thread.join(timeout=2)

        if self.watchdog_thread is not None and self.watchdog_thread.is_alive():
            self.watchdog_thread.join(timeout=2)

        with self._process_lock:
            if self._process is not None and hasattr(self._process, "poll"):
                try:
                    if self._process.poll() is None and hasattr(
                        self._process, "terminate"
                    ):
                        self._process.terminate()
                except OSError:
                    log.debug("Failed to terminate iperf server process cleanly")
            if self._process is not None:
                self._close_process_streams(self._process)

    def read_output(self):
        with self._process_lock:
            if self._process is None or getattr(self._process, "stdout", None) is None:
                return

            for line in self._process.stdout.readlines():
                log.debug(line)
                if line:
                    self._raw_stdout = line.strip()
                    self.parse_output()

    def watch_process(self):
        while not self._stop_cleanup.is_set():
            self.ensure_running()
            if self._stop_cleanup.wait(self.watchdog_interval):
                break

    async def periodically_remove_dead_clients(self):
        await asyncio.sleep(self.cleanup_startup_delay)
        while not self._stop_cleanup.is_set():
            with self._lock:
                alive_metrics = {}
                for peer_id, value in self.output.items():
                    value.decrease_current_metric_ttl()
                    if not value.is_metric_ttl_exceeded():
                        alive_metrics[peer_id] = value

                removed_peer_ids = set(self.output.keys()) - set(alive_metrics.keys())
                if removed_peer_ids:
                    log.info(f"Removed peer ids: {removed_peer_ids = }")

                self.output = alive_metrics
                if self.tcp_histograms:
                    self.tcp_histograms = {
                        key: value
                        for key, value in self.tcp_histograms.items()
                        if value.peer_id in alive_metrics
                    }
            await asyncio.sleep(self.cleanup_interval)

    def start_async_loop(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self.periodically_remove_dead_clients())
        finally:
            self._loop.close()

    def parse_runtime_settings(self) -> bool:
        server_listening_match = re.match(
            r"^Server listening on (?:TCP|UDP) port (\d+)(?: with pid (\d+))?$",
            self._raw_stdout,
        )
        if server_listening_match:
            self.runtime_settings.listen_port = server_listening_match.group(1)
            self.runtime_settings.server_pid = server_listening_match.group(2) or ""
            return True

        receiving_match = re.match(
            r"^Receiving (\d+) byte datagrams$",
            self._raw_stdout,
        )
        if receiving_match:
            self.runtime_settings.datagram_size_bytes = receiving_match.group(1)
            return True

        udp_buffer_match = re.match(
            r"^UDP buffer size:\s+([\d.]+ [KMGT]?Bytes?)",
            self._raw_stdout,
        )
        if udp_buffer_match:
            self.runtime_settings.udp_buffer_bytes = _stringify_numeric(
                _parse_iperf_size_to_bytes(udp_buffer_match.group(1))
            )
            return True

        read_buffer_match = re.match(
            r"^Read buffer size:\s*([\d.]+ [KMGT]?Bytes?) \(Dist bin width=([\d.]+ [KMGT]?Bytes?)\)$",
            self._raw_stdout,
        )
        if read_buffer_match:
            self.runtime_settings.read_buffer_bytes = _stringify_numeric(
                _parse_iperf_size_to_bytes(read_buffer_match.group(1))
            )
            self.runtime_settings.read_dist_bin_width_bytes = _stringify_numeric(
                _parse_iperf_size_to_bytes(read_buffer_match.group(2))
            )
            return True

        congestion_match = re.match(
            r"^TCP congestion control default(?: set to)?\s+([^\s]+)",
            self._raw_stdout,
        )
        if congestion_match:
            self.runtime_settings.congestion_control_default = congestion_match.group(1)
            return True

        tcp_window_match = re.match(
            r"^TCP window size:\s+([\d.]+ [KMGT]?Bytes?)",
            self._raw_stdout,
        )
        if tcp_window_match:
            self.runtime_settings.tcp_window_bytes = _stringify_numeric(
                _parse_iperf_size_to_bytes(tcp_window_match.group(1))
            )
            return True

        histogram_match = re.match(
            r"^Enabled receive histograms bin-width=([0-9.]+) ms, bins=(\d+)",
            self._raw_stdout,
        )
        if histogram_match:
            self.runtime_settings.histogram_bin_width_ms = histogram_match.group(1)
            self.runtime_settings.histogram_bin_count = histogram_match.group(2)
            return True

        return False

    def parse_output(self):
        if not self._raw_stdout:
            return
        if self.parse_runtime_settings():
            return
        if self._raw_stdout.endswith("(omitted)"):
            log.debug(f"Ignoring omitted iperf line: {self._raw_stdout}")
            return

        if self.proto == "udp":
            match = self.entry_parser_cls(self._raw_stdout).match()
            if match:
                peer_id = match.group(1).strip()
                latency_values = _parse_udp_latency_field(match.group(10))
                netpwr = _extract_trailing_numeric_value(match.group(12))
                if latency_values is None or netpwr is None:
                    log.debug(
                        f"Ignoring unsupported UDP report line: {self._raw_stdout}"
                    )
                    return
                with self._lock:
                    try:
                        self.output[peer_id].update(
                            interval_start=match.group(2),
                            interval_end=match.group(3),
                            transfer=match.group(4).split()[0],
                            bandwidth=match.group(5).split()[0],
                            jitter=match.group(6).split()[0],
                            lost=match.group(7),
                            total=match.group(8),
                            lost_percentage=match.group(9),
                            latency_avg=latency_values[0],
                            latency_min=latency_values[1],
                            latency_max=latency_values[2],
                            latency_stdev=latency_values[3],
                            pps=match.group(11),
                            netpwr=netpwr,
                        )
                    except (KeyError, ValueError, IndexError):
                        log.error(
                            f"Can't update metric {peer_id = } because it doesn't exist"
                        )
                return
        else:
            trip_times_match = IPerfParserTripTimesTCPEntry(self._raw_stdout).match()
            if trip_times_match:
                peer_id = trip_times_match.group(1).strip()
                with self._lock:
                    try:
                        self.output[peer_id].update(
                            interval_start=trip_times_match.group(2),
                            interval_end=trip_times_match.group(3),
                            transfer=_stringify_numeric(
                                _parse_iperf_size_to_bytes(trip_times_match.group(4))
                            ),
                            bandwidth=trip_times_match.group(5).split()[0],
                            reads=trip_times_match.group(14),
                            reads_distribution=trip_times_match.group(15),
                            burst_latency_avg=trip_times_match.group(6),
                            burst_latency_min=trip_times_match.group(7),
                            burst_latency_max=trip_times_match.group(8),
                            burst_latency_stdev=trip_times_match.group(9),
                            burst_count=trip_times_match.group(10),
                            burst_size=trip_times_match.group(11),
                            inprogress_bytes=_stringify_numeric(
                                _parse_iperf_size_to_bytes(trip_times_match.group(12))
                            ),
                            netpwr=trip_times_match.group(13),
                        )
                    except (KeyError, ValueError, IndexError):
                        log.error(
                            f"Can't update metric {peer_id = } because it doesn't exist"
                        )
                return

            histogram_match = IPerfParserTCPHistogramEntry(self._raw_stdout).match()
            if histogram_match:
                peer_id = histogram_match.group(1).strip()
                with self._lock:
                    try:
                        peer_output = self.output[peer_id]
                        histogram_name = histogram_match.group(4)
                        self.tcp_histograms[
                            f"{peer_id}:{histogram_name}"
                        ] = IPerfServerTCPHistogramOutput(
                            peer_id=peer_id,
                            local_address=peer_output.local_address,
                            interface_name=peer_output.interface_name,
                            local_port=peer_output.local_port,
                            peer_address=peer_output.peer_address,
                            peer_port=peer_output.peer_port,
                            histogram_name=histogram_name,
                            bin_width_seconds=_parse_iperf_histogram_width_to_seconds(
                                histogram_match.group(5)
                            ),
                            sample_count=int(histogram_match.group(6)),
                            bins=_parse_histogram_bins(histogram_match.group(7)),
                        )
                    except KeyError:
                        log.error(
                            f"Can't update tcp histogram {peer_id = } because it doesn't exist"
                        )
                        return
                    except ValueError:
                        log.warning(
                            f"Can't parse tcp histogram line safely: {self._raw_stdout}"
                        )
                return

            match = self.entry_parser_cls(self._raw_stdout).match()
            if match:
                peer_id = match.group(1).strip()
                with self._lock:
                    try:
                        self.output[peer_id].update(
                            interval_start=match.group(2),
                            interval_end=match.group(3),
                            transfer=match.group(4).split()[0],
                            bandwidth=match.group(5).split()[0],
                            reads=match.group(6),
                            reads_distribution=match.group(7),
                        )
                    except (KeyError, ValueError, IndexError):
                        log.error(
                            f"Can't update metric {peer_id = } because it doesn't exist"
                        )
                return

        match = IPerfParserNewConnection(self._raw_stdout).match()
        if not match:
            return

        peer_id = match.group(1).strip()
        log.info(f"Found new client {peer_id = }")
        connection_metadata = _parse_connection_metadata(match.group(7))
        with self._lock:
            self.output[peer_id] = self.output_cls(
                peer_id=peer_id,
                local_address=match.group(2),
                interface_name=match.group(3) or "",
                local_port=match.group(4),
                peer_address=match.group(5),
                peer_port=match.group(6),
                metric_ttl=self.metric_ttl,
                **connection_metadata,
            )


if __name__ == "__main__":
    server = IPerfServer(5001, "udp", 1280, 604800)
    server.run()
    while True:
        server.read_output()
        print(f"{server._raw_stdout = }")
        time.sleep(1)
        print(str(server.output))
