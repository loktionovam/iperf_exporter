import logging
import os
from pythonjsonlogger import jsonlogger

DEBUG = int(os.environ.get("DEBUG", "0"))
MODE = os.environ.get("IPERF_EXPORTER_MODE", "server")
if MODE == "server":
    log = logging.getLogger("iperf_exporter_server")
elif MODE == "client":
    log = logging.getLogger("iperf_exporter_client")

log.setLevel(logging.DEBUG if DEBUG else logging.INFO)

logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logHandler.setFormatter(formatter)
log.addHandler(logHandler)

if DEBUG:
    log.debug(f"Current log level is {logging.getLevelName(log.level)}")
