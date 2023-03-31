import pytest
import subprocess
import os
import testinfra

IPERF_EXPORTER_SERVER_IMAGE_NAME = os.environ.get(
    "IPERF_EXPORTER_SERVER_IMAGE_NAME", "loktionovam/iperf_exporter_server"
)
IPERF_EXPORTER_IMAGE_TAG = os.environ.get("IPERF_EXPORTER_IMAGE_TAG", "4229e23")


# scope='session' uses the same container for all the tests;
# scope='function' uses a new container per test function.
@pytest.fixture(scope="class")
def host(request):
    # run a container
    docker_id = (
        subprocess.check_output(
            [
                "docker",
                "run",
                "-d",
                f"{IPERF_EXPORTER_SERVER_IMAGE_NAME}:{IPERF_EXPORTER_IMAGE_TAG}",
            ]
        )
        .decode()
        .strip()
    )
    # return a testinfra connection to the container
    host = testinfra.get_host("docker://" + docker_id)
    request.cls.host = host
    yield host
    # at the end of the test suite, destroy the container
    subprocess.check_call(["docker", "rm", "-f", docker_id])
