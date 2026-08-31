FROM python:3.14-alpine@sha256:05b2b8b732ecd268fee8727a369f936f022d1321b59befd13c30ede22769dcdc

# Apply security fixes even when the pinned Python image has not been rebuilt.
# hadolint ignore=DL3018
RUN apk upgrade --no-cache \
    && apk add --no-cache iperf iproute2 iputils \
    && adduser -H -S -D -u 1000 iperf_exporter

WORKDIR /app

COPY pyproject.toml README.md requirements.txt ./
COPY iperf_exporter ./iperf_exporter

# hadolint ignore=DL3013
RUN python -m pip install --no-cache-dir . \
    && python -m pip uninstall --yes pip setuptools

ARG VERSION=v4.0.0

USER iperf_exporter

LABEL maintainer=loktionovam@gmail.com
LABEL version=${VERSION}

ENV DEBUG=0 \
    IPERF_EXPORTER_MODE=server \
    IPERF_EXPORTER_VERSION=${VERSION} \
    IPERF_EXPORTER_PORT=5001 \
    IPERF_EXPORTER_PROTO=udp \
    IPERF_EXPORTER_LEN=1280 \
    IPERF_EXPORTER_BIND_PORT=9868 \
    IPERF_EXPORTER_METRIC_TTL=3600 \
    IPERF_EXPORTER_CLIENT_BANDWIDTH=1M \
    IPERF_EXPORTER_CLIENT_PEER=127.0.0.1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "iperf_exporter"]
