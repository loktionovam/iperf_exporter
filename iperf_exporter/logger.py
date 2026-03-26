import logging
import os
from pythonjsonlogger import jsonlogger


def _debug_enabled(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on", "debug"}


DEBUG = _debug_enabled(os.environ.get("DEBUG", "0"))
MODE = os.environ.get("IPERF_EXPORTER_MODE", "server")
if MODE == "server":
    log = logging.getLogger("iperf_exporter_server")
elif MODE == "client":
    log = logging.getLogger("iperf_exporter_client")
else:
    log = logging.getLogger("iperf_exporter")

log.setLevel(logging.DEBUG if DEBUG else logging.INFO)

logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logHandler.setFormatter(formatter)
if not log.handlers:
    log.addHandler(logHandler)

if DEBUG:
    log.debug(f"Current log level is {logging.getLevelName(log.level)}")
