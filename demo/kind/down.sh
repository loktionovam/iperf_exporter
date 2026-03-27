#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-iperf-demo}"

kind delete cluster --name "${CLUSTER_NAME}"
