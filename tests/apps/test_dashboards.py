import json
from pathlib import Path

import pytest

DASHBOARD_DIR = Path("grafana/dashboards")

EXPECTED_NEW_METRICS = {
    "iperf-exporter-overview.json": {
        "iperf_exporter_sample_timestamp_seconds",
        "iperf_exporter_test_runs_total",
        "iperf_exporter_parse_errors_total",
        "iperf_exporter_collector_errors_total",
        "iperf_exporter_path_trace_failures_total",
        "iperf_operator_reconciliations_total",
        "iperf_operator_finalizers_pending",
        "iperf_operator_remote_cluster_up",
        "iperf_operator_probe_runs_total",
        "iperf_operator_reconciliation_duration_seconds_bucket",
    },
    "iperf-exporter-tcp-quality.json": {
        "iperf_exporter_sample_timestamp_seconds",
        "iperf_exporter_test_runs_total",
        "iperf_exporter_parse_errors_total",
        "iperf_exporter_collector_errors_total",
        "iperf_exporter_path_trace_failures_total",
        "iperf_exporter_tcp_socket_retransmissions_total",
        "iperf_exporter_tcp_socket_bytes_retransmitted_total",
    },
    "iperf-exporter-udp-quality.json": {
        "iperf_exporter_sample_timestamp_seconds",
        "iperf_exporter_test_runs_total",
        "iperf_exporter_parse_errors_total",
        "iperf_exporter_collector_errors_total",
        "iperf_exporter_path_trace_failures_total",
    },
}


@pytest.mark.parametrize(("filename", "expected_metrics"), EXPECTED_NEW_METRICS.items())
def test_dashboard_queries_include_health_metrics(filename, expected_metrics):
    dashboard = json.loads((DASHBOARD_DIR / filename).read_text())
    expressions = "\n".join(
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
        if "expr" in target
    )

    assert expected_metrics <= {
        metric for metric in expected_metrics if metric in expressions
    }
    assert "hop_summary" not in expressions


@pytest.mark.parametrize("filename", EXPECTED_NEW_METRICS)
def test_dashboard_panel_ids_are_unique(filename):
    dashboard = json.loads((DASHBOARD_DIR / filename).read_text())
    panel_ids = [panel["id"] for panel in dashboard["panels"]]

    assert len(panel_ids) == len(set(panel_ids))
