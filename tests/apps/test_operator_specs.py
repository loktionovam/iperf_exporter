from iperf_operator.specs import (
    SESSION_LABEL_KEYS,
    build_exporter_env,
    expand_measurement_sessions,
    kubernetes_label_value,
    session_client_deployment_name,
    session_client_peer,
    session_client_job_name,
    session_headless_service_name,
    session_server_statefulset_name,
    session_service_name,
)
from iperf_operator.manifests import (
    build_client_deployment,
    build_client_job,
    build_cluster_ip_service,
    build_headless_service,
    build_server_statefulset,
)


def _profile(protocol="tcp"):
    return {
        "apiVersion": "netperf.iperfexporter.io/v1",
        "kind": "MeasurementProfile",
        "metadata": {"name": f"{protocol}-quality"},
        "spec": {
            "protocol": protocol,
            "exporter": {
                "port": 5001,
                "bindPort": 9868,
                "interval": 2,
                "len": 8192 if protocol == "tcp" else 1280,
                "metricTTL": 120,
                "clientBandwidth": "3M",
                "clientDuration": 600,
                "clientAdditionalParams": "--trip-times",
                "serverAdditionalParams": "--histograms=100u,20",
                "pathTraceTTL": 45,
                "pathTraceMaxHops": 8,
                "pathTraceTimeout": 5,
            },
        },
    }


def _measurement(network_modes=None, execution=None):
    return {
        "apiVersion": "netperf.iperfexporter.io/v1",
        "kind": "LinkMeasurement",
        "metadata": {"name": "worker-a-worker-b", "namespace": "demo"},
        "spec": {
            "profileRef": "tcp-quality",
            "source": {"cluster": "local", "nodeName": "worker-a"},
            "destination": {"cluster": "local", "nodeName": "worker-b"},
            "directions": ["sourceToDestination", "destinationToSource"],
            "networkModes": network_modes or ["host", "pod", "service"],
            "execution": execution or {"mode": "continuous"},
            "runtime": {"image": "iperf_exporter:kind-demo"},
        },
    }


def _cross_cluster_measurement(network_modes=None, execution=None):
    measurement = _measurement(network_modes=network_modes, execution=execution)
    measurement["metadata"]["name"] = "cluster-a-worker-a-cluster-b-worker-b"
    measurement["spec"]["source"]["cluster"] = "cluster-a"
    measurement["spec"]["destination"]["cluster"] = "cluster-b"
    return measurement


def test_expand_measurement_sessions_creates_bidirectional_sessions():
    sessions = expand_measurement_sessions(
        _measurement(),
        _profile(),
        node_addresses={"worker-a": "10.0.0.10", "worker-b": "10.0.0.11"},
        default_image="iperf_exporter:dev",
    )

    assert len(sessions) == 6
    service_session = next(
        session
        for session in sessions
        if session["spec"]["networkMode"] == "service"
        and session["spec"]["direction"] == "sourceToDestination"
    )
    reverse_host_session = next(
        session
        for session in sessions
        if session["spec"]["networkMode"] == "host"
        and session["spec"]["direction"] == "destinationToSource"
    )

    assert service_session["spec"]["source"]["nodeName"] == "worker-a"
    assert service_session["spec"]["destination"]["nodeName"] == "worker-b"
    assert reverse_host_session["spec"]["source"]["nodeName"] == "worker-b"
    assert reverse_host_session["spec"]["destination"]["nodeName"] == "worker-a"
    assert service_session["spec"]["runtime"]["image"] == "iperf_exporter:kind-demo"


def test_build_exporter_env_includes_all_supported_exporter_fields():
    exporter = _profile()["spec"]["exporter"] | {"protocol": "tcp"}
    server_env = {
        item["name"]: item["value"]
        for item in build_exporter_env(exporter, mode="server")
    }
    client_env = {
        item["name"]: item["value"]
        for item in build_exporter_env(
            exporter,
            mode="client",
            peer="server.demo.svc.cluster.local",
            context_labels={
                "measurement_id": "worker-a-worker-b",
                "profile_ref": "tcp-quality",
                "session_id": "worker-a-worker-b-service-sourcetodestination",
                "execution_mode": "continuous",
                "direction": "sourceToDestination",
                "network_mode": "service",
                "src_node": "worker-a",
                "dst_node": "worker-b",
                "src_cluster": "local",
                "dst_cluster": "local",
            },
        )
    }

    assert server_env["IPERF_EXPORTER_MODE"] == "server"
    assert server_env["IPERF_EXPORTER_PORT"] == "5001"
    assert server_env["IPERF_EXPORTER_INTERVAL"] == "2"
    assert server_env["IPERF_EXPORTER_LEN"] == "8192"
    assert server_env["IPERF_EXPORTER_METRIC_TTL"] == "120"
    assert server_env["IPERF_EXPORTER_CONTEXT_CLIENT_BANDWIDTH"] == "3M"
    assert (
        server_env["IPERF_EXPORTER_CONTEXT_CLIENT_ADDITIONAL_PARAMS"] == "--trip-times"
    )
    assert (
        server_env["IPERF_EXPORTER_SERVER_ADDITIONAL_PARAMS"] == "--histograms=100u,20"
    )
    assert server_env["IPERF_EXPORTER_PATH_TRACE_TTL"] == "45"
    assert server_env["IPERF_EXPORTER_PATH_TRACE_MAX_HOPS"] == "8"
    assert server_env["IPERF_EXPORTER_PATH_TRACE_TIMEOUT"] == "5"

    assert client_env["IPERF_EXPORTER_MODE"] == "client"
    assert client_env["IPERF_EXPORTER_CLIENT_PEER"] == "server.demo.svc.cluster.local"
    assert client_env["IPERF_EXPORTER_CLIENT_BANDWIDTH"] == "3M"
    assert client_env["IPERF_EXPORTER_CLIENT_DURATION"] == "600"
    assert client_env["IPERF_EXPORTER_CLIENT_ADDITIONAL_PARAMS"] == "--trip-times"
    assert client_env["IPERF_EXPORTER_CONTEXT_MEASUREMENT_ID"] == "worker-a-worker-b"
    assert client_env["IPERF_EXPORTER_CONTEXT_PROFILE_REF"] == "tcp-quality"
    assert client_env["IPERF_EXPORTER_CONTEXT_EXECUTION_MODE"] == "continuous"
    assert client_env["IPERF_EXPORTER_CONTEXT_NETWORK_MODE"] == "service"
    assert client_env["IPERF_EXPORTER_CONTEXT_SRC_NODE"] == "worker-a"
    assert client_env["IPERF_EXPORTER_CONTEXT_DST_NODE"] == "worker-b"


def test_removed_exporter_environment_fields_are_ignored():
    profile = _profile()
    profile["spec"]["exporter"].update(
        {
            "env": {"UNSUPPORTED": "value"},
            "serverEnv": {"UNSUPPORTED": "value"},
            "clientEnv": {"UNSUPPORTED": "value"},
        }
    )

    session = expand_measurement_sessions(
        _measurement(network_modes=["host"]),
        profile,
        node_addresses={"worker-a": "10.0.0.10", "worker-b": "10.0.0.11"},
        default_image="iperf_exporter:dev",
    )[0]

    assert "env" not in session["spec"]["exporter"]
    assert "serverEnv" not in session["spec"]["exporter"]
    assert "clientEnv" not in session["spec"]["exporter"]


def test_session_peer_resolution_matches_network_mode():
    sessions = expand_measurement_sessions(
        _measurement(network_modes=["host", "pod", "service"]),
        _profile(),
        node_addresses={"worker-a": "10.0.0.10", "worker-b": "10.0.0.11"},
        default_image="iperf_exporter:dev",
    )
    peers = {
        session["spec"]["networkMode"]: session_client_peer(session)
        for session in sessions
        if session["spec"]["direction"] == "sourceToDestination"
    }

    assert peers["host"] == "10.0.0.11"
    assert peers["service"] == (
        f"{session_service_name(next(s for s in sessions if s['spec']['networkMode'] == 'service' and s['spec']['direction'] == 'sourceToDestination'))}.demo.svc.cluster.local"
    )
    pod_session = next(
        session
        for session in sessions
        if session["spec"]["networkMode"] == "pod"
        and session["spec"]["direction"] == "sourceToDestination"
    )
    assert peers["pod"] == (
        f"{session_server_statefulset_name(pod_session)}-0."
        f"{session_headless_service_name(pod_session)}.demo.svc.cluster.local"
    )


def test_expand_measurement_sessions_normalizes_periodic_execution():
    session = next(
        session
        for session in expand_measurement_sessions(
            _measurement(
                network_modes=["pod"],
                execution={
                    "mode": "periodicProbe",
                    "every": "5m",
                    "durationSeconds": 30,
                },
            ),
            _profile(),
            node_addresses={"worker-a": "10.0.0.10", "worker-b": "10.0.0.11"},
            default_image="iperf_exporter:dev",
        )
        if session["spec"]["direction"] == "sourceToDestination"
    )

    assert session["spec"]["execution"]["mode"] == "periodicProbe"
    assert session["spec"]["execution"]["every"] == "5m"
    assert session["spec"]["execution"]["everySeconds"] == 300
    assert session["spec"]["execution"]["durationSeconds"] == 30


def test_expand_measurement_sessions_allows_cross_cluster_host_measurements():
    sessions = expand_measurement_sessions(
        _cross_cluster_measurement(network_modes=["host"]),
        _profile(),
        node_addresses={
            ("cluster-a", "worker-a"): "10.10.0.10",
            ("cluster-b", "worker-b"): "10.20.0.11",
        },
        default_image="iperf_exporter:dev",
    )

    assert len(sessions) == 2
    forward = next(
        session
        for session in sessions
        if session["spec"]["direction"] == "sourceToDestination"
    )
    reverse = next(
        session
        for session in sessions
        if session["spec"]["direction"] == "destinationToSource"
    )

    assert forward["spec"]["source"]["cluster"] == "cluster-a"
    assert forward["spec"]["destination"]["cluster"] == "cluster-b"
    assert session_client_peer(forward) == "10.20.0.11"
    assert session_client_peer(reverse) == "10.10.0.10"


def test_expand_measurement_sessions_rejects_cross_cluster_pod_and_service_modes():
    for mode in ("pod", "service"):
        try:
            expand_measurement_sessions(
                _cross_cluster_measurement(network_modes=[mode]),
                _profile(),
                node_addresses={
                    ("cluster-a", "worker-a"): "10.10.0.10",
                    ("cluster-b", "worker-b"): "10.20.0.11",
                },
                default_image="iperf_exporter:dev",
            )
        except ValueError as exc:
            assert "host network mode" in str(exc)
        else:  # pragma: no cover - explicit failure branch
            raise AssertionError(f"cross-cluster mode {mode!r} should be rejected")


def test_generated_workload_names_leave_headroom_for_kubernetes_suffixes():
    session = next(
        session
        for session in expand_measurement_sessions(
            _cross_cluster_measurement(network_modes=["host"]),
            _profile(),
            node_addresses={
                ("cluster-a", "worker-a"): "10.10.0.10",
                ("cluster-b", "worker-b"): "10.20.0.11",
            },
            default_image="iperf_exporter:dev",
        )
        if session["spec"]["direction"] == "sourceToDestination"
    )
    session["metadata"]["generation"] = 7

    assert len(session_server_statefulset_name(session)) <= 50
    assert len(session_client_deployment_name(session)) <= 50
    assert len(session_headless_service_name(session)) <= 50
    assert len(session_service_name(session)) <= 50
    assert len(session_client_job_name(session)) <= 50


def test_manifests_reflect_session_topology():
    session = next(
        session
        for session in expand_measurement_sessions(
            _measurement(network_modes=["service"]),
            _profile("udp"),
            node_addresses={"worker-a": "10.0.0.10", "worker-b": "10.0.0.11"},
            default_image="iperf_exporter:dev",
        )
        if session["spec"]["direction"] == "sourceToDestination"
    )

    headless_service = build_headless_service(session)
    cluster_service = build_cluster_ip_service(session)
    statefulset = build_server_statefulset(session)
    deployment = build_client_deployment(session)

    assert headless_service["spec"]["clusterIP"] == "None"
    assert cluster_service["metadata"]["name"] == session_service_name(session)
    assert statefulset["spec"]["template"]["spec"]["nodeName"] == "worker-b"
    assert deployment["spec"]["template"]["spec"]["nodeName"] == "worker-a"
    deployment_env = {
        item["name"]: item["value"]
        for item in deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    statefulset_env = {
        item["name"]: item["value"]
        for item in statefulset["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert deployment_env["IPERF_EXPORTER_CONTEXT_NETWORK_MODE"] == "service"
    assert statefulset_env["IPERF_EXPORTER_CONTEXT_NETWORK_MODE"] == "service"
    assert statefulset_env["IPERF_EXPORTER_CONTEXT_DIRECTION"] == "sourceToDestination"
    assert cluster_service["spec"]["ports"][0]["name"] == "iperf"
    assert cluster_service["spec"]["ports"][1]["name"] == "service-metrics"
    server_container = statefulset["spec"]["template"]["spec"]["containers"][0]
    assert server_container["readinessProbe"]["tcpSocket"]["port"] == 9868
    assert server_container["livenessProbe"]["tcpSocket"]["port"] == 9868
    assert "httpGet" not in server_container["readinessProbe"]
    assert "httpGet" not in server_container["livenessProbe"]
    selector_labels = statefulset["spec"]["selector"]["matchLabels"]
    assert set(selector_labels) == {
        "app.kubernetes.io/name",
        "app.kubernetes.io/component",
        SESSION_LABEL_KEYS["session"],
    }
    assert (
        statefulset["spec"]["template"]["metadata"]["labels"][
            SESSION_LABEL_KEYS["src_node"]
        ]
        == "worker-a"
    )


def test_probe_job_uses_single_run_client_mode():
    session = next(
        session
        for session in expand_measurement_sessions(
            _measurement(
                network_modes=["host"],
                execution={"mode": "probe", "durationSeconds": 45},
            ),
            _profile("tcp"),
            node_addresses={"worker-a": "10.0.0.10", "worker-b": "10.0.0.11"},
            default_image="iperf_exporter:dev",
        )
        if session["spec"]["direction"] == "sourceToDestination"
    )
    session["metadata"]["generation"] = 3

    job = build_client_job(session)

    assert job["metadata"]["name"] == session_client_job_name(session)
    assert "ttlSecondsAfterFinished" not in job["spec"]
    assert job["spec"]["backoffLimit"] == 0
    assert job["spec"]["activeDeadlineSeconds"] == 105
    assert job["spec"]["template"]["spec"]["restartPolicy"] == "Never"
    container_env = {
        item["name"]: item["value"]
        for item in job["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert container_env["IPERF_EXPORTER_CLIENT_EXECUTION_MODE"] == "probe"
    assert container_env["IPERF_EXPORTER_CLIENT_DURATION"] == "45"


def test_periodic_probe_deployment_sets_period_seconds():
    session = next(
        session
        for session in expand_measurement_sessions(
            _measurement(
                network_modes=["pod"],
                execution={
                    "mode": "periodicProbe",
                    "every": "2m",
                    "durationSeconds": 20,
                },
            ),
            _profile("udp"),
            node_addresses={"worker-a": "10.0.0.10", "worker-b": "10.0.0.11"},
            default_image="iperf_exporter:dev",
        )
        if session["spec"]["direction"] == "sourceToDestination"
    )

    deployment = build_client_deployment(session)
    container_env = {
        item["name"]: item["value"]
        for item in deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert container_env["IPERF_EXPORTER_CLIENT_EXECUTION_MODE"] == "periodicProbe"
    assert container_env["IPERF_EXPORTER_CLIENT_PERIOD_SECONDS"] == "120"
    assert container_env["IPERF_EXPORTER_CLIENT_DURATION"] == "20"


def test_long_topology_values_are_safe_labels_but_metrics_keep_full_values():
    long_name = "node-" + ("x" * 80)
    measurement = _measurement(network_modes=["host"])
    measurement["metadata"]["name"] = "measurement-" + ("y" * 80)
    measurement["spec"]["source"]["nodeName"] = long_name
    sessions = expand_measurement_sessions(
        measurement,
        _profile(),
        node_addresses={
            long_name: "10.0.0.10",
            "worker-b": "10.0.0.11",
        },
        default_image="iperf_exporter:dev",
    )
    session = next(
        item for item in sessions if item["spec"]["direction"] == "sourceToDestination"
    )

    assert all(len(value) <= 63 for value in session["metadata"]["labels"].values())
    assert session["metadata"]["labels"][SESSION_LABEL_KEYS["src_node"]] == (
        kubernetes_label_value(long_name)
    )
    client_env = {
        item["name"]: item["value"]
        for item in build_client_deployment(session)["spec"]["template"]["spec"][
            "containers"
        ][0]["env"]
    }
    assert client_env["IPERF_EXPORTER_CONTEXT_SRC_NODE"] == long_name
    assert (
        client_env["IPERF_EXPORTER_CONTEXT_MEASUREMENT_ID"]
        == measurement["metadata"]["name"]
    )


def test_explicit_empty_session_dimensions_are_rejected():
    for field_name in ("directions", "networkModes"):
        measurement = _measurement()
        measurement["spec"][field_name] = []

        try:
            expand_measurement_sessions(
                measurement,
                _profile(),
                node_addresses={
                    "worker-a": "10.0.0.10",
                    "worker-b": "10.0.0.11",
                },
                default_image="iperf_exporter:dev",
            )
        except ValueError as exc:
            assert "must not be empty" in str(exc)
        else:  # pragma: no cover - explicit failure branch
            raise AssertionError(f"{field_name}=[] should be rejected")


def test_label_values_normalize_non_ascii_characters():
    assert kubernetes_label_value("nódé/東京") == "nd"
