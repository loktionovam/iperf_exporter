import json
import os
import subprocess
import time
from collections import Counter
from copy import deepcopy

import pytest

CLUSTER_NAME = os.environ.get("CLUSTER_NAME", "iperf-demo")
KUBECTL_CONTEXT = os.environ.get("KUBECTL_CONTEXT", f"kind-{CLUSTER_NAME}")
REMOTE_CLUSTER_NAME = os.environ.get("REMOTE_CLUSTER_NAME", "iperf-demo-remote")
REMOTE_KUBECTL_CONTEXT = f"kind-{REMOTE_CLUSTER_NAME}"
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
    os.environ.get("REMOTE_CLUSTER_ID", "cluster-b"),
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
    wait_for_rollout("deployment", "iperf-operator")

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


def test_operator_crds_serve_and_store_v1_only():
    for plural in (
        "measurementprofiles",
        "linkmeasurements",
        "measurementsessions",
        "remoteclusters",
    ):
        crd = kubectl_json("get", "crd", f"{plural}.netperf.iperfexporter.io")
        assert [version["name"] for version in crd["spec"]["versions"]] == ["v1"]
        assert crd["spec"]["versions"][0]["served"] is True
        assert crd["spec"]["versions"][0]["storage"] is True
        assert crd["status"]["storedVersions"] == ["v1"]


def test_api_server_rejects_alpha_resources():
    result = subprocess.run(
        [
            "kubectl",
            "--context",
            KUBECTL_CONTEXT,
            "apply",
            "--dry-run=server",
            "-f",
            "-",
        ],
        input=json.dumps(
            {
                "apiVersion": "netperf.iperfexporter.io/v1alpha1",
                "kind": "MeasurementProfile",
                "metadata": {"name": "unsupported-alpha", "namespace": NAMESPACE},
                "spec": {"protocol": "tcp"},
            }
        ),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    assert 'no matches for kind "MeasurementProfile"' in result.stderr


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
apiVersion: netperf.iperfexporter.io/v1
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


def test_prometheus_scrapes_each_exporter_once():
    targets = http_json(PROM_HOST, "/api/v1/targets")["data"]["activeTargets"]
    for job in ("iperf-exporter", "iperf-exporter-remote"):
        counts = Counter(
            target["labels"]["kubernetes_pod"]
            for target in targets
            if target["labels"].get("job") == job
        )
        assert counts, f"No exporter targets for {job}"
        assert all(count == 1 for count in counts.values()), counts


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


def test_operator_restart_preserves_measurements():
    sessions = measurement_sessions_payload()["items"]
    original_uids = {
        item["metadata"]["name"]: item["metadata"]["uid"] for item in sessions
    }
    kubectl("rollout", "restart", "deployment/iperf-operator")
    wait_for_rollout("deployment", "iperf-operator")

    def _sessions_resumed() -> bool:
        resumed = measurement_sessions_payload()["items"]
        uids = {item["metadata"]["name"]: item["metadata"]["uid"] for item in resumed}
        return uids == original_uids and all(
            item.get("status", {}).get("phase")
            in EXPECTED_SESSION_PHASES[item["spec"]["execution"]["mode"]]
            for item in resumed
        )

    wait_until(
        _sessions_resumed,
        timeout=180,
        message="Measurement sessions did not resume after restarting the operator",
    )
    test_prometheus_sees_cross_cluster_measurement()


@pytest.mark.parametrize("remote", [False, True], ids=["local", "remote"])
def test_deleting_measurement_cleans_up_workloads(remote: bool):
    name = "release-cleanup-remote" if remote else "release-cleanup-local"
    template_name = "tcp-cross-cluster-demo" if remote else "tcp-demo"
    spec = deepcopy(kubectl_json("get", "linkmeasurement", template_name)["spec"])
    spec["profileRef"] = name
    spec["directions"] = ["sourceToDestination"]
    spec["networkModes"] = ["host"] if remote else ["pod", "service"]
    resources = {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "apiVersion": "netperf.iperfexporter.io/v1",
                "kind": "MeasurementProfile",
                "metadata": {"name": name, "namespace": NAMESPACE},
                "spec": {
                    "protocol": "tcp",
                    "exporter": {
                        "port": 5801,
                        "bindPort": 9899,
                        "clientBandwidth": "100K",
                        "pathTraceTTL": 0,
                    },
                },
            },
            {
                "apiVersion": "netperf.iperfexporter.io/v1",
                "kind": "LinkMeasurement",
                "metadata": {"name": name, "namespace": NAMESPACE},
                "spec": spec,
            },
        ],
    }
    selector = f"netperf.iperfexporter.io/measurement-id={name}"
    try:
        subprocess.run(
            ["kubectl", "--context", KUBECTL_CONTEXT, "apply", "-f", "-"],
            input=json.dumps(resources),
            text=True,
            check=True,
            timeout=30,
        )
        wait_for_phase("linkmeasurement", name, "Ready")

        def _sessions_running() -> bool:
            sessions = kubectl_json("get", "measurementsessions", "-l", selector)[
                "items"
            ]
            return len(sessions) == len(spec["networkModes"]) and all(
                item.get("status", {}).get("phase") == "Running" for item in sessions
            )

        wait_until(
            _sessions_running,
            timeout=180,
            message=f"Cleanup test measurement {name} did not start",
        )
    finally:
        kubectl(
            "delete",
            "linkmeasurement",
            name,
            "--ignore-not-found=true",
            "--timeout=180s",
        )
        kubectl("delete", "measurementprofile", name, "--ignore-not-found=true")

    def _workloads_removed() -> bool:
        if kubectl_json("get", "measurementsessions", "-l", selector)["items"]:
            return False
        contexts = (
            [KUBECTL_CONTEXT, REMOTE_KUBECTL_CONTEXT] if remote else [KUBECTL_CONTEXT]
        )
        for context in contexts:
            result = subprocess.run(
                [
                    "kubectl",
                    "--context",
                    context,
                    "-n",
                    NAMESPACE,
                    "get",
                    "pods,services,deployments,statefulsets,jobs",
                    "-l",
                    selector,
                    "-o",
                    "json",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if json.loads(result.stdout)["items"]:
                return False
        return True

    wait_until(
        _workloads_removed,
        timeout=180,
        message=f"Deleting measurement {name} left generated workloads behind",
    )
