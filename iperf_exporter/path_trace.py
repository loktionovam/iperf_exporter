import re
import subprocess
import threading
import time
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace

from iperf_exporter.logger import log

TRACE_DIRECTION = "server_to_client"


@dataclass
class PathTraceHop:
    hop_index: int
    hop_address: str


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


@dataclass(frozen=True)
class _TraceTarget:
    local_address: str
    local_port: str
    peer_address: str
    peer_port: str


@dataclass
class _CachedPathTrace:
    snapshot: PathTraceSnapshot
    refresh_after: float


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
        return hop_index, address_match.group(1), address_match.group(2).strip()

    return hop_index, "", hop_body


class PathTraceCollector:
    def __init__(
        self,
        proto,
        ttl=300,
        max_hops=16,
        timeout=10,
        runner=None,
        process_factory=subprocess.Popen,
        tracepath_binary="tracepath",
        time_fn=time.monotonic,
    ):
        self.proto = proto
        self.ttl = max(int(ttl), 0)
        self.max_hops = int(max_hops)
        self.timeout = int(timeout)
        self.process_factory = process_factory
        self._uses_internal_runner = runner is None
        self.runner = runner or self._run_trace_command
        self.tracepath_binary = tracepath_binary
        self.time_fn = time_fn
        self._cache: dict[tuple[str, str], _CachedPathTrace] = {}
        self._in_flight: dict[tuple[str, str], Future] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="iperf-path-trace",
        )
        self._lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._active_process = None
        self._closed = threading.Event()
        self._availability_warning_sent = False
        self._execution_warning_sent = False
        self._error_counts = Counter()
        self._last_duration_seconds = 0.0
        self._last_success_timestamp_seconds = None

    @staticmethod
    def _target(out) -> _TraceTarget:
        return _TraceTarget(
            local_address=out.local_address,
            local_port=out.local_port,
            peer_address=out.peer_address,
            peer_port=out.peer_port,
        )

    @staticmethod
    def _pair_key(target: _TraceTarget) -> tuple[str, str]:
        return target.local_address, target.peer_address

    @staticmethod
    def _socket_key(target: _TraceTarget) -> tuple[str, str, str, str]:
        return (
            target.local_address,
            target.local_port,
            target.peer_address,
            target.peer_port,
        )

    @staticmethod
    def _failed_snapshot(target: _TraceTarget) -> PathTraceSnapshot:
        return PathTraceSnapshot(
            local_address=target.local_address,
            local_port=target.local_port,
            peer_address=target.peer_address,
            peer_port=target.peer_port,
            success=False,
            hops_total=0.0,
        )

    def collect(self, output):
        if self.ttl == 0 or self._closed.is_set():
            return {}

        targets = [self._target(out) for out in output.values()]
        current_pairs = {self._pair_key(target) for target in targets}
        now = self.time_fn()

        with self._lock:
            self._store_completed_traces(now)
            self._cache = {
                key: value for key, value in self._cache.items() if key in current_pairs
            }

            snapshots = {}
            for target in targets:
                pair_key = self._pair_key(target)
                cached = self._cache.get(pair_key)
                if cached is not None:
                    snapshots[self._socket_key(target)] = replace(
                        cached.snapshot,
                        local_port=target.local_port,
                        peer_port=target.peer_port,
                    )

                if pair_key not in self._in_flight and (
                    cached is None or cached.refresh_after <= now
                ):
                    self._in_flight[pair_key] = self._executor.submit(
                        lambda trace_target=target: self._collect_for_target(
                            trace_target
                        )
                    )

            return snapshots

    def _store_completed_traces(self, now: float) -> None:
        for pair_key, future in list(self._in_flight.items()):
            if not future.done():
                continue

            try:
                snapshot = future.result()
            except Exception:
                self._error_counts["worker"] += 1
                log.exception("Unexpected path trace worker failure")
            else:
                self._cache[pair_key] = _CachedPathTrace(
                    snapshot=snapshot,
                    refresh_after=now + self.ttl,
                )
            del self._in_flight[pair_key]

    def _build_command(self, target: _TraceTarget) -> list[str]:
        command = [
            self.tracepath_binary,
            "-n",
            "-m",
            str(self.max_hops),
        ]
        if target.peer_port:
            command.extend(["-p", str(target.peer_port)])
        command.append(target.peer_address)
        return command

    def _collect_for_target(self, target: _TraceTarget) -> PathTraceSnapshot:
        started_at = time.monotonic()
        command = self._build_command(target)
        try:
            result = self.runner(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            self._record_trace_failure(started_at, "unavailable")
            if not self._availability_warning_sent:
                log.warning(
                    "Path trace is disabled because %s is unavailable",
                    self.tracepath_binary,
                )
                self._availability_warning_sent = True
            return self._failed_snapshot(target)
        except subprocess.TimeoutExpired:
            self._record_trace_failure(started_at, "timeout")
            if not self._execution_warning_sent:
                log.warning(
                    "Path trace command %s timed out after %ss",
                    " ".join(command),
                    self.timeout,
                )
                self._execution_warning_sent = True
            return self._failed_snapshot(target)

        snapshot = self._parse_output(
            target.local_address,
            target.local_port,
            target.peer_address,
            target.peer_port,
            result.stdout or "",
        )
        if snapshot is None:
            self._record_trace_failure(
                started_at,
                "command" if result.returncode != 0 else "parse",
            )
            if result.returncode != 0 and not self._execution_warning_sent:
                stderr = (result.stderr or "").strip()
                log.warning(
                    "Path trace command %s failed: %s",
                    " ".join(command),
                    stderr,
                )
                self._execution_warning_sent = True
            return self._failed_snapshot(target)

        self._execution_warning_sent = False
        if snapshot.success:
            self._record_trace_success(started_at)
        else:
            self._record_trace_failure(started_at, "unreachable")
        return snapshot

    def _record_trace_failure(self, started_at: float, reason: str) -> None:
        with self._lock:
            self._last_duration_seconds = time.monotonic() - started_at
            self._error_counts[reason] += 1

    def _record_trace_success(self, started_at: float) -> None:
        with self._lock:
            self._last_duration_seconds = time.monotonic() - started_at
            self._last_success_timestamp_seconds = time.time()

    def health_snapshot(self) -> dict:
        with self._lock:
            return {
                "error_counts": dict(self._error_counts),
                "last_duration_seconds": self._last_duration_seconds,
                "last_success_timestamp_seconds": (
                    self._last_success_timestamp_seconds
                ),
                "in_flight": len(self._in_flight),
            }

    def _run_trace_command(
        self,
        command,
        *,
        capture_output,
        text,
        check,
        timeout,
    ) -> subprocess.CompletedProcess:
        del capture_output, check
        with self._process_lock:
            if self._closed.is_set():
                return subprocess.CompletedProcess(command, -15, "", "")
            process = self.process_factory(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=text,
            )
            self._active_process = process

        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            self._stop_active_process(process)
            stdout, stderr = process.communicate()
            raise subprocess.TimeoutExpired(
                command,
                timeout,
                output=stdout,
                stderr=stderr,
            ) from error
        finally:
            with self._process_lock:
                if self._active_process is process:
                    self._active_process = None

        return subprocess.CompletedProcess(
            command,
            process.returncode,
            stdout,
            stderr,
        )

    @staticmethod
    def _stop_active_process(process) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=0.5)
        except OSError:
            log.debug("Failed to stop tracepath process cleanly")

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

    def close(self) -> None:
        self._closed.set()
        with self._process_lock:
            process = self._active_process
        if process is not None:
            self._stop_active_process(process)
        self._executor.shutdown(
            wait=self._uses_internal_runner,
            cancel_futures=True,
        )
