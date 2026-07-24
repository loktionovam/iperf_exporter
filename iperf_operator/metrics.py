import os
import platform
import threading
import time
from collections import Counter as CounterMap
from contextlib import contextmanager
from functools import cache

import kopf
from kubernetes.client.rest import ApiException
from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)


def _error_reason(error: Exception) -> str:
    if isinstance(error, ApiException):
        return "kubernetes_api"
    if isinstance(error, kopf.PermanentError):
        return "permanent"
    return "unexpected"


class OperatorMetrics:
    def __init__(self, registry: CollectorRegistry = REGISTRY):
        self.reconciliations = Counter(
            "iperf_operator_reconciliations_total",
            "Operator reconciliation attempts grouped by resource kind and result.",
            ["kind", "result"],
            registry=registry,
        )
        self.reconciliation_duration = Histogram(
            "iperf_operator_reconciliation_duration_seconds",
            "Operator reconciliation duration in seconds.",
            ["kind"],
            registry=registry,
        )
        self.reconciliation_errors = Counter(
            "iperf_operator_reconciliation_errors_total",
            "Operator reconciliation errors grouped by resource kind and bounded reason.",
            ["kind", "reason"],
            registry=registry,
        )
        self.resources = Gauge(
            "iperf_operator_resources",
            "Known custom resources grouped by kind and latest observed phase.",
            ["kind", "phase"],
            registry=registry,
        )
        self.remote_cluster_up = Gauge(
            "iperf_operator_remote_cluster_up",
            "Whether the latest RemoteCluster connectivity check succeeded.",
            ["cluster"],
            registry=registry,
        )
        self.remote_cleanup_failures = Counter(
            "iperf_operator_remote_cleanup_failures_total",
            "Remote MeasurementSession cleanup failures grouped by cluster.",
            ["cluster"],
            registry=registry,
        )
        self.finalizers_pending = Gauge(
            "iperf_operator_finalizers_pending",
            "MeasurementSession finalizers currently waiting for workload cleanup.",
            registry=registry,
        )
        self.probe_duration = Histogram(
            "iperf_operator_probe_duration_seconds",
            "Completed probe Job runtime in seconds.",
            ["result"],
            registry=registry,
        )
        self.probe_runs = Counter(
            "iperf_operator_probe_runs_total",
            "Completed probe Jobs grouped by result.",
            ["result"],
            registry=registry,
        )
        self.start_time = Gauge(
            "iperf_operator_start_time_seconds",
            "Unix timestamp when operator metrics were initialized.",
            registry=registry,
        )
        self.build_info = Gauge(
            "iperf_operator_build_info",
            "Build and runtime information for iperf_operator.",
            ["version", "python_version"],
            registry=registry,
        )
        self.start_time.set(time.time())
        self.build_info.labels(
            version=os.environ.get("IPERF_OPERATOR_VERSION", "dev"),
            python_version=platform.python_version(),
        ).set(1)

        self._lock = threading.Lock()
        self._resource_phases: dict[tuple[str, str, str], str] = {}
        self._known_phases: dict[str, set[str]] = {}
        self._pending_finalizers: set[tuple[str, str]] = set()
        self._observed_probe_jobs: set[str] = set()

    @contextmanager
    def observe_reconciliation(self, kind: str):
        started_at = time.monotonic()
        try:
            yield
        except Exception as error:
            self.reconciliations.labels(kind=kind, result="error").inc()
            self.reconciliation_errors.labels(
                kind=kind,
                reason=_error_reason(error),
            ).inc()
            raise
        else:
            self.reconciliations.labels(kind=kind, result="success").inc()
        finally:
            self.reconciliation_duration.labels(kind=kind).observe(
                time.monotonic() - started_at
            )

    def set_resource_phase(
        self,
        kind: str,
        namespace: str,
        name: str,
        phase: str,
    ) -> None:
        normalized_phase = phase or "Unknown"
        with self._lock:
            self._resource_phases[(kind, namespace, name)] = normalized_phase
            self._known_phases.setdefault(kind, set()).add(normalized_phase)
            self._update_resource_gauges(kind)

    def remove_resource(self, kind: str, namespace: str, name: str) -> None:
        with self._lock:
            self._resource_phases.pop((kind, namespace, name), None)
            self._update_resource_gauges(kind)

    def _update_resource_gauges(self, kind: str) -> None:
        counts = CounterMap(
            phase
            for (resource_kind, _, _), phase in self._resource_phases.items()
            if resource_kind == kind
        )
        for phase in self._known_phases.get(kind, set()):
            self.resources.labels(kind=kind, phase=phase).set(counts[phase])

    def set_remote_cluster_up(self, cluster: str, is_up: bool) -> None:
        self.remote_cluster_up.labels(cluster=cluster).set(float(is_up))

    def remove_remote_cluster(self, cluster: str) -> None:
        self.remote_cluster_up.remove(cluster)

    def mark_finalizer_pending(self, namespace: str, name: str) -> None:
        with self._lock:
            self._pending_finalizers.add((namespace, name))
            self.finalizers_pending.set(len(self._pending_finalizers))

    def mark_finalizer_complete(self, namespace: str, name: str) -> None:
        with self._lock:
            self._pending_finalizers.discard((namespace, name))
            self.finalizers_pending.set(len(self._pending_finalizers))

    def record_remote_cleanup_failure(self, cluster: str) -> None:
        self.remote_cleanup_failures.labels(cluster=cluster).inc()

    def observe_probe_job(
        self,
        uid: str,
        result: str,
        duration_seconds: float | None,
    ) -> None:
        if not uid:
            return
        with self._lock:
            if uid in self._observed_probe_jobs:
                return
            self._observed_probe_jobs.add(uid)
        self.probe_runs.labels(result=result).inc()
        if duration_seconds is not None and duration_seconds >= 0:
            self.probe_duration.labels(result=result).observe(duration_seconds)


@cache
def get_operator_metrics() -> OperatorMetrics:
    return OperatorMetrics()


_metrics_server_lock = threading.Lock()
_metrics_server_started = False


def start_operator_metrics_server(port: int) -> None:
    global _metrics_server_started
    with _metrics_server_lock:
        if _metrics_server_started:
            return
        start_http_server(port)
        _metrics_server_started = True
