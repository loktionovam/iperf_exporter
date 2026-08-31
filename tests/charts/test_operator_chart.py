import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.fixture(scope="module")
def chart_path() -> Path:
    return Path(__file__).resolve().parents[2] / "helm/charts/iperf-operator"


def render(
    chart_path: Path, *options: str, namespace: str = "measurements"
) -> list[dict]:
    result = subprocess.run(
        [
            "helm",
            "template",
            "custom-release",
            str(chart_path),
            "--namespace",
            namespace,
            "--include-crds",
            *options,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if item is not None]


def resource(resources: list[dict], kind: str) -> dict:
    return next(item for item in resources if item["kind"] == kind)


def test_chart_scopes_operator_and_rbac_to_custom_namespace(chart_path: Path) -> None:
    resources = render(chart_path)
    deployment = resource(resources, "Deployment")
    name = deployment["metadata"]["name"]
    spec = deployment["spec"]["template"]["spec"]
    assert name == "custom-release-iperf-operator"
    assert deployment["metadata"]["namespace"] == "measurements"
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"]["type"] == "Recreate"
    assert "--namespace=measurements" in spec["containers"][0]["command"]
    assert spec["serviceAccountName"] == name
    assert resource(resources, "ServiceAccount")["metadata"]["name"] == name
    for kind in ("RoleBinding", "ClusterRoleBinding"):
        binding = resource(resources, kind)
        assert binding["subjects"] == [
            {"kind": "ServiceAccount", "name": name, "namespace": "measurements"}
        ]
        assert (
            binding["roleRef"]["name"]
            == resource(resources, binding["roleRef"]["kind"])["metadata"]["name"]
        )
    other_namespace = render(chart_path, namespace="another-namespace")
    assert (
        resource(resources, "ClusterRole")["metadata"]["name"]
        != resource(other_namespace, "ClusterRole")["metadata"]["name"]
    )
    secret_rule = next(
        rule
        for rule in resource(resources, "Role")["rules"]
        if "secrets" in rule["resources"]
    )
    assert secret_rule["verbs"] == ["get"]


def test_chart_defaults_to_release_images_and_stable_crds(chart_path: Path) -> None:
    resources = render(chart_path)
    container = resource(resources, "Deployment")["spec"]["template"]["spec"][
        "containers"
    ][0]
    assert container["image"] == "ghcr.io/loktionovam/iperf_operator:v4.0.0"
    env = {item["name"]: item["value"] for item in container["env"]}
    assert env["IPERF_OPERATOR_DEFAULT_EXPORTER_IMAGE"] == (
        "ghcr.io/loktionovam/iperf_exporter_server:v4.0.0"
    )
    assert env["IPERF_OPERATOR_LOCAL_CLUSTER_NAME"] == "local"
    crds = [item for item in resources if item["kind"] == "CustomResourceDefinition"]
    assert len(crds) == 4
    for crd in crds:
        assert crd["spec"]["group"] == "netperf.iperfexporter.io"
        assert crd["spec"]["scope"] == "Namespaced"
        assert len(crd["spec"]["versions"]) == 1
        version = crd["spec"]["versions"][0]
        assert version["name"] == "v1"
        assert version["served"] is True
        assert version["storage"] is True


def test_operator_overrides_images_placement_and_cluster_name(chart_path: Path) -> None:
    resources = render(
        chart_path,
        "--set",
        "image.repository=local/operator,image.tag=testing,image.pullPolicy=Never",
        "--set",
        "exporter.image.repository=local/exporter,exporter.image.tag=testing",
        "--set",
        "localClusterName=cluster-a,resources.requests.cpu=200m,nodeSelector.role=network",
        "--set",
        "tolerations[0].key=network,tolerations[0].operator=Exists",
    )
    spec = resource(resources, "Deployment")["spec"]["template"]["spec"]
    container = spec["containers"][0]
    assert container["image"] == "local/operator:testing"
    assert container["imagePullPolicy"] == "Never"
    env = {item["name"]: item["value"] for item in container["env"]}
    assert env["IPERF_OPERATOR_DEFAULT_EXPORTER_IMAGE"] == "local/exporter:testing"
    assert env["IPERF_OPERATOR_LOCAL_CLUSTER_NAME"] == "cluster-a"
    assert "IPERF_OPERATOR_VERSION" not in env
    assert container["resources"]["requests"]["cpu"] == "200m"
    assert spec["nodeSelector"] == {"role": "network"}
    assert spec["tolerations"] == [{"key": "network", "operator": "Exists"}]


@pytest.mark.parametrize("enabled", [False, True])
def test_service_monitors_select_metrics_only_in_release_namespace(
    chart_path: Path, enabled: bool
) -> None:
    resources = render(
        chart_path,
        "--set",
        f"serviceMonitor.enabled={str(enabled).lower()}",
        "--set",
        "serviceMonitor.additionalLabels.release=prometheus",
    )
    monitors = [item for item in resources if item["kind"] == "ServiceMonitor"]
    assert len(monitors) == (2 if enabled else 0)
    if not enabled:
        return
    service = resource(resources, "Service")
    matches = [
        item
        for item in monitors
        if item["spec"]["selector"]["matchLabels"].items()
        <= service["metadata"]["labels"].items()
    ]
    assert len(matches) == 1
    operator_job_label = matches[0]["spec"]["jobLabel"]
    assert service["metadata"]["name"] == "custom-release-iperf-operator"
    assert service["metadata"]["labels"][operator_job_label] == "iperf-operator"
    exporters = next(item for item in monitors if item not in matches)
    assert exporters["spec"]["selector"]["matchLabels"] == {
        "app.kubernetes.io/name": "iperf-exporter",
        "app.kubernetes.io/component": "server",
    }
    assert exporters["spec"]["endpoints"][0]["honorLabels"] is True
    for monitor in monitors:
        assert monitor["metadata"]["namespace"] == "measurements"
        assert monitor["metadata"]["labels"]["release"] == "prometheus"
        assert monitor["spec"]["namespaceSelector"]["matchNames"] == ["measurements"]
        assert len(monitor["spec"]["endpoints"]) == 1
        assert monitor["spec"]["endpoints"][0]["port"] == "metrics"
