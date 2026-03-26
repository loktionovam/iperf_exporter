import re
import subprocess
import time
from dataclasses import dataclass, field

from iperf_exporter.logger import log

TRACE_DIRECTION = "server_to_client"


@dataclass
class PathTraceHop:
    hop_index: int
    hop_address: str
    hop_summary: str


@dataclass
class PathTraceSnapshot:
    local_address: str
    local_port: str
    peer_address: str
    peer_port: str
    trace_direction: str = TRACE_DIRECTION
    success: bool = False
    pmtu_bytes: float | None = None
    hops_total: float | None = None
    hops: list[PathTraceHop] = field(default_factory=list)


@dataclass
class _CachedPathTrace:
    snapshot: PathTraceSnapshot
    expires_at: float


def _parse_hop_line(line: str) -> tuple[int, str, str] | None:
    match = re.match(r"^\s*(\d+):\s+(.*)$", line)
    if match is None:
        return None

    hop_index = int(match.group(1))
    hop_body = match.group(2).strip()
    if not hop_body:
        return None

    if hop_body.startswith("no reply"):
        return hop_index, "", "no reply"

    address_match = re.match(r"^([0-9A-Fa-f:.]+)\s*(.*)$", hop_body)
    if address_match:
        hop_address = address_match.group(1)
        hop_summary = address_match.group(2).strip() or "reached"
        return hop_index, hop_address, hop_summary

    return hop_index, "", hop_body


class PathTraceCollector:
    def __init__(
        self,
        proto,
        ttl=300,
        max_hops=16,
        timeout=10,
        runner=subprocess.run,
        tracepath_binary="tracepath",
        time_fn=time.monotonic,
    ):
        self.proto = proto
        self.ttl = max(int(ttl), 0)
        self.max_hops = int(max_hops)
        self.timeout = int(timeout)
        self.runner = runner
        self.tracepath_binary = tracepath_binary
        self.time_fn = time_fn
        self._cache: dict[tuple[str, str, str, str], _CachedPathTrace] = {}
        self._availability_warning_sent = False
        self._execution_warning_sent = False

    def collect(self, output):
        if self.ttl == 0:
            return {}

        now = self.time_fn()
        self._cache = {
            key: value for key, value in self._cache.items() if value.expires_at > now
        }

        snapshots = {}
        for out in output.values():
            key = (
                out.local_address,
                out.local_port,
                out.peer_address,
                out.peer_port,
            )
            cached = self._cache.get(key)
            if cached is not None:
                snapshots[key] = cached.snapshot
                continue

            snapshot = self._collect_for_output(out)
            if snapshot is None:
                continue

            snapshots[key] = snapshot
            self._cache[key] = _CachedPathTrace(snapshot, now + self.ttl)

        return snapshots

    def _build_command(self, out) -> list[str]:
        command = [
            self.tracepath_binary,
            "-n",
            "-m",
            str(self.max_hops),
        ]
        if out.peer_port:
            command.extend(["-p", str(out.peer_port)])
        command.append(out.peer_address)
        return command

    def _collect_for_output(self, out):
        command = self._build_command(out)
        try:
            result = self.runner(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            if not self._availability_warning_sent:
                log.warning(
                    f"Path trace is disabled because {self.tracepath_binary} is unavailable"
                )
                self._availability_warning_sent = True
            return None
        except subprocess.TimeoutExpired:
            if not self._execution_warning_sent:
                log.warning(
                    f"Path trace is disabled because {' '.join(command)} timed out after {self.timeout}s"
                )
                self._execution_warning_sent = True
            return None

        snapshot = self._parse_output(
            out.local_address,
            out.local_port,
            out.peer_address,
            out.peer_port,
            result.stdout or "",
        )
        if snapshot is None:
            if result.returncode != 0 and not self._execution_warning_sent:
                stderr = (result.stderr or "").strip()
                log.warning(
                    f"Path trace is disabled because {' '.join(command)} failed: {stderr}"
                )
                self._execution_warning_sent = True
            return None

        self._execution_warning_sent = False
        return snapshot

    def _parse_output(
        self,
        local_address: str,
        local_port: str,
        peer_address: str,
        peer_port: str,
        raw_output: str,
    ):
        pmtu_bytes = None
        hops_total = None
        success = False
        hops_by_index = {}

        for raw_line in raw_output.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            resume_match = re.match(r"^Resume:\s+pmtu\s+(\d+)\s+hops\s+(\d+)\b", line)
            if resume_match:
                pmtu_bytes = float(resume_match.group(1))
                hops_total = float(resume_match.group(2))
                continue

            local_pmtu_match = re.search(r"\bpmtu\s+(\d+)\b", line)
            if line.startswith("1?:") and local_pmtu_match:
                pmtu_bytes = float(local_pmtu_match.group(1))
                continue

            parsed_hop = _parse_hop_line(line)
            if parsed_hop is None:
                continue

            hop_index, hop_address, hop_summary = parsed_hop
            if "reached" in hop_summary:
                success = True
            hops_by_index[hop_index] = PathTraceHop(
                hop_index=hop_index,
                hop_address=hop_address,
                hop_summary=hop_summary,
            )

        if not hops_by_index and pmtu_bytes is None and hops_total is None:
            return None

        hops = [hops_by_index[index] for index in sorted(hops_by_index)]
        if hops_total is None and hops:
            hops_total = float(hops[-1].hop_index)

        return PathTraceSnapshot(
            local_address=local_address,
            local_port=local_port,
            peer_address=peer_address,
            peer_port=peer_port,
            success=success,
            pmtu_bytes=pmtu_bytes,
            hops_total=hops_total,
            hops=hops,
        )
