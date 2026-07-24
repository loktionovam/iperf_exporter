from unittest import TestCase

import iperf_exporter.logger


class TestLogger(TestCase):
    def test_server_log(self):
        iperf_exporter.logger.configure_logging(debug=False, mode="server")
        log = iperf_exporter.logger.log
        self.assertEqual(20, log.level)

        with self.assertLogs(logger=log, level=log.level) as cm:
            log.info("info message")
            log.warning("warn message")
        self.assertEqual(
            cm.output,
            [
                "INFO:iperf_exporter_server:info message",
                "WARNING:iperf_exporter_server:warn message",
            ],
        )

    def test_server_log_debug(self):
        iperf_exporter.logger.configure_logging(debug=True, mode="server")
        log = iperf_exporter.logger.log
        self.assertEqual(10, log.level)

        with self.assertLogs(logger=log, level=log.level) as cm:
            log.info("info message")
            log.warning("warn message")
            log.debug("debug message")
        self.assertEqual(
            cm.output,
            [
                "INFO:iperf_exporter_server:info message",
                "WARNING:iperf_exporter_server:warn message",
                "DEBUG:iperf_exporter_server:debug message",
            ],
        )
