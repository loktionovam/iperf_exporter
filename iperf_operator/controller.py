from __future__ import annotations

import base64
import os
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone

import kopf
import yaml
from kubernetes import client, config
from kubernetes.client.rest import ApiException

from iperf_operator import (
    API_GROUP,
    API_VERSION,
    LINK_MEASUREMENT_PLURAL,
    MEASUREMENT_PROFILE_PLURAL,
    MEASUREMENT_SESSION_PLURAL,
    REMOTE_CLUSTER_PLURAL,
)
from iperf_operator.manifests import (
    build_client_deployment,
    build_client_job,
    build_cluster_ip_service,
    build_headless_service,
    build_server_statefulset,
)
from iperf_operator.specs import (
    SESSION_LABEL_KEYS,
    expand_measurement_sessions,
    legacy_session_client_deployment_name,
    legacy_session_client_job_name,
    legacy_session_headless_service_name,
    legacy_session_server_statefulset_name,
    legacy_session_service_name,
    session_client_deployment_name,
    session_client_job_name,
    session_client_peer,
    session_headless_service_name,
    session_server_statefulset_name,
    session_service_name,
    session_summary,
)

PROFILE_TRIGGER_ANNOTATION = "netperf.iperfexporter.io/profile-resource-version"
DEFAULT_EXPORTER_IMAGE = os.environ.get(
    "IPERF_OPERATOR_DEFAULT_EXPORTER_IMAGE",
    os.environ.get("IPERF_OPERATOR_DEFAULT_IMAGE", "iperf_exporter:kind-demo"),
)
LOCAL_CLUSTER_NAME = os.environ.get("IPERF_OPERATOR_LOCAL_CLUSTER_NAME", "local")


@dataclass(frozen=True)
class ClusterContext:
    name: str
    namespace: str
    is_local: bool
    core: client.CoreV1Api
    apps: client.AppsV1Api
    batch: client.BatchV1Api


def _custom_api() -> client.CustomObjectsApi:
    return client.CustomObjectsApi()


def _core_api() -> client.CoreV1Api:
    return client.CoreV1Api()


@kopf.on.startup()
def configure_kubernetes(**_):
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def _local_cluster_aliases() -> set[str]:
    return {LOCAL_CLUSTER_NAME, "local"}


def _resource_in_namespace(body: dict, namespace: str) -> dict:
    resource = deepcopy(body)
    resource.setdefault("metadata", {})["namespace"] = namespace
    return resource


def _cluster_context_from_api_client(
    name: str,
    namespace: str,
    api_client: client.ApiClient | None,
    *,
    is_local: bool,
) -> ClusterContext:
    api_client = api_client or client.ApiClient()
    return ClusterContext(
        name=name,
        namespace=namespace,
        is_local=is_local,
        core=client.CoreV1Api(api_client),
        apps=client.AppsV1Api(api_client),
        batch=client.BatchV1Api(api_client),
    )


def _load_remote_cluster(namespace: str, name: str) -> dict:
    try:
        return _custom_api().get_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural=REMOTE_CLUSTER_PLURAL,
            name=name,
        )
    except ApiException as exc:
        if exc.status == 404:
            raise kopf.PermanentError(
                f"RemoteCluster {name!r} was not found in namespace {namespace!r}"
            ) from exc
        raise


def _cluster_context(
    namespace: str,
    cluster_name: str,
    *,
    required: bool = True,
) -> ClusterContext | None:
    if cluster_name in _local_cluster_aliases():
        return _cluster_context_from_api_client(
            name=LOCAL_CLUSTER_NAME,
            namespace=namespace,
            api_client=None,
            is_local=True,
        )

    try:
        remote_cluster = _load_remote_cluster(namespace, cluster_name)
    except Exception:
        if required:
            raise
        return None

    secret_ref = remote_cluster.get("spec", {}).get("kubeconfigSecretRef", {})
    secret_name = secret_ref.get("name", "")
    secret_key = secret_ref.get("key", "kubeconfig")
    if not secret_name:
        if required:
            raise kopf.PermanentError(
                f"RemoteCluster {cluster_name!r} is missing spec.kubeconfigSecretRef.name"
            )
        return None

    try:
        secret = _core_api().read_namespaced_secret(name=secret_name, namespace=namespace)
        encoded = (secret.data or {}).get(secret_key, "")
        if not encoded:
            raise kopf.PermanentError(
                f"Secret {secret_name!r} does not contain key {secret_key!r}"
            )
        kubeconfig_dict = yaml.safe_load(base64.b64decode(encoded).decode("utf-8"))
        api_client = config.new_client_from_config_dict(kubeconfig_dict)
    except Exception:
        if required:
            raise
        return None

    return _cluster_context_from_api_client(
        name=cluster_name,
        namespace=remote_cluster.get("spec", {}).get("namespace", namespace) or namespace,
        api_client=api_client,
        is_local=False,
    )


def _apply_namespaced_custom_object(namespace: str, plural: str, body: dict) -> None:
    try:
        _custom_api().patch_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural=plural,
            name=body["metadata"]["name"],
            body=body,
        )
    except ApiException as exc:
        if exc.status != 404:
            raise
        _custom_api().create_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural=plural,
            body=body,
        )


def _apply_service(cluster: ClusterContext, body: dict) -> None:
    body = _resource_in_namespace(body, cluster.namespace)
    try:
        cluster.core.patch_namespaced_service(
            name=body["metadata"]["name"],
            namespace=cluster.namespace,
            body=body,
        )
    except ApiException as exc:
        if exc.status != 404:
            raise
        cluster.core.create_namespaced_service(namespace=cluster.namespace, body=body)


def _apply_statefulset(cluster: ClusterContext, body: dict) -> None:
    body = _resource_in_namespace(body, cluster.namespace)
    try:
        cluster.apps.patch_namespaced_stateful_set(
            name=body["metadata"]["name"],
            namespace=cluster.namespace,
            body=body,
        )
    except ApiException as exc:
        if exc.status == 422:
            _delete_statefulset_if_exists(cluster, body["metadata"]["name"])
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    cluster.apps.read_namespaced_stateful_set(
                        name=body["metadata"]["name"],
                        namespace=cluster.namespace,
                    )
                except ApiException as read_exc:
                    if read_exc.status == 404:
                        break
                    raise
                time.sleep(1)
            else:
                raise
            cluster.apps.create_namespaced_stateful_set(
                namespace=cluster.namespace,
                body=body,
            )
            return
        if exc.status != 404:
            raise
        cluster.apps.create_namespaced_stateful_set(namespace=cluster.namespace, body=body)


def _apply_deployment(cluster: ClusterContext, body: dict) -> None:
    body = _resource_in_namespace(body, cluster.namespace)
    try:
        cluster.apps.patch_namespaced_deployment(
            name=body["metadata"]["name"],
            namespace=cluster.namespace,
            body=body,
        )
    except ApiException as exc:
        if exc.status != 404:
            raise
        cluster.apps.create_namespaced_deployment(namespace=cluster.namespace, body=body)


def _apply_job(cluster: ClusterContext, body: dict) -> None:
    body = _resource_in_namespace(body, cluster.namespace)
    try:
        cluster.batch.patch_namespaced_job(
            name=body["metadata"]["name"],
            namespace=cluster.namespace,
            body=body,
        )
    except ApiException as exc:
        if exc.status != 404:
            raise
        cluster.batch.create_namespaced_job(namespace=cluster.namespace, body=body)


def _delete_service_if_exists(cluster: ClusterContext, name: str) -> None:
    try:
        cluster.core.delete_namespaced_service(name=name, namespace=cluster.namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise


def _delete_statefulset_if_exists(cluster: ClusterContext, name: str) -> None:
    try:
        cluster.apps.delete_namespaced_stateful_set(
            name=name,
            namespace=cluster.namespace,
            propagation_policy="Background",
        )
    except ApiException as exc:
        if exc.status != 404:
            raise


def _delete_deployment_if_exists(cluster: ClusterContext, name: str) -> None:
    try:
        cluster.apps.delete_namespaced_deployment(name=name, namespace=cluster.namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise


def _delete_job_if_exists(cluster: ClusterContext, name: str) -> None:
    try:
        cluster.batch.delete_namespaced_job(
            name=name,
            namespace=cluster.namespace,
            propagation_policy="Background",
        )
    except ApiException as exc:
        if exc.status != 404:
            raise


def _delete_session_if_exists(namespace: str, name: str) -> None:
    try:
        _custom_api().delete_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural=MEASUREMENT_SESSION_PLURAL,
            name=name,
        )
    except ApiException as exc:
        if exc.status != 404:
            raise


def _adopt_if_local(body: dict, owner: dict, cluster: ClusterContext) -> None:
    if cluster.is_local:
        kopf.adopt(body, owner=owner)


def _readiness(
    server_cluster: ClusterContext,
    client_cluster: ClusterContext,
    statefulset_name: str,
    deployment_name: str,
) -> dict:
    try:
        statefulset = server_cluster.apps.read_namespaced_stateful_set(
            name=statefulset_name,
            namespace=server_cluster.namespace,
        )
        deployment = client_cluster.apps.read_namespaced_deployment(
            name=deployment_name,
            namespace=client_cluster.namespace,
        )
    except ApiException as exc:
        if exc.status != 404:
            raise
        return {
            "serverReady": False,
            "clientReady": False,
            "phase": "Reconciling",
        }

    server_ready = (statefulset.status.ready_replicas or 0) >= 1
    client_ready = (deployment.status.ready_replicas or 0) >= 1
    return {
        "serverReady": server_ready,
        "clientReady": client_ready,
        "phase": "Running" if server_ready and client_ready else "Reconciling",
    }


def _statefulset_ready(cluster: ClusterContext, statefulset_name: str) -> bool:
    try:
        statefulset = cluster.apps.read_namespaced_stateful_set(
            name=statefulset_name,
            namespace=cluster.namespace,
        )
    except ApiException as exc:
        if exc.status == 404:
            return False
        raise
    return (statefulset.status.ready_replicas or 0) >= 1


def _job_readiness(
    server_cluster: ClusterContext,
    client_cluster: ClusterContext,
    statefulset_name: str,
    job_name: str,
) -> dict:
    try:
        statefulset = server_cluster.apps.read_namespaced_stateful_set(
            name=statefulset_name,
            namespace=server_cluster.namespace,
        )
        job = client_cluster.batch.read_namespaced_job(
            name=job_name,
            namespace=client_cluster.namespace,
        )
    except ApiException as exc:
        if exc.status != 404:
            raise
        return {
            "serverReady": False,
            "clientReady": False,
            "clientActive": 0,
            "clientSucceeded": 0,
            "clientFailed": 0,
            "phase": "Reconciling",
        }

    server_ready = (statefulset.status.ready_replicas or 0) >= 1
    active = job.status.active or 0
    succeeded = job.status.succeeded or 0
    failed = job.status.failed or 0
    if failed > 0:
        phase = "Failed"
        client_ready = False
    elif active > 0 and server_ready:
        phase = "Running"
        client_ready = True
    elif succeeded > 0 and server_ready:
        phase = "Completed"
        client_ready = True
    else:
        phase = "Reconciling"
        client_ready = False
    return {
        "serverReady": server_ready,
        "clientReady": client_ready,
        "clientActive": active,
        "clientSucceeded": succeeded,
        "clientFailed": failed,
        "phase": phase,
    }


def _node_addresses(endpoints: list[dict], namespace: str) -> dict[tuple[str, str], str]:
    cluster_cache: dict[str, ClusterContext] = {}
    resolved: dict[tuple[str, str], str] = {}
    for endpoint in endpoints:
        node_name = endpoint.get("nodeName", "")
        cluster_name = endpoint.get("cluster", LOCAL_CLUSTER_NAME)
        if not node_name:
            continue
        key = (cluster_name, node_name)
        if endpoint.get("nodeAddress"):
            resolved[key] = endpoint["nodeAddress"]
            continue
        if key in resolved:
            continue

        cluster = cluster_cache.setdefault(
            cluster_name,
            _cluster_context(namespace, cluster_name),
        )
        node = cluster.core.read_node(name=node_name)
        internal_ip = next(
            (
                address.address
                for address in node.status.addresses or []
                if address.type == "InternalIP"
            ),
            "",
        )
        if not internal_ip:
            raise kopf.PermanentError(
                f"Node {node_name} in cluster {cluster_name} does not have an InternalIP"
            )
        resolved[key] = internal_ip
    return resolved


def _list_link_measurements(namespace: str) -> list[dict]:
    return (
        _custom_api()
        .list_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural=LINK_MEASUREMENT_PLURAL,
        )
        .get("items", [])
    )


def _list_measurement_sessions(namespace: str, measurement_name: str) -> list[dict]:
    return (
        _custom_api()
        .list_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural=MEASUREMENT_SESSION_PLURAL,
            label_selector=f"{SESSION_LABEL_KEYS['measurement']}={measurement_name}",
        )
        .get("items", [])
    )


def _list_session_jobs(cluster: ClusterContext, session: dict) -> list[client.V1Job]:
    label_value = session["metadata"]["labels"][SESSION_LABEL_KEYS["session"]]
    return (
        cluster.batch.list_namespaced_job(
            namespace=cluster.namespace,
            label_selector=f"{SESSION_LABEL_KEYS['session']}={label_value}",
        ).items
    )


def _job_counters(job: client.V1Job) -> tuple[int, int, int]:
    return (
        job.status.active or 0,
        job.status.succeeded or 0,
        job.status.failed or 0,
    )


def _load_profile(namespace: str, profile_name: str) -> dict:
    try:
        return _custom_api().get_namespaced_custom_object(
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural=MEASUREMENT_PROFILE_PLURAL,
            name=profile_name,
        )
    except ApiException as exc:
        if exc.status == 404:
            raise kopf.PermanentError(
                f"MeasurementProfile {profile_name!r} was not found in namespace {namespace!r}"
            ) from exc
        raise


def _patch_link_measurement_annotation(namespace: str, name: str, value: str) -> None:
    _custom_api().patch_namespaced_custom_object(
        group=API_GROUP,
        version=API_VERSION,
        namespace=namespace,
        plural=LINK_MEASUREMENT_PLURAL,
        name=name,
        body={"metadata": {"annotations": {PROFILE_TRIGGER_ANNOTATION: value}}},
    )


def _server_cluster(body: dict, namespace: str, *, required: bool = True) -> ClusterContext | None:
    return _cluster_context(namespace, body["spec"]["destination"]["cluster"], required=required)


def _client_cluster(body: dict, namespace: str, *, required: bool = True) -> ClusterContext | None:
    return _cluster_context(namespace, body["spec"]["source"]["cluster"], required=required)


def _delete_session_workloads(body: dict, namespace: str) -> None:
    server_cluster = _server_cluster(body, namespace, required=False)
    client_cluster = _client_cluster(body, namespace, required=False)

    if server_cluster is not None:
        _delete_statefulset_if_exists(server_cluster, session_server_statefulset_name(body))
        _delete_service_if_exists(server_cluster, session_headless_service_name(body))
        _delete_service_if_exists(server_cluster, session_service_name(body))
        legacy_server = legacy_session_server_statefulset_name(body)
        legacy_headless = legacy_session_headless_service_name(body)
        legacy_service = legacy_session_service_name(body)
        if legacy_server != session_server_statefulset_name(body):
            _delete_statefulset_if_exists(server_cluster, legacy_server)
        if legacy_headless != session_headless_service_name(body):
            _delete_service_if_exists(server_cluster, legacy_headless)
        if legacy_service != session_service_name(body):
            _delete_service_if_exists(server_cluster, legacy_service)

    if client_cluster is not None:
        _delete_deployment_if_exists(client_cluster, session_client_deployment_name(body))
        _delete_job_if_exists(client_cluster, session_client_job_name(body))
        legacy_deployment = legacy_session_client_deployment_name(body)
        legacy_job = legacy_session_client_job_name(body)
        if legacy_deployment != session_client_deployment_name(body):
            _delete_deployment_if_exists(client_cluster, legacy_deployment)
        if legacy_job != session_client_job_name(body):
            _delete_job_if_exists(client_cluster, legacy_job)


def _delete_legacy_session_workloads(body: dict, namespace: str) -> None:
    server_cluster = _server_cluster(body, namespace, required=False)
    client_cluster = _client_cluster(body, namespace, required=False)

    if server_cluster is not None:
        legacy_server = legacy_session_server_statefulset_name(body)
        legacy_headless = legacy_session_headless_service_name(body)
        legacy_service = legacy_session_service_name(body)
        if legacy_server != session_server_statefulset_name(body):
            _delete_statefulset_if_exists(server_cluster, legacy_server)
        if legacy_headless != session_headless_service_name(body):
            _delete_service_if_exists(server_cluster, legacy_headless)
        if legacy_service != session_service_name(body):
            _delete_service_if_exists(server_cluster, legacy_service)

    if client_cluster is not None:
        legacy_deployment = legacy_session_client_deployment_name(body)
        legacy_job = legacy_session_client_job_name(body)
        if legacy_deployment != session_client_deployment_name(body):
            _delete_deployment_if_exists(client_cluster, legacy_deployment)
        if legacy_job != session_client_job_name(body):
            _delete_job_if_exists(client_cluster, legacy_job)


def _reconcile_measurement(body: dict, namespace: str) -> dict:
    profile_name = body.get("spec", {}).get("profileRef", "")
    if not profile_name:
        raise kopf.PermanentError("spec.profileRef is required")

    profile = _load_profile(namespace, profile_name)
    node_addresses = _node_addresses(
        [
            body["spec"]["source"],
            body["spec"]["destination"],
        ],
        namespace=namespace,
    )
    sessions = expand_measurement_sessions(
        body,
        profile,
        node_addresses=node_addresses,
        default_image=DEFAULT_EXPORTER_IMAGE,
    )

    desired_names = set()
    for session in sessions:
        kopf.adopt(session, owner=body)
        session.setdefault("metadata", {}).setdefault("annotations", {})[
            PROFILE_TRIGGER_ANNOTATION
        ] = profile["metadata"].get("resourceVersion", "")
        _apply_namespaced_custom_object(
            namespace=namespace,
            plural=MEASUREMENT_SESSION_PLURAL,
            body=session,
        )
        desired_names.add(session["metadata"]["name"])

    existing_sessions = _list_measurement_sessions(
        namespace=namespace,
        measurement_name=body["metadata"]["name"],
    )
    for session in existing_sessions:
        if session["metadata"]["name"] not in desired_names:
            _delete_session_if_exists(namespace, session["metadata"]["name"])

    return {
        "phase": "Ready",
        "profileName": profile_name,
        "reconciledAt": datetime.now(timezone.utc).isoformat(),
        "sessions": [session_summary(session) for session in sessions],
    }


def _reconcile_session(body: dict, namespace: str) -> dict:
    execution_mode = body["spec"]["execution"]["mode"]
    server_cluster = _server_cluster(body, namespace)
    client_cluster = _client_cluster(body, namespace)

    _delete_legacy_session_workloads(body, namespace)

    headless_service = build_headless_service(body)
    cluster_service = build_cluster_ip_service(body)
    statefulset = build_server_statefulset(body)

    for resource in (headless_service, statefulset):
        _adopt_if_local(resource, body, server_cluster)
    _apply_service(server_cluster, headless_service)
    if cluster_service is not None:
        _adopt_if_local(cluster_service, body, server_cluster)
        _apply_service(server_cluster, cluster_service)
    else:
        _delete_service_if_exists(server_cluster, session_service_name(body))
    _apply_statefulset(server_cluster, statefulset)

    if execution_mode == "probe":
        _delete_deployment_if_exists(client_cluster, session_client_deployment_name(body))
        job = build_client_job(body)
        _adopt_if_local(job, body, client_cluster)
        desired_job_name = job["metadata"]["name"]
        current_job = None
        for existing_job in _list_session_jobs(client_cluster, body):
            if existing_job.metadata.name != desired_job_name:
                _delete_job_if_exists(client_cluster, existing_job.metadata.name)
                continue
            current_job = existing_job

        if current_job is not None:
            active, succeeded, failed = _job_counters(current_job)
            if failed > 0:
                _delete_job_if_exists(client_cluster, current_job.metadata.name)
                current_job = None
            elif active > 0 or succeeded > 0:
                readiness = _session_status(body=body, namespace=namespace)
                return {
                    **readiness,
                    "headlessServiceName": session_headless_service_name(body),
                    "serviceName": (
                        session_service_name(body)
                        if body["spec"]["networkMode"] == "service"
                        else ""
                    ),
                    "serverStatefulSetName": session_server_statefulset_name(body),
                    "clientDeploymentName": "",
                    "clientJobName": session_client_job_name(body),
                }

        if _statefulset_ready(server_cluster, session_server_statefulset_name(body)):
            _apply_job(client_cluster, job)
    else:
        deployment = build_client_deployment(body)
        _adopt_if_local(deployment, body, client_cluster)
        _apply_deployment(client_cluster, deployment)
        for existing_job in _list_session_jobs(client_cluster, body):
            _delete_job_if_exists(client_cluster, existing_job.metadata.name)

    readiness = _session_status(body=body, namespace=namespace)
    return {
        **readiness,
        "headlessServiceName": session_headless_service_name(body),
        "serviceName": (
            session_service_name(body)
            if body["spec"]["networkMode"] == "service"
            else ""
        ),
        "serverStatefulSetName": session_server_statefulset_name(body),
        "clientDeploymentName": (
            session_client_deployment_name(body) if execution_mode != "probe" else ""
        ),
        "clientJobName": (
            session_client_job_name(body) if execution_mode == "probe" else ""
        ),
    }


def _session_status(body: dict, namespace: str) -> dict:
    execution_mode = body["spec"]["execution"]["mode"]
    server_cluster = _server_cluster(body, namespace)
    client_cluster = _client_cluster(body, namespace)

    if execution_mode == "probe":
        readiness = _job_readiness(
            server_cluster=server_cluster,
            client_cluster=client_cluster,
            statefulset_name=session_server_statefulset_name(body),
            job_name=session_client_job_name(body),
        )
    else:
        readiness = _readiness(
            server_cluster=server_cluster,
            client_cluster=client_cluster,
            statefulset_name=session_server_statefulset_name(body),
            deployment_name=session_client_deployment_name(body),
        )
    return {
        **readiness,
        "clientPeer": session_client_peer(body),
        "headlessServiceName": session_headless_service_name(body),
        "serviceName": (
            session_service_name(body)
            if body["spec"]["networkMode"] == "service"
            else ""
        ),
        "serverStatefulSetName": session_server_statefulset_name(body),
        "clientDeploymentName": (
            session_client_deployment_name(body) if execution_mode != "probe" else ""
        ),
        "clientJobName": (
            session_client_job_name(body) if execution_mode == "probe" else ""
        ),
        "serverCluster": server_cluster.name,
        "serverNamespace": server_cluster.namespace,
        "clientCluster": client_cluster.name,
        "clientNamespace": client_cluster.namespace,
    }


@kopf.on.create(API_GROUP, API_VERSION, MEASUREMENT_PROFILE_PLURAL)
@kopf.on.update(API_GROUP, API_VERSION, MEASUREMENT_PROFILE_PLURAL)
def reconcile_profile(meta, namespace, spec, patch, **_):
    name = meta["name"]
    trigger_value = meta.get("resourceVersion", "")
    for measurement in _list_link_measurements(namespace):
        if measurement.get("spec", {}).get("profileRef") == name:
            _patch_link_measurement_annotation(
                namespace=namespace,
                name=measurement["metadata"]["name"],
                value=trigger_value,
            )
    patch.status.update(
        {
            "phase": "Ready",
            "protocol": spec.get("protocol", ""),
            "reconciledAt": datetime.now(timezone.utc).isoformat(),
        }
    )


@kopf.on.create(API_GROUP, API_VERSION, REMOTE_CLUSTER_PLURAL)
@kopf.on.update(API_GROUP, API_VERSION, REMOTE_CLUSTER_PLURAL)
@kopf.on.resume(API_GROUP, API_VERSION, REMOTE_CLUSTER_PLURAL)
def reconcile_remote_cluster(body, namespace, patch, **_):
    cluster_name = body["metadata"]["name"]
    cluster = _cluster_context(namespace, cluster_name)
    namespace_name = body.get("spec", {}).get("namespace", namespace) or namespace

    cluster.core.read_namespace(name=namespace_name)
    cluster.core.list_node(limit=1)

    patch.status.update(
        {
            "phase": "Ready",
            "namespace": namespace_name,
            "reconciledAt": datetime.now(timezone.utc).isoformat(),
        }
    )


@kopf.on.create(API_GROUP, API_VERSION, LINK_MEASUREMENT_PLURAL)
@kopf.on.update(API_GROUP, API_VERSION, LINK_MEASUREMENT_PLURAL)
@kopf.on.resume(API_GROUP, API_VERSION, LINK_MEASUREMENT_PLURAL)
def reconcile_link_measurement(body, namespace, patch, **_):
    patch.status.update(_reconcile_measurement(body=body, namespace=namespace))


@kopf.on.create(API_GROUP, API_VERSION, MEASUREMENT_SESSION_PLURAL)
@kopf.on.update(API_GROUP, API_VERSION, MEASUREMENT_SESSION_PLURAL)
@kopf.on.resume(API_GROUP, API_VERSION, MEASUREMENT_SESSION_PLURAL)
def reconcile_measurement_session(body, namespace, patch, **_):
    patch.status.update(_reconcile_session(body=body, namespace=namespace))


@kopf.on.delete(API_GROUP, API_VERSION, MEASUREMENT_SESSION_PLURAL)
def delete_measurement_session(body, namespace, **_):
    _delete_session_workloads(body=body, namespace=namespace)


@kopf.timer(API_GROUP, API_VERSION, MEASUREMENT_SESSION_PLURAL, interval=15.0)
def refresh_measurement_session_status(body, namespace, patch, **_):
    if body["spec"]["execution"]["mode"] == "probe":
        patch.status.update(_reconcile_session(body=body, namespace=namespace))
        return
    patch.status.update(_session_status(body=body, namespace=namespace))
