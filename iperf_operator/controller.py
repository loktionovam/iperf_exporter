from __future__ import annotations

import os
from datetime import datetime, timezone

import kopf
from kubernetes import client, config
from kubernetes.client.rest import ApiException

from iperf_operator import (
    API_GROUP,
    API_VERSION,
    LINK_MEASUREMENT_PLURAL,
    MEASUREMENT_PROFILE_PLURAL,
    MEASUREMENT_SESSION_PLURAL,
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


def _custom_api() -> client.CustomObjectsApi:
    return client.CustomObjectsApi()


def _core_api() -> client.CoreV1Api:
    return client.CoreV1Api()


def _apps_api() -> client.AppsV1Api:
    return client.AppsV1Api()


def _batch_api() -> client.BatchV1Api:
    return client.BatchV1Api()


@kopf.on.startup()
def configure_kubernetes(**_):
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


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


def _apply_service(namespace: str, body: dict) -> None:
    try:
        _core_api().patch_namespaced_service(
            name=body["metadata"]["name"],
            namespace=namespace,
            body=body,
        )
    except ApiException as exc:
        if exc.status != 404:
            raise
        _core_api().create_namespaced_service(namespace=namespace, body=body)


def _apply_statefulset(namespace: str, body: dict) -> None:
    try:
        _apps_api().patch_namespaced_stateful_set(
            name=body["metadata"]["name"],
            namespace=namespace,
            body=body,
        )
    except ApiException as exc:
        if exc.status != 404:
            raise
        _apps_api().create_namespaced_stateful_set(namespace=namespace, body=body)


def _apply_deployment(namespace: str, body: dict) -> None:
    try:
        _apps_api().patch_namespaced_deployment(
            name=body["metadata"]["name"],
            namespace=namespace,
            body=body,
        )
    except ApiException as exc:
        if exc.status != 404:
            raise
        _apps_api().create_namespaced_deployment(namespace=namespace, body=body)


def _apply_job(namespace: str, body: dict) -> None:
    try:
        _batch_api().patch_namespaced_job(
            name=body["metadata"]["name"],
            namespace=namespace,
            body=body,
        )
    except ApiException as exc:
        if exc.status != 404:
            raise
        _batch_api().create_namespaced_job(namespace=namespace, body=body)


def _delete_service_if_exists(namespace: str, name: str) -> None:
    try:
        _core_api().delete_namespaced_service(name=name, namespace=namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise


def _delete_deployment_if_exists(namespace: str, name: str) -> None:
    try:
        _apps_api().delete_namespaced_deployment(name=name, namespace=namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise


def _delete_job_if_exists(namespace: str, name: str) -> None:
    try:
        _batch_api().delete_namespaced_job(
            name=name,
            namespace=namespace,
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


def _readiness(namespace: str, statefulset_name: str, deployment_name: str) -> dict:
    try:
        statefulset = _apps_api().read_namespaced_stateful_set(
            name=statefulset_name,
            namespace=namespace,
        )
        deployment = _apps_api().read_namespaced_deployment(
            name=deployment_name,
            namespace=namespace,
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


def _statefulset_ready(namespace: str, statefulset_name: str) -> bool:
    try:
        statefulset = _apps_api().read_namespaced_stateful_set(
            name=statefulset_name,
            namespace=namespace,
        )
    except ApiException as exc:
        if exc.status == 404:
            return False
        raise
    return (statefulset.status.ready_replicas or 0) >= 1


def _job_readiness(namespace: str, statefulset_name: str, job_name: str) -> dict:
    try:
        statefulset = _apps_api().read_namespaced_stateful_set(
            name=statefulset_name,
            namespace=namespace,
        )
        job = _batch_api().read_namespaced_job(
            name=job_name,
            namespace=namespace,
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


def _node_addresses(node_names: list[str]) -> dict[str, str]:
    node_lookup = {}
    for node_name in node_names:
        node = _core_api().read_node(name=node_name)
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
                f"Node {node_name} does not have an InternalIP address"
            )
        node_lookup[node_name] = internal_ip
    return node_lookup


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


def _list_session_jobs(namespace: str, session: dict) -> list[client.V1Job]:
    label_value = session["metadata"]["labels"][SESSION_LABEL_KEYS["session"]]
    return (
        _batch_api()
        .list_namespaced_job(
            namespace=namespace,
            label_selector=f"{SESSION_LABEL_KEYS['session']}={label_value}",
        )
        .items
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


def _reconcile_measurement(body: dict, namespace: str) -> dict:
    profile_name = body.get("spec", {}).get("profileRef", "")
    if not profile_name:
        raise kopf.PermanentError("spec.profileRef is required")

    profile = _load_profile(namespace, profile_name)
    measurement_nodes = [
        body["spec"]["source"]["nodeName"],
        body["spec"]["destination"]["nodeName"],
    ]
    sessions = expand_measurement_sessions(
        body,
        profile,
        node_addresses=_node_addresses(measurement_nodes),
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
    headless_service = build_headless_service(body)
    cluster_service = build_cluster_ip_service(body)
    statefulset = build_server_statefulset(body)

    for resource in (headless_service, statefulset):
        kopf.adopt(resource, owner=body)
    _apply_service(namespace, headless_service)
    if cluster_service is not None:
        kopf.adopt(cluster_service, owner=body)
        _apply_service(namespace, cluster_service)
    else:
        _delete_service_if_exists(namespace, session_service_name(body))
    _apply_statefulset(namespace, statefulset)

    if execution_mode == "probe":
        _delete_deployment_if_exists(namespace, session_client_deployment_name(body))
        job = build_client_job(body)
        kopf.adopt(job, owner=body)
        desired_job_name = job["metadata"]["name"]
        current_job = None
        for existing_job in _list_session_jobs(namespace, body):
            if existing_job.metadata.name != desired_job_name:
                _delete_job_if_exists(namespace, existing_job.metadata.name)
                continue
            current_job = existing_job

        if current_job is not None:
            active, succeeded, failed = _job_counters(current_job)
            if failed > 0:
                _delete_job_if_exists(namespace, current_job.metadata.name)
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

        if _statefulset_ready(namespace, session_server_statefulset_name(body)):
            _apply_job(namespace, job)
    else:
        deployment = build_client_deployment(body)
        kopf.adopt(deployment, owner=body)
        _apply_deployment(namespace, deployment)
        for existing_job in _list_session_jobs(namespace, body):
            _delete_job_if_exists(namespace, existing_job.metadata.name)

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
    if execution_mode == "probe":
        readiness = _job_readiness(
            namespace=namespace,
            statefulset_name=session_server_statefulset_name(body),
            job_name=session_client_job_name(body),
        )
    else:
        readiness = _readiness(
            namespace=namespace,
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


@kopf.timer(API_GROUP, API_VERSION, MEASUREMENT_SESSION_PLURAL, interval=15.0)
def refresh_measurement_session_status(body, namespace, patch, **_):
    if body["spec"]["execution"]["mode"] == "probe":
        patch.status.update(_reconcile_session(body=body, namespace=namespace))
        return
    patch.status.update(_session_status(body=body, namespace=namespace))
