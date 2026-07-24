from __future__ import annotations

from iperf_operator.specs import (
    build_exporter_env,
    session_client_deployment_name,
    session_client_job_name,
    session_client_peer,
    session_metric_context,
    session_headless_service_name,
    session_resource_labels,
    session_selector_labels,
    session_server_statefulset_name,
    session_service_name,
)


def build_headless_service(session: dict) -> dict:
    exporter = session["spec"]["exporter"]
    protocol = session["spec"]["protocol"].upper()
    labels = session_resource_labels(session, "server")
    selector_labels = session_selector_labels(session, "server")
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": session_headless_service_name(session),
            "namespace": session["metadata"]["namespace"],
            "labels": labels,
        },
        "spec": {
            "clusterIP": "None",
            "publishNotReadyAddresses": True,
            "selector": selector_labels,
            "ports": [
                {
                    "name": "iperf",
                    "port": exporter["port"],
                    "targetPort": exporter["port"],
                    "protocol": protocol,
                },
                {
                    "name": "metrics",
                    "port": exporter["bindPort"],
                    "targetPort": exporter["bindPort"],
                    "protocol": "TCP",
                },
            ],
        },
    }


def build_cluster_ip_service(session: dict) -> dict | None:
    if session["spec"]["networkMode"] != "service":
        return None

    exporter = session["spec"]["exporter"]
    protocol = session["spec"]["protocol"].upper()
    labels = session_resource_labels(session, "server")
    selector_labels = session_selector_labels(session, "server")
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": session_service_name(session),
            "namespace": session["metadata"]["namespace"],
            "labels": labels,
        },
        "spec": {
            "selector": selector_labels,
            "ports": [
                {
                    "name": "iperf",
                    "port": exporter["port"],
                    "targetPort": exporter["port"],
                    "protocol": protocol,
                },
                {
                    # Keep the metrics endpoint reachable if needed, but do not
                    # name it "metrics" so the kind demo Prometheus job does
                    # not scrape the same pod twice through both services.
                    "name": "service-metrics",
                    "port": exporter["bindPort"],
                    "targetPort": exporter["bindPort"],
                    "protocol": "TCP",
                },
            ],
        },
    }


def build_server_statefulset(session: dict) -> dict:
    exporter = session["spec"]["exporter"]
    runtime = session["spec"]["runtime"]
    labels = session_resource_labels(session, "server")
    selector_labels = session_selector_labels(session, "server")
    host_network = session["spec"]["networkMode"] == "host"
    return {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": session_server_statefulset_name(session),
            "namespace": session["metadata"]["namespace"],
            "labels": labels,
        },
        "spec": {
            "serviceName": session_headless_service_name(session),
            "replicas": 1,
            "selector": {"matchLabels": selector_labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "nodeName": session["spec"]["destination"]["nodeName"],
                    "hostNetwork": host_network,
                    "dnsPolicy": (
                        "ClusterFirstWithHostNet" if host_network else "ClusterFirst"
                    ),
                    "containers": [
                        {
                            "name": "iperf-exporter-server",
                            "image": runtime["image"],
                            "imagePullPolicy": runtime["imagePullPolicy"],
                            "env": build_exporter_env(
                                exporter,
                                mode="server",
                                context_labels=session_metric_context(session),
                            ),
                            "ports": [
                                {
                                    "name": "iperf",
                                    "containerPort": exporter["port"],
                                    "protocol": session["spec"]["protocol"].upper(),
                                },
                                {
                                    "name": "metrics",
                                    "containerPort": exporter["bindPort"],
                                    "protocol": "TCP",
                                },
                            ],
                            "readinessProbe": {
                                "$patch": "replace",
                                "tcpSocket": {"port": exporter["bindPort"]},
                                "initialDelaySeconds": 3,
                                "periodSeconds": 5,
                                "timeoutSeconds": 2,
                            },
                            "livenessProbe": {
                                "$patch": "replace",
                                "tcpSocket": {"port": exporter["bindPort"]},
                                "initialDelaySeconds": 10,
                                "periodSeconds": 10,
                                "timeoutSeconds": 2,
                            },
                        }
                    ],
                },
            },
        },
    }


def _client_container(session: dict) -> dict:
    execution = session["spec"]["execution"]
    exporter = dict(session["spec"]["exporter"])
    if execution.get("durationSeconds", 0) > 0:
        exporter["clientDuration"] = execution["durationSeconds"]

    env = build_exporter_env(
        exporter,
        mode="client",
        peer=session_client_peer(session),
        context_labels=session_metric_context(session),
    )
    env.append(
        {
            "name": "IPERF_EXPORTER_CLIENT_EXECUTION_MODE",
            "value": execution["mode"],
        }
    )
    if execution["mode"] == "periodicProbe":
        env.append(
            {
                "name": "IPERF_EXPORTER_CLIENT_PERIOD_SECONDS",
                "value": str(execution.get("everySeconds", 0)),
            }
        )

    runtime = session["spec"]["runtime"]
    return {
        "name": "iperf-exporter-client",
        "image": runtime["image"],
        "imagePullPolicy": runtime["imagePullPolicy"],
        "env": env,
    }


def build_client_deployment(session: dict) -> dict:
    labels = session_resource_labels(session, "client")
    selector_labels = session_selector_labels(session, "client")
    host_network = session["spec"]["networkMode"] == "host"
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": session_client_deployment_name(session),
            "namespace": session["metadata"]["namespace"],
            "labels": labels,
        },
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": selector_labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "nodeName": session["spec"]["source"]["nodeName"],
                    "hostNetwork": host_network,
                    "dnsPolicy": (
                        "ClusterFirstWithHostNet" if host_network else "ClusterFirst"
                    ),
                    "containers": [_client_container(session)],
                },
            },
        },
    }


def build_client_job(session: dict) -> dict:
    labels = session_resource_labels(session, "client")
    host_network = session["spec"]["networkMode"] == "host"
    duration_seconds = (
        session["spec"]["execution"].get("durationSeconds", 0)
        or session["spec"]["exporter"]["clientDuration"]
    )
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": session_client_job_name(session),
            "namespace": session["metadata"]["namespace"],
            "labels": labels,
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": int(duration_seconds) + 60,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "restartPolicy": "Never",
                    "nodeName": session["spec"]["source"]["nodeName"],
                    "hostNetwork": host_network,
                    "dnsPolicy": (
                        "ClusterFirstWithHostNet" if host_network else "ClusterFirst"
                    ),
                    "containers": [_client_container(session)],
                },
            },
        },
    }
