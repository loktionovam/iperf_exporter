from iperf_exporter.cli import parse_args, run_exporter
from unittest import TestCase, mock
from multiprocessing import Process
import os
import responses
import requests
from time import sleep
import psutil


class TestCLI(TestCase):
    def setUp(self):
        responses.mock.start()
        responses.add_passthru("http://127.0.0.1:9868/metrics")

    def tearDown(self):
        """Disable responses."""
        responses.mock.stop()
        responses.mock.reset()

    @mock.patch.dict(
        os.environ,
        {
            "IPERF_EXPORTER_BIND_PORT": "9868",
        },
    )
    def test_parse_args_env(self):
        args = parse_args([])

        assert args.iperf_exporter_bind_port == 9868

    def test_run_exporter(self):
        args = parse_args(["--iperf_exporter_mode", "server"])
        p = Process(target=run_exporter, args=(args,))
        try:
            p.start()
            sleep(2)
            response = requests.get("http://127.0.0.1:9868/metrics")
            self.assertEqual(200, response.status_code)
        finally:

            # ugly kill all because p.terminate() can't kill child subprocesses
            # https://stackoverflow.com/questions/6549669/how-to-kill-process-and-child-processes-from-python
            parent_pid = p.pid
            parent = psutil.Process(parent_pid)
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
