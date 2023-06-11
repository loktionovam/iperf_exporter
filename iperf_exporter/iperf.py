from abc import ABC, abstractmethod
import subprocess
import time
import re
import os
import asyncio
import threading
from iperf_exporter.logger import log


class IPerf(ABC):
    def __init__(
        self,
        port: int,
        proto: str,
        additional_params: str,
    ):
        self.port = port
        self.proto = proto
        self.additional_params = additional_params
        self.len = len
        self._process = None
        self._raw_stdout = None
        self._raw_stderr = None

    @abstractmethod
    def _cmd(self):
        pass

    @abstractmethod
    def run(self):
        pass

    @abstractmethod
    def read_output(self):
        pass


class IPerfServerUDPOutput:
    def __init__(
        self,
        peer_id: str,
        local_address: str,
        interface_name: str,
        local_port: str,
        peer_address: str,
        peer_port: str,
        metric_ttl=604800,
    ):
        self.peer_id = peer_id
        self.local_address = local_address
        self.interface_name = interface_name
        self.local_port = local_port
        self.peer_address = peer_address
        self.peer_port = peer_port
        self.metric_ttl = metric_ttl
        self.current_metric_ttl = self.metric_ttl

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
        self.interval_start = interval_start
        self.interval_end = interval_end

        # transfer Bytes
        self.transfer = transfer

        # bandwidth bits/s
        self.bandwidth = bandwidth
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
        self.reset_current_metric_ttl()

    def is_metric_ttl_exceeded(self):
        return self.current_metric_ttl == 0

    def reset_current_metric_ttl(self):
        self.current_metric_ttl = self.metric_ttl

    def decrease_current_metric_ttl(self):
        # FIXME: setup loglevel

        if self.current_metric_ttl > 0:
            self.current_metric_ttl -= 1
        else:
            log.debug(f"{self.peer_id = } is exceeded")

    def __iter__(self):
        for out in self.__dict__.items():
            yield out

    def __str__(self):
        return f"""
peer_id = {self.peer_id}
local_address = {self.local_address}
interface_name = {self.interface_name}
local_port = {self.local_port}
peer_address = {self.peer_address}
peer_port = {self.peer_port}
interval_start = {self.interval_start}
interval_end = {self.interval_end}
transfer = {self.transfer}
bandwidth = {self.bandwidth}
jitter = {self.jitter}
lost = {self.lost}
total = {self.total}
lost_percentage = {self.lost_percentage}
latency_avg = {self.latency_avg}
latency_min = {self.latency_min}
latency_max = {self.latency_max}
latency_stdev = {self.latency_stdev}
pps = {self.pps}
netpwr = {self.netpwr}
metric_ttl = {self.metric_ttl}
current_metric_ttl = {self.current_metric_ttl}"""


class IPerfClient(IPerf):
    def __init__(self, port, proto, bandwidth, peer, additional_params=""):
        super().__init__(port, proto, additional_params)
        self.bandwidth = bandwidth
        self.peer = peer
        self._cmd()

    def _cmd(self):
        self._cmd = f"iperf --client {self.peer} --interval 1 --port {self.port} --enhanced --{self.proto} --bandwidth {self.bandwidth} -t 315360000  --utc {self.additional_params}"

    def run(self):
        self._process = subprocess.Popen(
            self._cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True,
        )
        os.set_blocking(self._process.stdout.fileno(), False)
        self.start_time = time.time()

    def read_output(self):
        for line in self._process.stdout.readlines():
            log.info(line)


class IPerfParser:
    def __init__(self, entry):
        self.entry = entry
        self.pattern = ""

    def match(self):
        return re.search(self.pattern, self.entry)


class IPerfParserUsualEntry(IPerfParser):
    def __init__(self, entry):
        super().__init__(entry)
        self.pattern = r"\[\s+(\d+)\]\s+(\d+\.\d+)-(\d+\.\d+) sec\s+([\d.]+ [KMGT]?Bytes)\s+([\d.]+ [KMGT]?bits/sec)\s+([\d.]+ ms)\s+(\d+)/(\d+) \((\d+)%\)\s+([-]?[\d.]+)/([-]?[\d.]+)/([-]?[\d.]+)/([-]?[\d.]+) ms\s+(\d+ pps)\s+([-]?[\d.]+)"


class IPerfParserNewConnection(IPerfParser):
    def __init__(self, entry):
        super().__init__(entry)
        self.pattern = r"\[\s+(\d+)\] local (\d+\.\d+\.\d+\.\d+)%([a-zA-Z0-9]+) port (\d+) connected with (\d+\.\d+\.\d+\.\d+) port (\d+)"


class IPerfServer(IPerf):
    def __init__(self, port, proto, len, metric_ttl, additional_params=""):
        super().__init__(port, proto, additional_params)
        self.len = len
        self.metric_ttl = metric_ttl
        self.output = {}
        self._stop_cleanup = threading.Event()
        self._lock = threading.Lock()
        self._cmd()

    def _cmd(self):
        self._cmd = f"iperf --server --port {self.port} --enhanced --{self.proto} --len {self.len} --interval 1 --format b --utc {self.additional_params}"

    def run(self):
        if self._process is None:
            self._process = subprocess.Popen(
                self._cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                universal_newlines=True,
            )
        os.set_blocking(self._process.stdout.fileno(), False)
        self.start_time = time.time()
        self.loop = asyncio.new_event_loop()
        self.cleanup_thread = threading.Thread(target=self.start_async_loop)
        self.cleanup_thread.start()

    def stop(self):
        self._stop_cleanup.set()

    def read_output(self):
        for line in self._process.stdout.readlines():
            log.debug(line)
            if line != "":
                self._raw_stdout = line.strip()
                self.parse_output()

    async def periodically_remove_dead_clients(self, startup_delay=5):
        await asyncio.sleep(startup_delay)
        while True:
            if self._stop_cleanup.is_set():
                break

            self._lock.acquire()
            try:
                alive_metrics = {}
                for id, value in self.output.items():
                    self.output[id].decrease_current_metric_ttl()
                    if not self.output[id].is_metric_ttl_exceeded():
                        alive_metrics[id] = value
                removed_peer_ids = set(self.output.keys()) - set(alive_metrics.keys())
                if removed_peer_ids:
                    log.info(f"Removed peer ids: {removed_peer_ids = }")

                self.output = alive_metrics
            finally:
                self._lock.release()
            await asyncio.sleep(1)

    def start_async_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.periodically_remove_dead_clients())

    def parse_output(self):
        if self._raw_stdout:
            match = IPerfParserUsualEntry(self._raw_stdout).match()
            if match:
                id = match.group(1)
                self._lock.acquire()
                try:
                    self.output[id].update(
                        interval_start=match.group(2),
                        interval_end=match.group(3),
                        transfer=match.group(4).split()[0],
                        bandwidth=match.group(5).split()[0],
                        jitter=match.group(6).split()[0],
                        lost=match.group(7),
                        total=match.group(8),
                        lost_percentage=match.group(9),
                        latency_avg=match.group(10),
                        latency_min=match.group(11),
                        latency_max=match.group(12),
                        latency_stdev=match.group(13),
                        pps=match.group(14).split()[0],
                        netpwr=match.group(15),
                    )
                except KeyError:
                    log.error(f"Can't update metric {id = } because it doesn't exist")
                finally:
                    self._lock.release()

            else:
                match = IPerfParserNewConnection(self._raw_stdout).match()
                if match:
                    id = match.group(1)
                    log.info(f"Found new client {id = }")
                    self._lock.acquire()
                    try:
                        self.output[id] = IPerfServerUDPOutput(
                            peer_id=id,
                            local_address=match.group(2),
                            interface_name=match.group(3),
                            local_port=match.group(4),
                            peer_address=match.group(5),
                            peer_port=match.group(6),
                            metric_ttl=self.metric_ttl,
                        )
                    finally:
                        self._lock.release()


if __name__ == "__main__":
    server = IPerfServer(5001, "udp", 1280)
    server.run()
    while True:
        server.read_output()
        print(f"{server._raw_stdout = }")
        time.sleep(1)
        out = str(server.output)
        print(out)
