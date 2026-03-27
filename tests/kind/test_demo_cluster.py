import json
import os
import subprocess
import time
from urllib.request import ProxyHandler, Request, build_opener

import pytest


CLUSTER_NAME = os.environ.get("CLUSTER_NAME", "iperf-demo")
KUBECTL_CONTEXT = os.environ.get("KUBECTL_CONTEXT", f"kind-{CLUSTER_NAME}")
NAMESPACE = os.environ.get("NAMESPACE", "iperf-exporter-demo")
INGRESS_HOST_SUFFIX = os.environ.get("INGRESS_HOST_SUFFIX", "127.0.0.1.nip.io")
INGRESS_HTTP_PORT = int(os.environ.get("INGRESS_HTTP_PORT", "8080"))
PROM_HOST = f"prometheus.{INGRESS_HOST_SUFFIX}"
GRAFANA_HOST = f"grafana.{INGRESS_HOST_SUFFIX}"
HTTP_TIMEOUT_SECONDS = int(os.environ.get("KIND_DEMO_HTTP_TIMEOUT", "5"))
HTTP_OPENER = build_opener(ProxyHandler({}))

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


def http_json(host: str, path: str) -> object:
    request = Request(
        f"http://127.0.0.1:{INGRESS_HTTP_PORT}{path}",
        headers={"Host": host},
    )
    with HTTP_OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.load(response)


def wait_http(host: str, path: str, timeout: int = 60) -> None:
    def _healthy() -> bool:
        request = Request(
            f"http://127.0.0.1:{INGRESS_HTTP_PORT}{path}",
            headers={"Host": host},
        )
        with HTTP_OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS):
            return True

    wait_until(
        _healthy,
        timeout=timeout,
        interval=1,
        message=f"Timed out waiting for http://{host}:{INGRESS_HTTP_PORT}{path}",
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


def test_prometheus_has_active_iperf_targets():
    payload = http_json(PROM_HOST, "/api/v1/targets")
    targets = payload["data"]["activeTargets"]
    iperf_targets = [
        target for target in targets if target["labels"].get("job") == "iperf-exporter"
    ]
    assert iperf_targets


def test_prometheus_sees_cross_cluster_measurement():
    payload = http_json(
        PROM_HOST,
        "/api/v1/query?query=count(iperf_exporter_tcp_transfer%7Bmeasurement_id%3D%22tcp-cross-cluster-demo%22%7D)",
    )
    result = payload["data"]["result"]
    assert result
    assert float(result[0]["value"][1]) > 0


def test_grafana_dashboards_are_provisioned():
    dashboards = http_json(GRAFANA_HOST, "/api/search")
    uids = {item.get("uid") for item in dashboards}
    assert EXPECTED_DASHBOARDS <= uids
