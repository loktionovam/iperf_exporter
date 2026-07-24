from __future__ import annotations

import hashlib
import re
from copy import deepcopy

from iperf_operator import API_VERSION_FULL

DEFAULT_IMAGE_PULL_POLICY = "IfNotPresent"
DEFAULT_DIRECTIONS = ("sourceToDestination", "destinationToSource")
DEFAULT_NETWORK_MODES = ("pod",)
SUPPORTED_DIRECTIONS = set(DEFAULT_DIRECTIONS)
SUPPORTED_NETWORK_MODES = {"host", "pod", "service"}
SUPPORTED_EXECUTION_MODES = {"continuous", "probe", "periodicProbe"}
SUPPORTED_PROTOCOLS = {"tcp", "udp"}
LEGACY_RESOURCE_NAME_MAX_LENGTH = 63
RESOURCE_NAME_MAX_LENGTH = 50

LABEL_PREFIX = "netperf.iperfexporter.io/"
SESSION_LABEL_KEYS = {
    "measurement": f"{LABEL_PREFIX}measurement-id",
    "session": f"{LABEL_PREFIX}session-id",
    "direction": f"{LABEL_PREFIX}direction",
    "network_mode": f"{LABEL_PREFIX}network-mode",
    "src_node": f"{LABEL_PREFIX}src-node",
    "dst_node": f"{LABEL_PREFIX}dst-node",
    "src_cluster": f"{LABEL_PREFIX}src-cluster",
    "dst_cluster": f"{LABEL_PREFIX}dst-cluster",
}

EXPORTER_ENV_MAPPING = {
    "port": "IPERF_EXPORTER_PORT",
    "bindPort": "IPERF_EXPORTER_BIND_PORT",
    "interval": "IPERF_EXPORTER_INTERVAL",
    "len": "IPERF_EXPORTER_LEN",
    "metricTTL": "IPERF_EXPORTER_METRIC_TTL",
    "clientBandwidth": "IPERF_EXPORTER_CLIENT_BANDWIDTH",
    "clientDuration": "IPERF_EXPORTER_CLIENT_DURATION",
    "serverAdditionalParams": "IPERF_EXPORTER_SERVER_ADDITIONAL_PARAMS",
    "clientAdditionalParams": "IPERF_EXPORTER_CLIENT_ADDITIONAL_PARAMS",
    "contextClientBandwidth": "IPERF_EXPORTER_CONTEXT_CLIENT_BANDWIDTH",
    "contextClientAdditionalParams": "IPERF_EXPORTER_CONTEXT_CLIENT_ADDITIONAL_PARAMS",
    "pathTraceTTL": "IPERF_EXPORTER_PATH_TRACE_TTL",
    "pathTraceMaxHops": "IPERF_EXPORTER_PATH_TRACE_MAX_HOPS",
    "pathTraceTimeout": "IPERF_EXPORTER_PATH_TRACE_TIMEOUT",
}
CONTEXT_ENV_MAPPING = {
    "measurement_id": "IPERF_EXPORTER_CONTEXT_MEASUREMENT_ID",
    "profile_ref": "IPERF_EXPORTER_CONTEXT_PROFILE_REF",
    "session_id": "IPERF_EXPORTER_CONTEXT_SESSION_ID",
    "execution_mode": "IPERF_EXPORTER_CONTEXT_EXECUTION_MODE",
    "direction": "IPERF_EXPORTER_CONTEXT_DIRECTION",
    "network_mode": "IPERF_EXPORTER_CONTEXT_NETWORK_MODE",
    "src_node": "IPERF_EXPORTER_CONTEXT_SRC_NODE",
    "dst_node": "IPERF_EXPORTER_CONTEXT_DST_NODE",
    "src_cluster": "IPERF_EXPORTER_CONTEXT_SRC_CLUSTER",
    "dst_cluster": "IPERF_EXPORTER_CONTEXT_DST_CLUSTER",
}

DEFAULT_EXPORTER_CONFIG = {
    "port": 5001,
    "bindPort": 9868,
    "interval": 1,
    "len": 1280,
    "metricTTL": 3600,
    "debug": False,
    "clientBandwidth": "1M",
    "clientDuration": 315360000,
    "serverAdditionalParams": "",
    "clientAdditionalParams": "",
    "contextClientBandwidth": "",
    "contextClientAdditionalParams": "",
    "pathTraceTTL": 300,
    "pathTraceMaxHops": 16,
    "pathTraceTimeout": 10,
}


def parse_duration_seconds(value, field_name: str) -> int:
    if value in (None, ""):
        return 0

    if isinstance(value, (int, float)):
        return int(value)

    match = re.fullmatch(r"\s*(\d+)([smhd]?)\s*", str(value))
    if match is None:
        raise ValueError(f"Unsupported {field_name} duration format: {value}")

    amount = int(match.group(1))
    suffix = match.group(2)
    multipliers = {
        "": 1,
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }
    return amount * multipliers[suffix]


def stable_name(*parts: str, max_length: int = 63) -> str:
    raw = "-".join(_slugify(part) for part in parts if part)
    if len(raw) <= max_length:
        return raw

    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    trimmed = raw[: max_length - len(digest) - 1].rstrip("-")
    return f"{trimmed}-{digest}"


def kubernetes_label_value(value: str) -> str:
    return stable_name(str(value), max_length=63)


def _slugify(value: str) -> str:
    allowed = []
    lower = str(value).lower()
    for char in lower:
        if char.isascii() and char.isalnum():
            allowed.append(char)
        elif char in {".", "_", "-", "/"}:
            allowed.append("-")
    slug = "".join(allowed).strip("-")
    return slug or "x"


def normalize_exporter_config(protocol: str, config: dict | None) -> dict:
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError(f"Unsupported protocol: {protocol}")

    merged = deepcopy(DEFAULT_EXPORTER_CONFIG)
    merged.update(config or {})
    for removed_field in ("env", "serverEnv", "clientEnv"):
        merged.pop(removed_field, None)
    merged["protocol"] = protocol
    merged["port"] = int(merged["port"])
    merged["bindPort"] = int(merged["bindPort"])
    merged["interval"] = int(merged["interval"])
    merged["len"] = int(merged["len"])
    merged["metricTTL"] = int(merged["metricTTL"])
    merged["clientDuration"] = int(merged["clientDuration"])
    merged["pathTraceTTL"] = int(merged["pathTraceTTL"])
    merged["pathTraceMaxHops"] = int(merged["pathTraceMaxHops"])
    merged["pathTraceTimeout"] = int(merged["pathTraceTimeout"])
    merged["debug"] = bool(merged["debug"])

    for field_name in ("port", "bindPort"):
        if not 1 <= merged[field_name] <= 65535:
            raise ValueError(f"exporter.{field_name} must be between 1 and 65535")
    for field_name in (
        "interval",
        "len",
        "clientDuration",
        "pathTraceMaxHops",
        "pathTraceTimeout",
    ):
        if merged[field_name] <= 0:
            raise ValueError(f"exporter.{field_name} must be positive")
    for field_name in ("metricTTL", "pathTraceTTL"):
        if merged[field_name] < 0:
            raise ValueError(f"exporter.{field_name} must not be negative")
    return merged


def normalize_runtime(runtime: dict | None, default_image: str) -> dict:
    runtime_spec = runtime or {}
    normalized = {
        "image": runtime_spec.get("image", default_image),
        "imagePullPolicy": runtime_spec.get(
            "imagePullPolicy", DEFAULT_IMAGE_PULL_POLICY
        ),
    }
    if normalized["imagePullPolicy"] not in {"Always", "IfNotPresent", "Never"}:
        raise ValueError("runtime.imagePullPolicy is invalid")
    return normalized


def normalize_execution(execution: dict | None) -> dict:
    execution_spec = execution or {}
    mode = execution_spec.get("mode", "continuous")
    if mode not in SUPPORTED_EXECUTION_MODES:
        raise ValueError(f"Unsupported execution mode: {mode}")
    every = str(execution_spec.get("every", "") or "").strip()
    every_seconds = parse_duration_seconds(every, "execution.every") if every else 0
    if mode == "periodicProbe" and every_seconds <= 0:
        raise ValueError("execution.every is required for execution.mode=periodicProbe")
    normalized = {
        "mode": mode,
    }
    if mode == "periodicProbe":
        normalized["every"] = every
        normalized["everySeconds"] = every_seconds

    duration_seconds = int(execution_spec.get("durationSeconds", 0) or 0)
    if "durationSeconds" in execution_spec and duration_seconds <= 0:
        raise ValueError("execution.durationSeconds must be positive")
    if duration_seconds > 0:
        normalized["durationSeconds"] = duration_seconds
    return normalized


def normalize_endpoint(endpoint: dict | None, field_name: str) -> dict:
    endpoint_spec = endpoint or {}
    node_name = endpoint_spec.get("nodeName", "")
    if not node_name:
        raise ValueError(f"{field_name}.nodeName is required")

    return {
        "cluster": endpoint_spec.get("cluster", "local"),
        "nodeName": node_name,
    }


def _resolve_node_address(node_addresses, cluster_name: str, node_name: str) -> str:
    if (cluster_name, node_name) in node_addresses:
        return node_addresses[(cluster_name, node_name)]
    if node_name in node_addresses:
        return node_addresses[node_name]
    raise ValueError(
        f"Missing node address for endpoint {cluster_name!r}/{node_name!r}"
    )


def resolve_profile(profile: dict) -> dict:
    if profile.get("kind") != "MeasurementProfile":
        raise ValueError("Profile kind must be MeasurementProfile")

    profile_spec = profile.get("spec", {})
    protocol = profile_spec.get("protocol", "")
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError(f"Unsupported profile protocol: {protocol}")

    return {
        "name": profile["metadata"]["name"],
        "protocol": protocol,
        "exporter": normalize_exporter_config(protocol, profile_spec.get("exporter")),
    }


def expand_measurement_sessions(
    measurement: dict,
    profile: dict,
    node_addresses: dict[str, str],
    default_image: str,
) -> list[dict]:
    if measurement.get("kind") != "LinkMeasurement":
        raise ValueError("Measurement kind must be LinkMeasurement")

    profile_view = resolve_profile(profile)
    metadata = measurement.get("metadata", {})
    spec = measurement.get("spec", {})
    namespace = metadata.get("namespace", "default")
    measurement_name = metadata["name"]

    source = normalize_endpoint(spec.get("source"), "source")
    destination = normalize_endpoint(spec.get("destination"), "destination")
    source["nodeAddress"] = _resolve_node_address(
        node_addresses, source["cluster"], source["nodeName"]
    )
    destination["nodeAddress"] = _resolve_node_address(
        node_addresses, destination["cluster"], destination["nodeName"]
    )

    directions_value = spec.get("directions")
    directions = tuple(
        DEFAULT_DIRECTIONS if directions_value is None else directions_value
    )
    if not directions:
        raise ValueError("directions must not be empty")
    if len(directions) != len(set(directions)):
        raise ValueError("directions must contain unique values")
    for direction in directions:
        if direction not in SUPPORTED_DIRECTIONS:
            raise ValueError(f"Unsupported direction: {direction}")

    network_modes_value = spec.get("networkModes")
    network_modes = tuple(
        DEFAULT_NETWORK_MODES if network_modes_value is None else network_modes_value
    )
    if not network_modes:
        raise ValueError("networkModes must not be empty")
    if len(network_modes) != len(set(network_modes)):
        raise ValueError("networkModes must contain unique values")
    for network_mode in network_modes:
        if network_mode not in SUPPORTED_NETWORK_MODES:
            raise ValueError(f"Unsupported network mode: {network_mode}")

    if source["cluster"] != destination["cluster"] and any(
        network_mode != "host" for network_mode in network_modes
    ):
        raise ValueError(
            "Cross-cluster measurements currently support only host network mode"
        )

    execution = normalize_execution(spec.get("execution"))
    runtime = normalize_runtime(spec.get("runtime"), default_image=default_image)

    session_specs = []
    for network_mode in network_modes:
        for direction in directions:
            if direction == "sourceToDestination":
                src = deepcopy(source)
                dst = deepcopy(destination)
            else:
                src = deepcopy(destination)
                dst = deepcopy(source)

            session_name = stable_name(measurement_name, network_mode, direction)
            session_id = f"{measurement_name}:{network_mode}:{direction}"
            session_labels = build_session_labels(
                measurement_name=measurement_name,
                session_id=session_id,
                direction=direction,
                network_mode=network_mode,
                source=src,
                destination=dst,
            )
            session_specs.append(
                {
                    "apiVersion": API_VERSION_FULL,
                    "kind": "MeasurementSession",
                    "metadata": {
                        "name": session_name,
                        "namespace": namespace,
                        "labels": session_labels,
                    },
                    "spec": {
                        "measurementRef": {"name": measurement_name},
                        "profileRef": {"name": profile_view["name"]},
                        "protocol": profile_view["protocol"],
                        "direction": direction,
                        "networkMode": network_mode,
                        "source": src,
                        "destination": dst,
                        "execution": execution,
                        "runtime": runtime,
                        "exporter": deepcopy(profile_view["exporter"]),
                    },
                }
            )
    return session_specs


def build_session_labels(
    measurement_name: str,
    session_id: str,
    direction: str,
    network_mode: str,
    source: dict,
    destination: dict,
) -> dict[str, str]:
    return {
        SESSION_LABEL_KEYS["measurement"]: kubernetes_label_value(measurement_name),
        SESSION_LABEL_KEYS["session"]: kubernetes_label_value(session_id),
        SESSION_LABEL_KEYS["direction"]: kubernetes_label_value(direction),
        SESSION_LABEL_KEYS["network_mode"]: kubernetes_label_value(network_mode),
        SESSION_LABEL_KEYS["src_node"]: kubernetes_label_value(source["nodeName"]),
        SESSION_LABEL_KEYS["dst_node"]: kubernetes_label_value(destination["nodeName"]),
        SESSION_LABEL_KEYS["src_cluster"]: kubernetes_label_value(source["cluster"]),
        SESSION_LABEL_KEYS["dst_cluster"]: kubernetes_label_value(
            destination["cluster"]
        ),
    }


def build_exporter_env(
    exporter: dict,
    *,
    mode: str,
    peer: str = "",
    context_labels: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    exporter = normalize_exporter_config(exporter["protocol"], exporter)
    env = [
        {"name": "IPERF_EXPORTER_MODE", "value": mode},
        {"name": "IPERF_EXPORTER_PROTO", "value": exporter["protocol"]},
        {"name": "DEBUG", "value": "1" if exporter["debug"] else "0"},
    ]

    for key, env_name in EXPORTER_ENV_MAPPING.items():
        if mode == "client" and key in {
            "bindPort",
            "metricTTL",
            "contextClientBandwidth",
            "contextClientAdditionalParams",
            "pathTraceTTL",
            "pathTraceMaxHops",
            "pathTraceTimeout",
            "serverAdditionalParams",
        }:
            continue
        if mode == "server" and key in {
            "clientBandwidth",
            "clientDuration",
            "clientAdditionalParams",
        }:
            continue

        value = exporter.get(key, "")
        if key == "contextClientBandwidth" and value == "":
            value = exporter.get("clientBandwidth", "")
        if key == "contextClientAdditionalParams" and value == "":
            value = exporter.get("clientAdditionalParams", "")
        env.append({"name": env_name, "value": str(value)})

    if mode == "client":
        env.append({"name": "IPERF_EXPORTER_CLIENT_PEER", "value": peer})

    for key, env_name in CONTEXT_ENV_MAPPING.items():
        env.append(
            {"name": env_name, "value": str((context_labels or {}).get(key, ""))}
        )

    return env


def session_resource_name(
    session: dict, suffix: str, *, max_length: int = RESOURCE_NAME_MAX_LENGTH
) -> str:
    return stable_name(session["metadata"]["name"], suffix, max_length=max_length)


def legacy_session_resource_name(session: dict, suffix: str) -> str:
    return session_resource_name(
        session,
        suffix,
        max_length=LEGACY_RESOURCE_NAME_MAX_LENGTH,
    )


def session_selector_labels(session: dict, role: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": "iperf-exporter",
        "app.kubernetes.io/component": role,
        SESSION_LABEL_KEYS["session"]: session["metadata"]["labels"][
            SESSION_LABEL_KEYS["session"]
        ],
    }


def session_resource_labels(session: dict, role: str) -> dict[str, str]:
    return {
        **session["metadata"].get("labels", {}),
        **session_selector_labels(session, role),
    }


def session_metric_context(session: dict) -> dict[str, str]:
    measurement_name = session["spec"].get("measurementRef", {}).get("name", "")
    return {
        "measurement_id": measurement_name,
        "profile_ref": session["spec"].get("profileRef", {}).get("name", ""),
        "session_id": (
            f"{measurement_name}:{session['spec'].get('networkMode', '')}:"
            f"{session['spec'].get('direction', '')}"
        ),
        "execution_mode": session["spec"].get("execution", {}).get("mode", ""),
        "direction": session["spec"].get("direction", ""),
        "network_mode": session["spec"].get("networkMode", ""),
        "src_node": session["spec"]["source"].get("nodeName", ""),
        "dst_node": session["spec"]["destination"].get("nodeName", ""),
        "src_cluster": session["spec"]["source"].get("cluster", ""),
        "dst_cluster": session["spec"]["destination"].get("cluster", ""),
    }


def session_headless_service_name(session: dict) -> str:
    return session_resource_name(session, "headless")


def legacy_session_headless_service_name(session: dict) -> str:
    return legacy_session_resource_name(session, "headless")


def session_service_name(session: dict) -> str:
    return session_resource_name(session, "service")


def legacy_session_service_name(session: dict) -> str:
    return legacy_session_resource_name(session, "service")


def session_server_statefulset_name(session: dict) -> str:
    return session_resource_name(session, "server")


def legacy_session_server_statefulset_name(session: dict) -> str:
    return legacy_session_resource_name(session, "server")


def session_client_deployment_name(session: dict) -> str:
    return session_resource_name(session, "client")


def legacy_session_client_deployment_name(session: dict) -> str:
    return legacy_session_resource_name(session, "client")


def session_client_job_name(session: dict) -> str:
    generation = str(session.get("metadata", {}).get("generation", "1"))
    return stable_name(
        session["metadata"]["name"],
        "client",
        generation,
        max_length=RESOURCE_NAME_MAX_LENGTH,
    )


def legacy_session_client_job_name(session: dict) -> str:
    generation = str(session.get("metadata", {}).get("generation", "1"))
    return stable_name(
        session["metadata"]["name"],
        "client",
        generation,
        max_length=LEGACY_RESOURCE_NAME_MAX_LENGTH,
    )


def session_client_peer(session: dict) -> str:
    namespace = session["metadata"]["namespace"]
    network_mode = session["spec"]["networkMode"]
    if network_mode == "host":
        return session["spec"]["destination"]["nodeAddress"]

    if network_mode == "service":
        return f"{session_service_name(session)}.{namespace}.svc.cluster.local"

    statefulset_name = session_server_statefulset_name(session)
    headless_service = session_headless_service_name(session)
    return f"{statefulset_name}-0.{headless_service}.{namespace}.svc.cluster.local"


def session_summary(session: dict) -> dict:
    context = session_metric_context(session)
    return {
        "name": session["metadata"]["name"],
        "sessionId": context["session_id"],
        "direction": session["spec"]["direction"],
        "networkMode": session["spec"]["networkMode"],
        "executionMode": session["spec"].get("execution", {}).get("mode", ""),
        "srcNode": session["spec"]["source"]["nodeName"],
        "dstNode": session["spec"]["destination"]["nodeName"],
        "srcCluster": session["spec"]["source"].get("cluster", ""),
        "dstCluster": session["spec"]["destination"].get("cluster", ""),
        "protocol": session["spec"]["protocol"],
        "clientPeer": session_client_peer(session),
    }
