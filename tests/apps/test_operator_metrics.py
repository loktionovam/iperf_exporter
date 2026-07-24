from prometheus_client import CollectorRegistry
from kubernetes.client.rest import ApiException

from iperf_operator.metrics import OperatorMetrics


def test_reconciliation_metrics_record_success_error_and_duration():
    registry = CollectorRegistry()
    metrics = OperatorMetrics(registry)

    with metrics.observe_reconciliation("MeasurementSession"):
        pass

    try:
        with metrics.observe_reconciliation("MeasurementSession"):
            raise ApiException(status=503)
    except ApiException:
        pass

    assert (
        registry.get_sample_value(
            "iperf_operator_reconciliations_total",
            {"kind": "MeasurementSession", "result": "success"},
        )
        == 1
    )
    assert (
        registry.get_sample_value(
            "iperf_operator_reconciliations_total",
            {"kind": "MeasurementSession", "result": "error"},
        )
        == 1
    )
    assert (
        registry.get_sample_value(
            "iperf_operator_reconciliation_errors_total",
            {"kind": "MeasurementSession", "reason": "kubernetes_api"},
        )
        == 1
    )
    assert (
        registry.get_sample_value(
            "iperf_operator_reconciliation_duration_seconds_count",
            {"kind": "MeasurementSession"},
        )
        == 2
    )


def test_resource_remote_cluster_and_finalizer_metrics_track_latest_state():
    registry = CollectorRegistry()
    metrics = OperatorMetrics(registry)

    metrics.set_resource_phase("RemoteCluster", "demo", "remote-a", "Ready")
    metrics.set_resource_phase("RemoteCluster", "demo", "remote-a", "Error")
    metrics.set_remote_cluster_up("remote-a", False)
    metrics.mark_finalizer_pending("demo", "session-a")
    metrics.mark_finalizer_pending("demo", "session-a")
    metrics.record_remote_cleanup_failure("remote-a")

    assert (
        registry.get_sample_value(
            "iperf_operator_resources",
            {"kind": "RemoteCluster", "phase": "Ready"},
        )
        == 0
    )
    assert (
        registry.get_sample_value(
            "iperf_operator_resources",
            {"kind": "RemoteCluster", "phase": "Error"},
        )
        == 1
    )
    assert (
        registry.get_sample_value(
            "iperf_operator_remote_cluster_up",
            {"cluster": "remote-a"},
        )
        == 0
    )
    assert registry.get_sample_value("iperf_operator_finalizers_pending") == 1
    assert (
        registry.get_sample_value(
            "iperf_operator_remote_cleanup_failures_total",
            {"cluster": "remote-a"},
        )
        == 1
    )

    metrics.mark_finalizer_complete("demo", "session-a")
    metrics.remove_resource("RemoteCluster", "demo", "remote-a")

    assert registry.get_sample_value("iperf_operator_finalizers_pending") == 0
    assert (
        registry.get_sample_value(
            "iperf_operator_resources",
            {"kind": "RemoteCluster", "phase": "Error"},
        )
        == 0
    )


def test_probe_job_metrics_are_deduplicated_by_uid():
    registry = CollectorRegistry()
    metrics = OperatorMetrics(registry)

    metrics.observe_probe_job("uid-a", "success", 2.5)
    metrics.observe_probe_job("uid-a", "success", 2.5)
    metrics.observe_probe_job("uid-b", "failed", None)

    assert (
        registry.get_sample_value(
            "iperf_operator_probe_runs_total",
            {"result": "success"},
        )
        == 1
    )
    assert (
        registry.get_sample_value(
            "iperf_operator_probe_runs_total",
            {"result": "failed"},
        )
        == 1
    )
    assert (
        registry.get_sample_value(
            "iperf_operator_probe_duration_seconds_count",
            {"result": "success"},
        )
        == 1
    )
    assert (
        registry.get_sample_value(
            "iperf_operator_probe_duration_seconds_sum",
            {"result": "success"},
        )
        == 2.5
    )


def test_operator_runtime_info_is_exposed():
    registry = CollectorRegistry()
    OperatorMetrics(registry)

    assert registry.get_sample_value("iperf_operator_start_time_seconds") > 0
    samples = [
        sample
        for metric in registry.collect()
        if metric.name == "iperf_operator_build_info"
        for sample in metric.samples
    ]
    assert len(samples) == 1
    assert samples[0].value == 1
    assert samples[0].labels["python_version"]
