import logging

from pythonjsonlogger.json import JsonFormatter

log = logging.getLogger("iperf_exporter")


def configure_logging(*, debug: bool, mode: str) -> None:
    log.name = (
        f"iperf_exporter_{mode}" if mode in {"server", "client"} else "iperf_exporter"
    )
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    log.propagate = False

    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            JsonFormatter(fmt="%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        log.addHandler(handler)

    if debug:
        log.debug("Current log level is %s", logging.getLevelName(log.level))


configure_logging(debug=False, mode="")
