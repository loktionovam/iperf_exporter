import json
import os
import subprocess
import time

import pytest

CLUSTER_NAME = os.environ.get("CLUSTER_NAME", "iperf-demo")
KUBECTL_CONTEXT = os.environ.get("KUBECTL_CONTEXT", f"kind-{CLUSTER_NAME}")
NAMESPACE = os.environ.get("NAMESPACE", "iperf-exporter-demo")
INGRESS_HOST_SUFFIX = os.environ.get("INGRESS_HOST_SUFFIX", "127.0.0.1.nip.io")
PROM_HOST = f"prometheus.{INGRESS_HOST_SUFFIX}"
GRAFANA_HOST = f"grafana.{INGRESS_HOST_SUFFIX}"
SERVICE_PROXIES = {
    PROM_HOST: f"/api/v1/namespaces/{NAMESPACE}/services/http:prometheus:9090/proxy",
    GRAFANA_HOST: f"/api/v1/namespaces/{NAMESPACE}/services/http:grafana:3000/proxy",
}

EXPECTED_PROFILES = {
    "tcp-quality-continuous",
    "udp-quality-continuous",
    "tcp-throughput-probe",
    "udp-loss-probe",
    "tcp-quality-periodic",
    "udp-quality-periodic",
    "tcp-quality-cross-cluster",
}
EXPECTED_MEASUREMENTS = {
    "tcp-demo",
    "udp-demo",
    "tcp-periodic-demo",
    "udp-periodic-demo",
    "tcp-probe-demo",
    "udp-probe-demo",
    "tcp-cross-cluster-demo",
}
EXPECTED_REMOTE_CLUSTERS = {
    "cluster-b",
}
EXPECTED_DASHBOARDS = {
    "iperf-exporter-overview",
    "iperf-exporter-tcp-quality",
    "iperf-exporter-udp-quality",
}
EXPECTED_SESSION_PHASES = {
    "continuous": {"Running"},
    "periodicProbe": {"Running"},
    "probe": {"Running", "Completed"},
}


def kubectl(*args: str) -> str:
    command = [
        "kubectl",
        "--context",
        KUBECTL_CONTEXT,
        "-n",
        NAMESPACE,
        *args,
    ]
    return subprocess.check_output(command, text=True)


def kubectl_json(*args: str) -> dict:
    return json.loads(kubectl(*args, "-o", "json"))


def kubectl_context_exists() -> bool:
    contexts = subprocess.check_output(
        ["kubectl", "config", "get-contexts", "-o", "name"],
        text=True,
    ).splitlines()
    return KUBECTL_CONTEXT in contexts


def wait_until(predicate, *, timeout: int, interval: int = 2, message: str) -> None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            if predicate():
                return
        except Exception as exc:  # pragma: no cover - surfaced by timeout
            last_error = exc
        time.sleep(interval)
    if last_error is not None:
        raise AssertionError(message) from last_error
    raise AssertionError(message)


def object_phase(resource: str, name: str) -> str:
    payload = kubectl_json("get", resource, name)
    return payload.get("status", {}).get("phase", "")


def wait_for_phase(resource: str, name: str, expected: str, timeout: int = 180) -> None:
    wait_until(
        lambda: object_phase(resource, name) == expected,
        timeout=timeout,
        message=f"{resource}/{name} did not reach phase {expected!r}",
    )


def wait_for_rollout(kind: str, name: str, timeout: int = 180) -> None:
    subprocess.check_call(
        [
            "kubectl",
            "--context",
            KUBECTL_CONTEXT,
            "-n",
            NAMESPACE,
            "rollout",
            "status",
            f"{kind}/{name}",
            f"--timeout={timeout}s",
        ]
    )


def service_proxy_get(host: str, path: str) -> str:
    proxy_path = SERVICE_PROXIES[host]
    return subprocess.check_output(
        [
            "kubectl",
            "--context",
            KUBECTL_CONTEXT,
            "get",
            "--raw",
            f"{proxy_path}{path}",
        ],
        text=True,
    )


def http_json(host: str, path: str) -> object:
    return json.loads(service_proxy_get(host, path))


def wait_http(host: str, path: str, timeout: int = 60) -> None:
    wait_until(
        lambda: bool(service_proxy_get(host, path)),
        timeout=timeout,
        interval=1,
        message=f"Timed out waiting for the {host} Kubernetes Service",
    )


def measurement_sessions_payload() -> dict:
    return kubectl_json("get", "measurementsessions")


@pytest.fixture(scope="module", autouse=True)
def wait_for_demo_cluster():
    assert (
        kubectl_context_exists()
    ), f"kubectl context {KUBECTL_CONTEXT!r} does not exist"
    subprocess.check_call(
        [
            "kubectl",
            "--context",
            KUBECTL_CONTEXT,
            "get",
            "namespace",
            NAMESPACE,
        ]
    )

    for name in sorted(EXPECTED_PROFILES):
        wait_for_phase("measurementprofile", name, "Ready")

    for name in sorted(EXPECTED_MEASUREMENTS):
        wait_for_phase("linkmeasurement", name, "Ready")

    for name in sorted(EXPECTED_REMOTE_CLUSTERS):
        wait_for_phase("remotecluster", name, "Ready")

    subprocess.check_call(
        [
            "kubectl",
            "--context",
            KUBECTL_CONTEXT,
            "-n",
            "ingress-nginx",
            "rollout",
            "status",
            "deploy/ingress-nginx-controller",
            "--timeout=180s",
        ]
    )
    wait_for_rollout("deployment", "prometheus")
    wait_for_rollout("deployment", "grafana")
    wait_for_rollout("deployment", "iperf-exporter-operator")

    def _all_exporter_pods_ready() -> bool:
        pods = kubectl_json(
            "get",
            "pods",
            "-l",
            "app.kubernetes.io/name=iperf-exporter",
        )
        items = pods.get("items", [])
        if not items:
            return False
        for item in items:
            phase = item.get("status", {}).get("phase", "")
            if phase == "Succeeded":
                continue
            if item.get("metadata", {}).get("deletionTimestamp"):
                return False
            statuses = item.get("status", {}).get("containerStatuses", [])
            if not statuses or not all(
                status.get("ready", False) for status in statuses
            ):
                return False
        return True

    wait_until(
        _all_exporter_pods_ready,
        timeout=240,
        message="Exporter pods did not become Ready",
    )

    def _sessions_stable() -> bool:
        payload = measurement_sessions_payload()
        items = payload.get("items", [])
        if len(items) < 12:
            return False
        for item in items:
            mode = item.get("spec", {}).get("execution", {}).get("mode", "")
            phase = item.get("status", {}).get("phase", "")
            if phase not in EXPECTED_SESSION_PHASES.get(mode, set()):
                return False
        return True

    wait_until(
        _sessions_stable,
        timeout=240,
        interval=3,
        message="MeasurementSession phases did not stabilize",
    )

    wait_http(PROM_HOST, "/-/healthy")
    wait_http(GRAFANA_HOST, "/api/health")


def test_measurement_profiles_ready():
    payload = kubectl_json("get", "measurementprofiles")
    names = {item["metadata"]["name"] for item in payload.get("items", [])}
    assert EXPECTED_PROFILES <= names


def test_link_measurements_ready():
    payload = kubectl_json("get", "linkmeasurements")
    names = {item["metadata"]["name"] for item in payload.get("items", [])}
    assert EXPECTED_MEASUREMENTS <= names


def test_remote_clusters_ready():
    payload = kubectl_json("get", "remoteclusters")
    names = {item["metadata"]["name"] for item in payload.get("items", [])}
    assert EXPECTED_REMOTE_CLUSTERS <= names


def test_ingresses_are_configured():
    payload = kubectl_json("get", "ingresses")
    hosts = {
        rule["host"]
        for item in payload.get("items", [])
        for rule in item.get("spec", {}).get("rules", [])
    }
    assert {PROM_HOST, GRAFANA_HOST} <= hosts


def test_measurement_sessions_cover_all_modes():
    payload = measurement_sessions_payload()
    items = payload.get("items", [])
    assert len(items) >= 12

    modes = {item["spec"]["networkMode"] for item in items}
    directions = {item["spec"]["direction"] for item in items}
    execution_modes = {item["spec"]["execution"]["mode"] for item in items}

    assert {"host", "pod", "service"} <= modes
    assert {"sourceToDestination", "destinationToSource"} <= directions
    assert {"continuous", "periodicProbe", "probe"} <= execution_modes


def test_measurement_session_status_is_consistent():
    payload = measurement_sessions_payload()
    invalid = {}
    for item in payload.get("items", []):
        mode = item.get("spec", {}).get("execution", {}).get("mode", "")
        phase = item.get("status", {}).get("phase", "")
        if phase not in EXPECTED_SESSION_PHASES.get(mode, set()):
            invalid[item["metadata"]["name"]] = {"mode": mode, "phase": phase}
    assert not invalid, invalid


def test_api_server_rejects_invalid_profile_port():
    invalid_profile = """
apiVersion: netperf.iperfexporter.io/v1alpha1
kind: MeasurementProfile
metadata:
  name: invalid-port
spec:
  protocol: tcp
  exporter:
    port: 0
"""
    result = subprocess.run(
        [
            "kubectl",
            "--context",
            KUBECTL_CONTEXT,
            "-n",
            NAMESPACE,
            "apply",
            "-f",
            "-",
        ],
        input=invalid_profile,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "greater than or equal to 1" in result.stderr


def test_completed_probe_is_one_shot_and_restarts_after_explicit_job_deletion():
    sessions = sorted(
        (
            item
            for item in measurement_sessions_payload().get("items", [])
            if item.get("spec", {}).get("execution", {}).get("mode") == "probe"
        ),
        key=lambda item: item["metadata"]["name"],
    )
    assert sessions
    session = sessions[0]
    session_name = session["metadata"]["name"]

    wait_until(
        lambda: object_phase("measurementsession", session_name) == "Completed",
        timeout=300,
        message=f"probe session {session_name} did not complete",
    )
    job_name = kubectl_json("get", "measurementsession", session_name)["status"][
        "clientJobName"
    ]
    original_uid = kubectl_json("get", "job", job_name)["metadata"]["uid"]

    time.sleep(305)
    wait_until(
        lambda: kubectl_json("get", "job", job_name)["metadata"]["uid"] == original_uid,
        timeout=30,
        message=f"probe job {job_name} was replaced without explicit deletion",
    )

    kubectl("delete", "job", job_name)
    wait_until(
        lambda: kubectl_json("get", "job", job_name)["metadata"]["uid"] != original_uid,
        timeout=300,
        message=f"probe job {job_name} was not recreated after explicit deletion",
    )


def test_prometheus_has_active_iperf_targets():
    def _has_iperf_targets() -> bool:
        payload = http_json(PROM_HOST, "/api/v1/targets")
        targets = payload["data"]["activeTargets"]
        return any(
            target["labels"].get("job") == "iperf-exporter" for target in targets
        )

    wait_until(
        _has_iperf_targets,
        timeout=60,
        interval=1,
        message="Prometheus did not discover active iperf exporter targets",
    )


def test_prometheus_scrapes_operator_metrics():
    def _operator_is_up() -> bool:
        payload = http_json(
            PROM_HOST,
            "/api/v1/query?query=up%7Bjob%3D%22iperf-operator%22%7D",
        )
        result = payload["data"]["result"]
        return bool(result) and float(result[0]["value"][1]) == 1

    wait_until(
        _operator_is_up,
        timeout=30,
        interval=1,
        message="Prometheus did not scrape the operator metrics endpoint",
    )

    payload = http_json(
        PROM_HOST,
        "/api/v1/query?query=iperf_operator_build_info",
    )
    assert payload["data"]["result"]


def test_prometheus_sees_cross_cluster_measurement():
    def _has_cross_cluster_measurement() -> bool:
        payload = http_json(
            PROM_HOST,
            "/api/v1/query?query=count%20by%20(job)(iperf_exporter_tcp_transfer%7Bmeasurement_id%3D%22tcp-cross-cluster-demo%22%7D)",
        )
        result = payload["data"]["result"]
        jobs = {
            item["metric"].get("job") for item in result if float(item["value"][1]) > 0
        }
        return {"iperf-exporter", "iperf-exporter-remote"} <= jobs

    wait_until(
        _has_cross_cluster_measurement,
        timeout=60,
        interval=1,
        message="Prometheus did not observe both sides of the cross-cluster measurement",
    )


def test_grafana_dashboards_are_provisioned():
    dashboards = http_json(GRAFANA_HOST, "/api/search")
    uids = {item.get("uid") for item in dashboards}
    assert EXPECTED_DASHBOARDS <= uids
