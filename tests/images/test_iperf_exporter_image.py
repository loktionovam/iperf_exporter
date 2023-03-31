import subprocess
from unittest import TestCase
import pytest
import json
from time import sleep


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
        self.assertEqual("iperf_exporter", parsed_log_entry["name"])
