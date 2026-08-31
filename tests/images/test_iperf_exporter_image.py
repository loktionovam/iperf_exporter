import subprocess
import json
import os
from time import monotonic, sleep
from unittest import TestCase

import pytest

IPERF_EXPORTER_IMAGE_NAME = os.environ.get(
    "IPERF_EXPORTER_IMAGE_NAME", "ghcr.io/loktionovam/iperf_exporter_server"
)
IPERF_EXPORTER_IMAGE_TAG = os.environ.get("IPERF_EXPORTER_IMAGE_TAG", "v4.0.0")
IPERF_OPERATOR_IMAGE_NAME = os.environ.get(
    "IPERF_OPERATOR_IMAGE_NAME", "ghcr.io/loktionovam/iperf_operator"
)


@pytest.mark.usefixtures("host")
class TestRequirements(TestCase):
    """
    Check the requirements for running the bot are set up in the Docker image
    correctly
    """

    def setUp(self):
        super(TestRequirements, self).setUp()

    def test_iperf_exporter_server_bind_port(self):
        sleep(1)
        self.assertTrue(self.host.socket("tcp://0.0.0.0:9868").is_listening)

    def test_iperf_exporter_server_process(self):
        """
        Check that exactly one python process launched
        and it is non-root process
        """
        process = self.host.process.get(comm="python")
        self.assertEqual("iperf_ex", process.user)
        self.assertEqual("nogroup", process.group)

    def test_iperf_exporter_server_logs(self):
        """
        Test that iperf exporter write logs in json format
        """
        sleep(2)
        log_entry = (
            subprocess.check_output(
                ["docker", "logs", self.host.backend.name], stderr=subprocess.STDOUT
            )
            .decode()
            .split("\n")[0]
        )
        parsed_log_entry = json.loads(log_entry)
        self.assertEqual("INFO", parsed_log_entry["levelname"])
        self.assertEqual("iperf_exporter_server", parsed_log_entry["name"])


@pytest.mark.parametrize("proto", ["tcp", "udp"])
def test_image_runs_real_client_session_and_exports_metrics(proto):
    image = f"{IPERF_EXPORTER_IMAGE_NAME}:{IPERF_EXPORTER_IMAGE_TAG}"
    server_id = subprocess.check_output(
        [
            "docker",
            "run",
            "-d",
            "-e",
            f"IPERF_EXPORTER_PROTO={proto}",
            image,
        ],
        text=True,
    ).strip()
    try:
        sleep(1)
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                f"container:{server_id}",
                "-e",
                "IPERF_EXPORTER_MODE=client",
                "-e",
                f"IPERF_EXPORTER_PROTO={proto}",
                "-e",
                "IPERF_EXPORTER_CLIENT_PEER=127.0.0.1",
                "-e",
                "IPERF_EXPORTER_CLIENT_DURATION=2",
                "-e",
                "IPERF_EXPORTER_CLIENT_EXECUTION_MODE=probe",
                image,
            ],
            check=True,
        )
        metrics = subprocess.check_output(
            [
                "docker",
                "exec",
                server_id,
                "wget",
                "-qO-",
                "http://127.0.0.1:9868/metrics",
            ],
            text=True,
        )
        assert f"iperf_exporter_{proto}_bandwidth" in metrics
        assert "iperf_exporter_active_streams" in metrics
        assert "iperf_exporter_connections_total" in metrics
        assert "iperf_exporter_samples_total" in metrics
        assert "iperf_exporter_test_runs_total" in metrics
        assert "iperf_exporter_test_duration_seconds" in metrics
        assert "iperf_exporter_sample_timestamp_seconds" in metrics
        assert "iperf_exporter_collector_duration_seconds" in metrics
        build_info = next(
            line
            for line in metrics.splitlines()
            if line.startswith("iperf_exporter_build_info{")
        )
        assert f'version="{IPERF_EXPORTER_IMAGE_TAG}"' in build_info
    finally:
        subprocess.run(["docker", "rm", "-f", server_id], check=False)


def test_image_stops_exporter_and_iperf_cleanly_on_sigterm():
    image = f"{IPERF_EXPORTER_IMAGE_NAME}:{IPERF_EXPORTER_IMAGE_TAG}"
    server_id = subprocess.check_output(
        ["docker", "run", "-d", image],
        text=True,
    ).strip()
    try:
        sleep(1)
        subprocess.run(
            ["docker", "exec", server_id, "pidof", "iperf"],
            check=True,
        )
        subprocess.run(
            ["docker", "stop", "--timeout", "5", server_id],
            check=True,
        )
        exit_code = subprocess.check_output(
            ["docker", "inspect", "--format", "{{.State.ExitCode}}", server_id],
            text=True,
        ).strip()
        assert exit_code == "0"
    finally:
        subprocess.run(["docker", "rm", "-f", server_id], check=False)


@pytest.mark.parametrize("startup_delay", [0, 2])
def test_operator_image_exposes_prometheus_metrics(startup_delay: int) -> None:
    image = f"{IPERF_OPERATOR_IMAGE_NAME}:{IPERF_EXPORTER_IMAGE_TAG}"
    operator_id = subprocess.check_output(
        [
            "docker",
            "run",
            "-d",
            "--entrypoint",
            "python",
            image,
            "-c",
            (
                "import time; "
                f"time.sleep({startup_delay}); "
                "from iperf_operator.metrics import "
                "get_operator_metrics,start_operator_metrics_server; "
                "get_operator_metrics(); "
                "start_operator_metrics_server(9869); "
                "time.sleep(30)"
            ),
        ],
        text=True,
    ).strip()
    try:
        deadline = monotonic() + 15
        while True:
            response = subprocess.run(
                [
                    "docker",
                    "exec",
                    operator_id,
                    "python",
                    "-c",
                    (
                        "import urllib.request; "
                        "print(urllib.request.urlopen("
                        "'http://127.0.0.1:9869/metrics', timeout=2).read().decode())"
                    ),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if response.returncode == 0:
                break
            if monotonic() >= deadline:
                subprocess.run(["docker", "logs", operator_id], check=False, timeout=5)
                pytest.fail(f"Operator metrics did not become ready: {response.stderr}")
            sleep(0.2)
        metrics = response.stdout
        assert "iperf_operator_build_info" in metrics
        assert "iperf_operator_start_time_seconds" in metrics
    finally:
        subprocess.run(["docker", "rm", "-f", operator_id], check=False)
