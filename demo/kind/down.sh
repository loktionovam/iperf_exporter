#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-iperf-demo}"
REMOTE_CLUSTER_NAME="${REMOTE_CLUSTER_NAME:-iperf-demo-remote}"

kind delete cluster --name "${CLUSTER_NAME}"
kind delete cluster --name "${REMOTE_CLUSTER_NAME}"
