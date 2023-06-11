FROM python:3-alpine AS base

# Manual upgrade vulnerable packages
# https://github.com/docker-library/python/issues/680
RUN apk upgrade expat expat-dev libcrypto1.1 libssl1.1

FROM base as iperf_exporter

RUN apk update \
    && apk add gcc libc-dev iperf \
    && adduser -H -S -D -u 1000 iperf_exporter

COPY . /setup/

RUN cd /setup \
    && python setup.py install \
    && find /usr/local/lib -name "*.pyc" -delete

ARG VERSION=dev
ARG  MODE=server
USER iperf_exporter

LABEL maintainer=loktionovam@gmail.com
LABEL version=${VERSION}
ENV DEBUG=0 \
    IPERF_EXPORTER_MODE=${MODE} \
    IPERF_EXPORTER_PORT=5001 \
    IPERF_EXPORTER_PROTO=udp \
    IPERF_EXPORTER_LEN=1280 \
    IPERF_EXPORTER_BIND_PORT=9868 \
    IPERF_EXPORTER_METRIC_TTL=604800 \
    IPERF_EXPORTER_CLIENT_BANDWIDTH=1M \
    IPERF_EXPORTER_CLIENT_PEER=127.0.0.1

ENTRYPOINT [ "python", "-m", "iperf_exporter" ]

FROM iperf_exporter AS vulnscan
COPY --from=aquasec/trivy:latest /usr/local/bin/trivy /usr/local/bin/trivy
USER root
RUN trivy rootfs --exit-code 1 --no-progress --skip-files /usr/local/bin/trivy /

FROM iperf_exporter as main
