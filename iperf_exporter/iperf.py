from abc import ABC, abstractmethod
import subprocess
import time
import re
import os
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
    ):
        self.peer_id = peer_id
        self.local_address = local_address
        self.interface_name = interface_name
        self.local_port = local_port
        self.peer_address = peer_address
        self.peer_port = peer_port

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
netpwr = {self.netpwr}"""


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


class IPerfServer(IPerf):
    def __init__(self, port, proto, len, additional_params=""):
        super().__init__(port, proto, additional_params)
        self.len = len
        self.output = {}
        self._cmd()

    def _cmd(self):
        self._cmd = f"iperf --server --port {self.port} --enhanced --{self.proto} --len {self.len} --interval 1 --format b --utc {self.additional_params}"

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
            if line != "":
                self._raw_stdout = line.strip()
                self.parse_output()

    def parse_output(self):
        if self._raw_stdout:
            pattern = r"\[\s+(\d+)\]\s+(\d+\.\d+)-(\d+\.\d+) sec\s+([\d.]+ [KMGT]?Bytes)\s+([\d.]+ [KMGT]?bits/sec)\s+(\d+\.\d+ ms)\s+(\d+)/(\d+) \((\d+)%\)\s+(\d+\.\d+)/(\d+\.\d+)/(\d+\.\d+)/(\d+\.\d+) ms\s+(\d+ pps)\s+(\d+)"
            match = re.search(pattern, self._raw_stdout)

            if match:
                id = match.group(1)
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
            else:
                pattern = r"\[\s+(\d+)\] local (\d+\.\d+\.\d+\.\d+)%([a-zA-Z0-9]+) port (\d+) connected with (\d+\.\d+\.\d+\.\d+) port (\d+)"
                match = re.search(pattern, self._raw_stdout)
                if match:
                    id = match.group(1)
                    self.output[id] = IPerfServerUDPOutput(
                        peer_id=id,
                        local_address=match.group(2),
                        interface_name=match.group(3),
                        local_port=match.group(4),
                        peer_address=match.group(5),
                        peer_port=match.group(6),
                    )


if __name__ == "__main__":
    server = IPerfServer(5001, "udp", 1280)
    server.run()
    while True:
        server.read_output()
        print(f"{server._raw_stdout = }")
        time.sleep(1)
        out = str(server.output)
        print(out)
