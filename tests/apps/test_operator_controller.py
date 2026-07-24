import base64
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import kopf
import pytest
import yaml
from kubernetes.client.rest import ApiException

from iperf_operator import controller
from iperf_operator.specs import SESSION_LABEL_KEYS, build_session_labels


def _cluster(name="local", namespace="demo", is_local=True):
    return controller.ClusterContext(
        name=name,
        namespace=namespace,
        is_local=is_local,
        core=mock.Mock(),
        apps=mock.Mock(),
        batch=mock.Mock(),
    )


def _session(mode="continuous", network_mode="service", generation=1):
    source = {
        "cluster": "local",
        "nodeName": "worker-a",
        "nodeAddress": "10.0.0.10",
    }
    destination = {
        "cluster": "local",
        "nodeName": "worker-b",
        "nodeAddress": "10.0.0.11",
    }
    labels = build_session_labels(
        measurement_name="worker-a-worker-b",
        session_id=f"worker-a-worker-b:{network_mode}:sourceToDestination",
        direction="sourceToDestination",
        network_mode=network_mode,
        source=source,
        destination=destination,
    )
    return {
        "apiVersion": "netperf.iperfexporter.io/v1alpha1",
        "kind": "MeasurementSession",
        "metadata": {
            "name": f"worker-a-worker-b-{network_mode}-source",
            "namespace": "demo",
            "generation": generation,
            "labels": labels,
        },
        "spec": {
            "measurementRef": {"name": "worker-a-worker-b"},
            "profileRef": {"name": "tcp-quality"},
            "protocol": "tcp",
            "direction": "sourceToDestination",
            "networkMode": network_mode,
            "source": source,
            "destination": destination,
            "execution": {"mode": mode, "durationSeconds": 2},
            "runtime": {
                "image": "iperf_exporter:test",
                "imagePullPolicy": "IfNotPresent",
            },
            "exporter": {
                "protocol": "tcp",
                "port": 5001,
                "bindPort": 9868,
                "interval": 1,
                "len": 8192,
                "metricTTL": 3600,
                "debug": False,
                "clientBandwidth": "1M",
                "clientDuration": 10,
                "serverAdditionalParams": "",
                "clientAdditionalParams": "",
                "contextClientBandwidth": "",
                "contextClientAdditionalParams": "",
                "pathTraceTTL": 0,
                "pathTraceMaxHops": 16,
                "pathTraceTimeout": 5,
            },
        },
    }


@pytest.mark.parametrize(
    ("apply_function", "api_name", "patch_method", "create_method"),
    [
        (
            controller._apply_service,
            "core",
            "patch_namespaced_service",
            "create_namespaced_service",
        ),
        (
            controller._apply_statefulset,
            "apps",
            "patch_namespaced_stateful_set",
            "create_namespaced_stateful_set",
        ),
        (
            controller._apply_deployment,
            "apps",
            "patch_namespaced_deployment",
            "create_namespaced_deployment",
        ),
        (
            controller._apply_job,
            "batch",
            "patch_namespaced_job",
            "create_namespaced_job",
        ),
    ],
)
def test_apply_creates_resource_only_after_404(
    apply_function,
    api_name,
    patch_method,
    create_method,
):
    cluster = _cluster(namespace="target")
    api = getattr(cluster, api_name)
    getattr(api, patch_method).side_effect = ApiException(status=404)
    body = {"metadata": {"name": "resource"}}

    apply_function(cluster, body)

    created = getattr(api, create_method)
    created.assert_called_once()
    assert created.call_args.kwargs["body"]["metadata"]["namespace"] == "target"
    assert "namespace" not in body["metadata"]


def test_statefulset_422_is_propagated_without_deleting_workload():
    cluster = _cluster()
    cluster.apps.patch_namespaced_stateful_set.side_effect = ApiException(status=422)

    with pytest.raises(ApiException) as error:
        controller._apply_statefulset(cluster, {"metadata": {"name": "server"}})

    assert error.value.status == 422
    cluster.apps.create_namespaced_stateful_set.assert_not_called()
    cluster.apps.delete_namespaced_stateful_set.assert_not_called()


def test_non_404_apply_error_is_propagated():
    cluster = _cluster()
    cluster.core.patch_namespaced_service.side_effect = ApiException(status=500)

    with pytest.raises(ApiException):
        controller._apply_service(cluster, {"metadata": {"name": "service"}})

    cluster.core.create_namespaced_service.assert_not_called()


@pytest.mark.parametrize(
    ("delete_function", "api_name", "method_name"),
    [
        (
            controller._delete_service_if_exists,
            "core",
            "delete_namespaced_service",
        ),
        (
            controller._delete_statefulset_if_exists,
            "apps",
            "delete_namespaced_stateful_set",
        ),
        (
            controller._delete_deployment_if_exists,
            "apps",
            "delete_namespaced_deployment",
        ),
        (
            controller._delete_job_if_exists,
            "batch",
            "delete_namespaced_job",
        ),
    ],
)
def test_delete_helpers_ignore_404(delete_function, api_name, method_name):
    cluster = _cluster()
    getattr(getattr(cluster, api_name), method_name).side_effect = ApiException(
        status=404
    )

    delete_function(cluster, "missing")


def test_delete_helper_propagates_non_404():
    cluster = _cluster()
    cluster.batch.delete_namespaced_job.side_effect = ApiException(status=403)

    with pytest.raises(ApiException):
        controller._delete_job_if_exists(cluster, "forbidden")


def test_configure_kubernetes_falls_back_to_kubeconfig():
    settings = mock.Mock()
    with (
        mock.patch.object(
            controller.config,
            "load_incluster_config",
            side_effect=controller.config.ConfigException(),
        ),
        mock.patch.object(controller.config, "load_kube_config") as load_kube_config,
    ):
        controller.configure_kubernetes(settings=settings)

    load_kube_config.assert_called_once_with()
    assert settings.scanning.disabled is True


def test_configure_metrics_starts_validated_port():
    with (
        mock.patch.dict(
            controller.os.environ,
            {"IPERF_OPERATOR_METRICS_PORT": "19869"},
        ),
        mock.patch.object(controller, "start_operator_metrics_server") as start,
    ):
        controller.configure_metrics()

    start.assert_called_once_with(19869)


@pytest.mark.parametrize("value", ["invalid", "0", "65536"])
def test_configure_metrics_rejects_invalid_port(value):
    with (
        mock.patch.dict(
            controller.os.environ,
            {"IPERF_OPERATOR_METRICS_PORT": value},
        ),
        mock.patch.object(controller, "start_operator_metrics_server") as start,
        pytest.raises(ValueError, match="IPERF_OPERATOR_METRICS_PORT"),
    ):
        controller.configure_metrics()

    start.assert_not_called()


def test_api_factories_and_local_cluster_context_use_default_client():
    api_client = mock.sentinel.api_client
    with (
        mock.patch.object(controller.client, "ApiClient", return_value=api_client),
        mock.patch.object(
            controller.client,
            "CustomObjectsApi",
            return_value=mock.sentinel.custom,
        ),
        mock.patch.object(
            controller.client,
            "CoreV1Api",
            side_effect=[mock.sentinel.direct_core, mock.sentinel.cluster_core],
        ),
        mock.patch.object(
            controller.client,
            "AppsV1Api",
            return_value=mock.sentinel.apps,
        ),
        mock.patch.object(
            controller.client,
            "BatchV1Api",
            return_value=mock.sentinel.batch,
        ),
    ):
        assert controller._custom_api() is mock.sentinel.custom
        assert controller._core_api() is mock.sentinel.direct_core
        cluster = controller._cluster_context("demo", "local")

    assert cluster.name == controller.LOCAL_CLUSTER_NAME
    assert cluster.namespace == "demo"
    assert cluster.is_local
    assert cluster.core is mock.sentinel.cluster_core


def test_apply_custom_object_creates_after_404_and_propagates_other_errors():
    custom_api = mock.Mock()
    custom_api.patch_namespaced_custom_object.side_effect = ApiException(status=404)
    body = {"metadata": {"name": "session"}}
    with mock.patch.object(controller, "_custom_api", return_value=custom_api):
        controller._apply_namespaced_custom_object("demo", "sessions", body)
    custom_api.create_namespaced_custom_object.assert_called_once()

    custom_api.reset_mock()
    custom_api.patch_namespaced_custom_object.side_effect = ApiException(status=422)
    with mock.patch.object(controller, "_custom_api", return_value=custom_api):
        with pytest.raises(ApiException):
            controller._apply_namespaced_custom_object("demo", "sessions", body)
    custom_api.create_namespaced_custom_object.assert_not_called()


def test_load_remote_cluster_translates_404_to_permanent_error():
    custom_api = mock.Mock()
    custom_api.get_namespaced_custom_object.side_effect = ApiException(status=404)
    with mock.patch.object(controller, "_custom_api", return_value=custom_api):
        with pytest.raises(kopf.PermanentError, match="was not found"):
            controller._load_remote_cluster("demo", "remote")


def test_remote_cluster_context_loads_secret_and_target_namespace():
    kubeconfig = {"apiVersion": "v1", "clusters": []}
    encoded = base64.b64encode(yaml.safe_dump(kubeconfig).encode()).decode()
    core_api = mock.Mock()
    core_api.read_namespaced_secret.return_value = SimpleNamespace(
        data={"config": encoded}
    )
    expected = _cluster(name="remote", namespace="target", is_local=False)
    remote = {
        "spec": {
            "namespace": "target",
            "kubeconfigSecretRef": {"name": "remote-config", "key": "config"},
        }
    }

    with (
        mock.patch.object(controller, "_load_remote_cluster", return_value=remote),
        mock.patch.object(controller, "_core_api", return_value=core_api),
        mock.patch.object(
            controller.config,
            "new_client_from_config_dict",
            return_value=mock.sentinel.api_client,
        ) as new_client,
        mock.patch.object(
            controller,
            "_cluster_context_from_api_client",
            return_value=expected,
        ),
    ):
        result = controller._cluster_context("demo", "remote")

    assert result is expected
    new_client.assert_called_once_with(kubeconfig)


@pytest.mark.parametrize("required", [True, False])
def test_remote_cluster_outage_is_only_suppressed_for_optional_lookup(required):
    with mock.patch.object(
        controller,
        "_load_remote_cluster",
        side_effect=RuntimeError("remote unavailable"),
    ):
        if required:
            with pytest.raises(RuntimeError, match="remote unavailable"):
                controller._cluster_context("demo", "remote", required=True)
        else:
            assert controller._cluster_context("demo", "remote", required=False) is None


def test_cleanup_remote_outage_propagates_to_keep_finalizer():
    body = _session()
    body["spec"]["destination"]["cluster"] = "remote"
    with mock.patch.object(
        controller,
        "_cluster_context",
        side_effect=RuntimeError("remote unavailable"),
    ):
        with pytest.raises(RuntimeError, match="remote unavailable"):
            controller.delete_measurement_session(body, "demo")


def test_cleanup_deletes_current_workloads_when_clusters_are_reachable():
    body = _session()
    cluster = _cluster()
    with (
        mock.patch.object(controller, "_server_cluster", return_value=cluster),
        mock.patch.object(controller, "_client_cluster", return_value=cluster),
        mock.patch.object(
            controller, "_delete_statefulset_if_exists"
        ) as delete_statefulset,
        mock.patch.object(controller, "_delete_service_if_exists") as delete_service,
        mock.patch.object(
            controller, "_delete_deployment_if_exists"
        ) as delete_deployment,
        mock.patch.object(controller, "_delete_job_if_exists") as delete_job,
    ):
        controller._delete_session_workloads(body, "demo")

    delete_statefulset.assert_called_once()
    assert delete_service.call_count == 2
    delete_deployment.assert_called_once()
    delete_job.assert_called_once()


def test_node_addresses_ignore_user_address_and_read_internal_ip():
    cluster = _cluster()
    cluster.core.read_node.return_value = SimpleNamespace(
        status=SimpleNamespace(
            addresses=[
                SimpleNamespace(type="Hostname", address="worker-a"),
                SimpleNamespace(type="InternalIP", address="10.0.0.10"),
            ]
        )
    )
    endpoint = {
        "cluster": "local",
        "nodeName": "worker-a",
        "nodeAddress": "203.0.113.1",
    }

    with mock.patch.object(controller, "_cluster_context", return_value=cluster):
        result = controller._node_addresses([endpoint, endpoint], "demo")

    assert result == {("local", "worker-a"): "10.0.0.10"}
    cluster.core.read_node.assert_called_once_with(name="worker-a")


def test_node_without_internal_ip_is_rejected():
    cluster = _cluster()
    cluster.core.read_node.return_value = SimpleNamespace(
        status=SimpleNamespace(addresses=[])
    )
    with mock.patch.object(controller, "_cluster_context", return_value=cluster):
        with pytest.raises(kopf.PermanentError, match="does not have an InternalIP"):
            controller._node_addresses(
                [{"cluster": "local", "nodeName": "worker-a"}],
                "demo",
            )


@pytest.mark.parametrize(
    ("active", "succeeded", "failed", "expected_phase"),
    [
        (1, 0, 0, "Running"),
        (0, 1, 0, "Completed"),
        (0, 0, 1, "Failed"),
        (0, 0, 0, "Reconciling"),
    ],
)
def test_job_readiness_phases(active, succeeded, failed, expected_phase):
    server_cluster = _cluster()
    client_cluster = _cluster()
    server_cluster.apps.read_namespaced_stateful_set.return_value = SimpleNamespace(
        status=SimpleNamespace(ready_replicas=1)
    )
    client_cluster.batch.read_namespaced_job.return_value = SimpleNamespace(
        status=SimpleNamespace(
            active=active,
            succeeded=succeeded,
            failed=failed,
        )
    )

    status = controller._job_readiness(
        server_cluster,
        client_cluster,
        "server",
        "job",
    )

    assert status["phase"] == expected_phase
    assert status["clientFailed"] == failed


def test_completed_probe_job_records_runtime_once_by_uid():
    server_cluster = _cluster()
    client_cluster = _cluster()
    started_at = datetime.now(timezone.utc)
    server_cluster.apps.read_namespaced_stateful_set.return_value = SimpleNamespace(
        status=SimpleNamespace(ready_replicas=1)
    )
    client_cluster.batch.read_namespaced_job.return_value = SimpleNamespace(
        metadata=SimpleNamespace(uid="probe-uid"),
        status=SimpleNamespace(
            active=0,
            succeeded=1,
            failed=0,
            start_time=started_at,
            completion_time=started_at + timedelta(seconds=2.5),
        ),
    )
    metrics = mock.Mock()

    with mock.patch.object(controller, "get_operator_metrics", return_value=metrics):
        controller._job_readiness(
            server_cluster,
            client_cluster,
            "server",
            "job",
        )

    metrics.observe_probe_job.assert_called_once_with(
        "probe-uid",
        "success",
        2.5,
    )


def test_readiness_returns_reconciling_on_404():
    server_cluster = _cluster()
    client_cluster = _cluster()
    server_cluster.apps.read_namespaced_stateful_set.side_effect = ApiException(
        status=404
    )

    assert controller._readiness(
        server_cluster,
        client_cluster,
        "server",
        "client",
    ) == {
        "serverReady": False,
        "clientReady": False,
        "phase": "Reconciling",
    }


def test_readiness_reports_running_when_both_workloads_are_ready():
    server_cluster = _cluster()
    client_cluster = _cluster()
    server_cluster.apps.read_namespaced_stateful_set.return_value = SimpleNamespace(
        status=SimpleNamespace(ready_replicas=1)
    )
    client_cluster.apps.read_namespaced_deployment.return_value = SimpleNamespace(
        status=SimpleNamespace(ready_replicas=1)
    )

    status = controller._readiness(
        server_cluster,
        client_cluster,
        "server",
        "client",
    )

    assert status == {
        "serverReady": True,
        "clientReady": True,
        "phase": "Running",
    }


def test_statefulset_ready_handles_present_and_missing_workload():
    cluster = _cluster()
    cluster.apps.read_namespaced_stateful_set.return_value = SimpleNamespace(
        status=SimpleNamespace(ready_replicas=1)
    )
    assert controller._statefulset_ready(cluster, "server")

    cluster.apps.read_namespaced_stateful_set.side_effect = ApiException(status=404)
    assert not controller._statefulset_ready(cluster, "missing")


def test_job_readiness_returns_reconciling_on_404():
    cluster = _cluster()
    cluster.apps.read_namespaced_stateful_set.side_effect = ApiException(status=404)

    status = controller._job_readiness(cluster, cluster, "server", "job")

    assert status["phase"] == "Reconciling"
    assert status["clientSucceeded"] == 0


def test_continuous_reconcile_applies_deployment_and_removes_probe_job():
    body = _session(mode="continuous", network_mode="service")
    cluster = _cluster()
    old_job = SimpleNamespace(metadata=SimpleNamespace(name="old-probe"))
    status = {"phase": "Running"}

    with (
        mock.patch.object(controller, "_server_cluster", return_value=cluster),
        mock.patch.object(controller, "_client_cluster", return_value=cluster),
        mock.patch.object(controller, "_delete_legacy_session_workloads"),
        mock.patch.object(controller, "_apply_service") as apply_service,
        mock.patch.object(controller, "_apply_statefulset") as apply_statefulset,
        mock.patch.object(controller, "_apply_deployment") as apply_deployment,
        mock.patch.object(controller, "_list_session_jobs", return_value=[old_job]),
        mock.patch.object(controller, "_delete_job_if_exists") as delete_job,
        mock.patch.object(controller, "_session_status", return_value=status),
        mock.patch.object(controller.kopf, "adopt"),
    ):
        result = controller._reconcile_session(body, "demo")

    assert result["phase"] == "Running"
    assert apply_service.call_count == 2
    apply_statefulset.assert_called_once()
    apply_deployment.assert_called_once()
    delete_job.assert_called_once_with(cluster, "old-probe")


@pytest.mark.parametrize("failed", [0, 1])
def test_existing_probe_job_is_never_recreated_or_deleted(failed):
    body = _session(mode="probe", network_mode="host")
    cluster = _cluster()
    desired_name = controller.session_client_job_name(body)
    current_job = SimpleNamespace(
        metadata=SimpleNamespace(name=desired_name),
        status=SimpleNamespace(active=0, succeeded=1 - failed, failed=failed),
    )

    with (
        mock.patch.object(controller, "_server_cluster", return_value=cluster),
        mock.patch.object(controller, "_client_cluster", return_value=cluster),
        mock.patch.object(controller, "_delete_legacy_session_workloads"),
        mock.patch.object(controller, "_apply_service"),
        mock.patch.object(controller, "_apply_statefulset"),
        mock.patch.object(controller, "_list_session_jobs", return_value=[current_job]),
        mock.patch.object(
            controller,
            "_session_status",
            return_value={"phase": "Failed" if failed else "Completed"},
        ),
        mock.patch.object(controller, "_apply_job") as apply_job,
        mock.patch.object(controller, "_delete_job_if_exists") as delete_job,
        mock.patch.object(controller.kopf, "adopt"),
    ):
        result = controller._reconcile_session(body, "demo")

    assert result["phase"] == ("Failed" if failed else "Completed")
    apply_job.assert_not_called()
    delete_job.assert_not_called()


def test_deleted_probe_job_is_recreated_when_server_is_ready():
    body = _session(mode="probe", network_mode="host")
    cluster = _cluster()

    with (
        mock.patch.object(controller, "_server_cluster", return_value=cluster),
        mock.patch.object(controller, "_client_cluster", return_value=cluster),
        mock.patch.object(controller, "_delete_legacy_session_workloads"),
        mock.patch.object(controller, "_apply_service"),
        mock.patch.object(controller, "_apply_statefulset"),
        mock.patch.object(controller, "_list_session_jobs", return_value=[]),
        mock.patch.object(controller, "_statefulset_ready", return_value=True),
        mock.patch.object(controller, "_apply_job") as apply_job,
        mock.patch.object(
            controller, "_session_status", return_value={"phase": "Running"}
        ),
        mock.patch.object(controller.kopf, "adopt"),
    ):
        controller._reconcile_session(body, "demo")

    apply_job.assert_called_once()


def test_reconcile_measurement_applies_desired_and_deletes_stale_sessions():
    body = {
        "metadata": {"name": "measurement", "namespace": "demo"},
        "spec": {
            "profileRef": "profile",
            "source": {"nodeName": "a"},
            "destination": {"nodeName": "b"},
        },
    }
    profile = {"metadata": {"resourceVersion": "7"}}
    desired = {
        "metadata": {"name": "desired"},
        "spec": {},
    }
    stale = {"metadata": {"name": "stale"}}

    with (
        mock.patch.object(controller, "_load_profile", return_value=profile),
        mock.patch.object(controller, "_node_addresses", return_value={}),
        mock.patch.object(
            controller, "expand_measurement_sessions", return_value=[desired]
        ),
        mock.patch.object(
            controller, "_apply_namespaced_custom_object"
        ) as apply_session,
        mock.patch.object(
            controller, "_list_measurement_sessions", return_value=[desired, stale]
        ),
        mock.patch.object(controller, "_delete_session_if_exists") as delete_session,
        mock.patch.object(
            controller, "session_summary", return_value={"name": "desired"}
        ),
        mock.patch.object(controller.kopf, "adopt"),
    ):
        result = controller._reconcile_measurement(body, "demo")

    assert result["phase"] == "Ready"
    assert (
        desired["metadata"]["annotations"][controller.PROFILE_TRIGGER_ANNOTATION] == "7"
    )
    apply_session.assert_called_once()
    delete_session.assert_called_once_with("demo", "stale")


def test_reconcile_measurement_requires_profile_reference():
    with pytest.raises(kopf.PermanentError, match="profileRef"):
        controller._reconcile_measurement(
            {"metadata": {"name": "measurement"}, "spec": {}},
            "demo",
        )


def test_list_and_load_helpers_use_custom_api():
    custom_api = mock.Mock()
    custom_api.list_namespaced_custom_object.side_effect = [
        {"items": [{"metadata": {"name": "measurement"}}]},
        {"items": [{"metadata": {"name": "session"}}]},
    ]
    custom_api.get_namespaced_custom_object.return_value = {
        "metadata": {"name": "profile"}
    }
    with mock.patch.object(controller, "_custom_api", return_value=custom_api):
        assert controller._list_link_measurements("demo")[0]["metadata"]["name"] == (
            "measurement"
        )
        assert (
            controller._list_measurement_sessions(
                "demo",
                "measurement-" + ("x" * 80),
            )[
                0
            ]["metadata"]["name"]
            == "session"
        )
        assert controller._load_profile("demo", "profile")["metadata"]["name"] == (
            "profile"
        )
        controller._patch_link_measurement_annotation("demo", "measurement", "9")

    assert custom_api.patch_namespaced_custom_object.call_args.kwargs["body"] == {
        "metadata": {"annotations": {controller.PROFILE_TRIGGER_ANNOTATION: "9"}}
    }


def test_load_profile_translates_404():
    custom_api = mock.Mock()
    custom_api.get_namespaced_custom_object.side_effect = ApiException(status=404)
    with mock.patch.object(controller, "_custom_api", return_value=custom_api):
        with pytest.raises(kopf.PermanentError, match="MeasurementProfile"):
            controller._load_profile("demo", "missing")


def test_profile_handler_updates_only_referencing_measurements():
    patch = SimpleNamespace(status={})
    measurements = [
        {"metadata": {"name": "used"}, "spec": {"profileRef": "profile"}},
        {"metadata": {"name": "other"}, "spec": {"profileRef": "other"}},
    ]
    with (
        mock.patch.object(
            controller,
            "_list_link_measurements",
            return_value=measurements,
        ),
        mock.patch.object(
            controller, "_patch_link_measurement_annotation"
        ) as patch_measurement,
    ):
        controller.reconcile_profile(
            meta={"name": "profile", "resourceVersion": "9"},
            namespace="demo",
            spec={"protocol": "tcp"},
            patch=patch,
        )

    patch_measurement.assert_called_once_with(
        namespace="demo",
        name="used",
        value="9",
    )
    assert patch.status["phase"] == "Ready"


def test_remote_cluster_handler_checks_nodes_and_target_namespace():
    cluster = _cluster(name="remote", namespace="target", is_local=False)
    patch = SimpleNamespace(status={})
    with mock.patch.object(controller, "_cluster_context", return_value=cluster):
        controller.reconcile_remote_cluster(
            body={"metadata": {"name": "remote"}, "spec": {"namespace": "target"}},
            namespace="demo",
            patch=patch,
        )

    cluster.core.list_node.assert_called_once_with(limit=1)
    cluster.core.list_namespaced_service.assert_called_once_with(
        namespace="target",
        limit=1,
    )
    assert patch.status["phase"] == "Ready"


def test_public_handlers_forward_status_results():
    body = _session()
    patch = SimpleNamespace(status={})
    with mock.patch.object(
        controller,
        "_reconcile_measurement",
        return_value={"phase": "Ready"},
    ):
        controller.reconcile_link_measurement(body, "demo", patch)
    assert patch.status == {"phase": "Ready"}

    patch.status = {}
    with mock.patch.object(
        controller,
        "_reconcile_session",
        return_value={"phase": "Running"},
    ):
        controller.reconcile_measurement_session(body, "demo", patch)
    assert patch.status == {"phase": "Running"}


def test_timer_reconciles_probe_but_only_reads_continuous_status():
    patch = SimpleNamespace(status={})
    probe = _session(mode="probe")
    with mock.patch.object(
        controller,
        "_reconcile_session",
        return_value={"phase": "Completed"},
    ) as reconcile:
        controller.refresh_measurement_session_status(probe, "demo", patch)
    reconcile.assert_called_once()

    patch.status = {}
    continuous = _session(mode="continuous")
    with mock.patch.object(
        controller,
        "_session_status",
        return_value={"phase": "Running"},
    ) as status:
        controller.refresh_measurement_session_status(continuous, "demo", patch)
    status.assert_called_once()
    assert patch.status["phase"] == "Running"


def test_session_job_selector_uses_normalized_session_label():
    cluster = _cluster()
    cluster.batch.list_namespaced_job.return_value = SimpleNamespace(items=[])
    body = _session()

    assert controller._list_session_jobs(cluster, body) == []
    cluster.batch.list_namespaced_job.assert_called_once_with(
        namespace="demo",
        label_selector=(
            f"{SESSION_LABEL_KEYS['session']}="
            f"{body['metadata']['labels'][SESSION_LABEL_KEYS['session']]}"
        ),
    )
