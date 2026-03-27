import os
from unittest import TestCase, mock

from iperf_exporter.cli import (
    main,
    parse_args,
    run_client,
    run_exporter,
    setup_client,
    setup_exporter,
    stream_client_once,
    stream_client_output,
    stream_client_periodically,
)


class TestCLI(TestCase):
    @mock.patch.dict(
        os.environ,
        {
            "IPERF_EXPORTER_BIND_PORT": "9868",
        },
    )
    def test_parse_args_env(self):
        args = parse_args([])

        assert args.iperf_exporter_bind_port == 9868

    def test_setup_exporter_registers_collector_and_http_server(self):
        args = parse_args(
            ["--iperf_exporter_mode", "server", "--iperf_exporter_proto", "tcp"]
        )
        collector = mock.Mock()
        collector_cls = mock.Mock(return_value=collector)
        registry = mock.Mock()
        http_server_factory = mock.Mock()

        result = setup_exporter(
            args,
            collector_cls=collector_cls,
            registry=registry,
            http_server_factory=http_server_factory,
        )

        self.assertIs(result, collector)
        collector_cls.assert_called_once_with(
            port=5001,
            proto="tcp",
            len=1280,
            interval=1,
            metric_ttl=604800,
            additional_params="",
            context_client_bandwidth="",
            context_client_additional_params="",
            path_trace_ttl=300,
            path_trace_max_hops=16,
            path_trace_timeout=10,
            context_labels={
                "measurement_id": "",
                "profile_ref": "",
                "session_id": "",
                "execution_mode": "",
                "direction": "",
                "network_mode": "",
                "src_node": "",
                "dst_node": "",
                "src_cluster": "",
                "dst_cluster": "",
            },
        )
        registry.register.assert_called_once_with(collector)
        http_server_factory.assert_called_once_with(9868)

    def test_run_exporter_uses_idle_function(self):
        args = parse_args(["--iperf_exporter_mode", "server"])
        idle_fn = mock.Mock()

        run_exporter(
            args,
            collector_cls=mock.Mock(return_value=mock.Mock()),
            registry=mock.Mock(),
            http_server_factory=mock.Mock(),
            idle_fn=idle_fn,
        )

        idle_fn.assert_called_once_with()

    def test_setup_client_runs_client(self):
        args = parse_args(
            ["--iperf_exporter_mode", "client", "--iperf_exporter_proto", "tcp"]
        )
        client = mock.Mock()
        client_cls = mock.Mock(return_value=client)

        result = setup_client(args, client_cls=client_cls)

        self.assertIs(result, client)
        client_cls.assert_called_once_with(
            port=5001,
            proto="tcp",
            interval=1,
            bandwidth="1M",
            duration=315360000,
            peer="127.0.0.1",
            additional_params="",
        )
        client.run.assert_called_once_with()

    def test_parse_args_additional_params(self):
        args = parse_args(
            [
                "--iperf_exporter_server_additional_params=--histograms=100u,20",
                "--iperf_exporter_client_additional_params=--trip-times",
                "--iperf_exporter_context_client_bandwidth=100M",
                "--iperf_exporter_context_client_additional_params=--trip-times",
                "--iperf_exporter_path_trace_ttl=60",
                "--iperf_exporter_context_network_mode=service",
                "--iperf_exporter_context_direction=sourceToDestination",
            ]
        )

        self.assertEqual(
            args.iperf_exporter_server_additional_params, "--histograms=100u,20"
        )
        self.assertEqual(args.iperf_exporter_client_additional_params, "--trip-times")
        self.assertEqual(args.iperf_exporter_context_client_bandwidth, "100M")
        self.assertEqual(
            args.iperf_exporter_context_client_additional_params, "--trip-times"
        )
        self.assertEqual(args.iperf_exporter_path_trace_ttl, 60)
        self.assertEqual(args.iperf_exporter_context_network_mode, "service")
        self.assertEqual(args.iperf_exporter_context_direction, "sourceToDestination")

    def test_run_client_uses_output_loop(self):
        args = parse_args(["--iperf_exporter_mode", "client"])
        client = mock.Mock()
        client_cls = mock.Mock(return_value=client)
        output_loop_fn = mock.Mock()

        run_client(args, client_cls=client_cls, output_loop_fn=output_loop_fn)

        output_loop_fn.assert_called_once_with(client)

    def test_run_client_probe_uses_single_run_loop(self):
        args = parse_args(
            [
                "--iperf_exporter_mode",
                "client",
                "--iperf_exporter_client_execution_mode",
                "probe",
            ]
        )
        client = mock.Mock()
        client_cls = mock.Mock(return_value=client)
        probe_loop_fn = mock.Mock(return_value=0)

        run_client(args, client_cls=client_cls, probe_loop_fn=probe_loop_fn)

        probe_loop_fn.assert_called_once_with(client)
        self.assertEqual(client.last_exit_code, 0)

    def test_run_client_periodic_probe_uses_periodic_loop(self):
        args = parse_args(
            [
                "--iperf_exporter_mode",
                "client",
                "--iperf_exporter_client_execution_mode",
                "periodicProbe",
                "--iperf_exporter_client_period_seconds",
                "30",
            ]
        )
        client = mock.Mock()
        client_cls = mock.Mock(return_value=client)
        periodic_loop_fn = mock.Mock()

        run_client(
            args,
            client_cls=client_cls,
            periodic_loop_fn=periodic_loop_fn,
        )

        periodic_loop_fn.assert_called_once_with(client, 30)

    def test_stream_client_output_supervises_process(self):
        client = mock.Mock()

        def stop_after_first_iteration(_):
            raise RuntimeError("stop-loop")

        with self.assertRaisesRegex(RuntimeError, "stop-loop"):
            stream_client_output(client, sleep_fn=stop_after_first_iteration)

        client.ensure_running.assert_called_once_with()
        client.read_output.assert_called_once_with()

    def test_stream_client_once_exits_when_client_process_finishes(self):
        client = mock.Mock()
        client.poll_exit_code.side_effect = [None, 0]

        stream_client_once(client, sleep_fn=lambda _: None)

        self.assertEqual(client.read_output.call_count, 2)

    def test_stream_client_periodically_restarts_client(self):
        client = mock.Mock()

        def stop_after_first_restart(_):
            raise RuntimeError("stop-loop")

        with mock.patch(
            "iperf_exporter.cli.stream_client_once",
            side_effect=[0],
        ) as probe_once:
            with self.assertRaisesRegex(RuntimeError, "stop-loop"):
                stream_client_periodically(
                    client,
                    5,
                    sleep_fn=stop_after_first_restart,
                )

        probe_once.assert_called_once_with(client, sleep_fn=stop_after_first_restart)
        client.run.assert_not_called()

    @mock.patch("iperf_exporter.cli.run_exporter")
    def test_main_dispatch_server(self, run_exporter_mock):
        result = main(["--iperf_exporter_mode", "server"])

        self.assertEqual(result, 0)
        run_exporter_mock.assert_called_once()

    @mock.patch("iperf_exporter.cli.run_client")
    def test_main_dispatch_client(self, run_client_mock):
        result = main(["--iperf_exporter_mode", "client"])

        self.assertEqual(result, 0)
        run_client_mock.assert_called_once()

    def test_main_dispatch_client_probe_failure_exit_code(self):
        client = mock.Mock(last_exit_code=7)

        with mock.patch("iperf_exporter.cli.run_client", return_value=client):
            result = main(
                [
                    "--iperf_exporter_mode",
                    "client",
                    "--iperf_exporter_client_execution_mode",
                    "probe",
                ]
            )

        self.assertEqual(result, 7)
