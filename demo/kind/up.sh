#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-iperf-demo}"
REMOTE_CLUSTER_NAME="${REMOTE_CLUSTER_NAME:-iperf-demo-remote}"
EXPORTER_IMAGE_NAME="${EXPORTER_IMAGE_NAME:-iperf_exporter:kind-demo}"
OPERATOR_IMAGE_NAME="${OPERATOR_IMAGE_NAME:-iperf_operator:kind-demo}"
KUBECTL_CONTEXT="kind-${CLUSTER_NAME}"
REMOTE_KUBECTL_CONTEXT="kind-${REMOTE_CLUSTER_NAME}"
NAMESPACE="iperf-exporter-demo"
LOCAL_CLUSTER_ID="${LOCAL_CLUSTER_ID:-cluster-a}"
REMOTE_CLUSTER_ID="${REMOTE_CLUSTER_ID:-cluster-b}"
INGRESS_HOST_SUFFIX="${INGRESS_HOST_SUFFIX:-127.0.0.1.nip.io}"
INGRESS_HTTP_PORT="${INGRESS_HTTP_PORT:-8080}"
INGRESS_HTTPS_PORT="${INGRESS_HTTPS_PORT:-8443}"
INGRESS_NGINX_VERSION="${INGRESS_NGINX_VERSION:-controller-v1.15.1}"
INGRESS_MANIFEST_URL="https://raw.githubusercontent.com/kubernetes/ingress-nginx/${INGRESS_NGINX_VERSION}/deploy/static/provider/kind/deploy.yaml"
REMOTE_ACCESS_SERVICEACCOUNT="${REMOTE_ACCESS_SERVICEACCOUNT:-iperf-exporter-remote-access}"
REMOTE_KUBECONFIG_SECRET_NAME="${REMOTE_KUBECONFIG_SECRET_NAME:-cluster-b-kubeconfig}"
REMOTE_KUBECONFIG_SECRET_KEY="${REMOTE_KUBECONFIG_SECRET_KEY:-cluster-b.kubeconfig}"

cd "${ROOT_DIR}"

if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif [[ -x "${ROOT_DIR}/venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

DEMO_TMP_DIR="$(mktemp -d)"
trap 'rm -r "${DEMO_TMP_DIR:?}"' EXIT

# Render isolated cluster names and host ports without changing the examples.
"${PYTHON_BIN}" - <<'PY' "${DEMO_TMP_DIR}" "${CLUSTER_NAME}" "${REMOTE_CLUSTER_NAME}" \
  "${LOCAL_CLUSTER_ID}" "${REMOTE_CLUSTER_ID}" "${REMOTE_KUBECONFIG_SECRET_NAME}" \
  "${REMOTE_KUBECONFIG_SECRET_KEY}" "${INGRESS_HOST_SUFFIX}" "${INGRESS_HTTP_PORT}" "${INGRESS_HTTPS_PORT}"
import re
import sys
from pathlib import Path

import yaml

output, cluster, remote, local_id, remote_id, secret, secret_key, suffix, http, https = sys.argv[1:]
output = Path(output)
replacements = {
    "iperf-demo-remote": remote,
    "iperf-demo": cluster,
    "cluster-a": local_id,
    "cluster-b": remote_id,
    "cluster-b-kubeconfig": secret,
    "cluster-b.kubeconfig": secret_key,
    "127.0.0.1.nip.io": suffix,
}
pattern = re.compile("|".join(re.escape(key) for key in sorted(replacements, key=len, reverse=True)))
for directory in ("examples", "manifests", "prometheus"):
    (output / directory).mkdir()
    for source in (Path("demo/kind") / directory).glob("*.y*ml"):
        text = pattern.sub(lambda match: replacements[match.group()], source.read_text(encoding="utf-8"))
        (output / directory / source.name).write_text(text, encoding="utf-8")
config = yaml.safe_load(Path("demo/kind/cluster.yaml").read_text(encoding="utf-8"))
for mapping in config["nodes"][0]["extraPortMappings"]:
    mapping["hostPort"] = int(http if mapping["containerPort"] == 80 else https)
(output / "cluster.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
PY

cluster_exists() {
  local cluster_name="$1"
  kind get clusters | grep -qx "${cluster_name}"
}

cluster_has_ingress_ports() {
  local cluster_name="$1"
  local ports_json

  ports_json="$(docker inspect "${cluster_name}-control-plane" --format '{{json .NetworkSettings.Ports}}' 2>/dev/null || true)"
  [[ "${ports_json}" == *'"80/tcp"'* && "${ports_json}" == *'"443/tcp"'* ]]
}

render_remote_kubeconfig() {
  local output_path="$1"
  local token server ca_data internal_kubeconfig

  token="$(
    kubectl --context "${REMOTE_KUBECTL_CONTEXT}" -n "${NAMESPACE}" create token \
      "${REMOTE_ACCESS_SERVICEACCOUNT}" --duration=24h
  )"
  internal_kubeconfig="${DEMO_TMP_DIR}/internal.kubeconfig"
  kind get kubeconfig --internal --name "${REMOTE_CLUSTER_NAME}" > "${internal_kubeconfig}"
  server="$(
    kubectl config view --raw --kubeconfig "${internal_kubeconfig}" \
      -o jsonpath="{.clusters[0].cluster.server}"
  )"
  ca_data="$(
    kubectl config view --raw --kubeconfig "${internal_kubeconfig}" \
      -o jsonpath="{.clusters[0].cluster.certificate-authority-data}"
  )"

  "${PYTHON_BIN}" - <<'PY' "${output_path}" "${REMOTE_CLUSTER_ID}" "${server}" "${ca_data}" "${token}"
import json
import sys

output_path, cluster_name, server, ca_data, token = sys.argv[1:]
kubeconfig = {
    "apiVersion": "v1",
    "kind": "Config",
    "clusters": [
        {
            "name": cluster_name,
            "cluster": {
                "server": server,
                "certificate-authority-data": ca_data,
            },
        }
    ],
    "users": [
        {
            "name": "iperf-exporter-remote-access",
            "user": {
                "token": token,
            },
        }
    ],
    "contexts": [
        {
            "name": cluster_name,
            "context": {
                "cluster": cluster_name,
                "user": "iperf-exporter-remote-access",
            },
        }
    ],
    "current-context": cluster_name,
}
with open(output_path, "w", encoding="utf-8") as fh:
    json.dump(kubeconfig, fh)
PY
  rm -f "${internal_kubeconfig}"
}

if cluster_exists "${CLUSTER_NAME}" && ! cluster_has_ingress_ports "${CLUSTER_NAME}"; then
  echo "Cluster ${CLUSTER_NAME} has no ingress port mappings. Use a new CLUSTER_NAME for this demo." >&2
  exit 1
fi

if ! cluster_exists "${CLUSTER_NAME}"; then
  kind create cluster --name "${CLUSTER_NAME}" --config "${DEMO_TMP_DIR}/cluster.yaml"
fi

if ! cluster_exists "${REMOTE_CLUSTER_NAME}"; then
  kind create cluster --name "${REMOTE_CLUSTER_NAME}" --config demo/kind/cluster-remote.yaml
fi

kubectl --context "${KUBECTL_CONTEXT}" label node "${CLUSTER_NAME}-control-plane" ingress-ready=true --overwrite
kubectl --context "${KUBECTL_CONTEXT}" apply -f "${INGRESS_MANIFEST_URL}"
kubectl --context "${KUBECTL_CONTEXT}" -n ingress-nginx patch deploy ingress-nginx-controller --type merge \
  -p '{"spec":{"template":{"spec":{"nodeSelector":{"kubernetes.io/os":"linux","ingress-ready":"true"}}}}}'
kubectl --context "${KUBECTL_CONTEXT}" -n ingress-nginx rollout status deploy/ingress-nginx-controller --timeout=180s

if [[ "${SKIP_IMAGE_BUILD:-false}" == "true" ]]; then
  docker image inspect "${EXPORTER_IMAGE_NAME}" "${OPERATOR_IMAGE_NAME}" >/dev/null
else
  docker build -t "${EXPORTER_IMAGE_NAME}" .
  docker build -f Dockerfile.operator -t "${OPERATOR_IMAGE_NAME}" .
fi
kind load docker-image "${EXPORTER_IMAGE_NAME}" --name "${CLUSTER_NAME}"
kind load docker-image "${EXPORTER_IMAGE_NAME}" --name "${REMOTE_CLUSTER_NAME}"
kind load docker-image "${OPERATOR_IMAGE_NAME}" --name "${CLUSTER_NAME}"

# Download monitoring images once, before rollout timeouts start on kind nodes.
for manifest in demo/kind/manifests/{prometheus,grafana}-deployment.yaml; do
  monitoring_image="$(
    kubectl --context "${KUBECTL_CONTEXT}" create --dry-run=client --validate=false \
      -f "${manifest}" -o jsonpath='{.spec.template.spec.containers[0].image}'
  )"
  docker pull "${monitoring_image}"
  kind load docker-image "${monitoring_image}" --name "${CLUSTER_NAME}"
done

kubectl --context "${KUBECTL_CONTEXT}" apply -f demo/kind/manifests/namespace.yaml
kubectl --context "${REMOTE_KUBECTL_CONTEXT}" apply -k demo/kind/remote-manifests

REMOTE_KUBECONFIG_FILE="${DEMO_TMP_DIR}/remote.kubeconfig"
render_remote_kubeconfig "${REMOTE_KUBECONFIG_FILE}"

kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" create secret generic "${REMOTE_KUBECONFIG_SECRET_NAME}" \
  --from-file=kubeconfig="${REMOTE_KUBECONFIG_FILE}" \
  --from-file="${REMOTE_KUBECONFIG_SECRET_KEY}"="${REMOTE_KUBECONFIG_FILE}" \
  --dry-run=client -o yaml | kubectl --context "${KUBECTL_CONTEXT}" apply -f -

kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" create configmap prometheus-config \
  --from-file=prometheus.yml="${DEMO_TMP_DIR}/prometheus/prometheus.yml" \
  --dry-run=client -o yaml | kubectl --context "${KUBECTL_CONTEXT}" apply -f -

kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" create configmap grafana-dashboards \
  --from-file=iperf-exporter-overview.json=grafana/dashboards/iperf-exporter-overview.json \
  --from-file=iperf-exporter-tcp-quality.json=grafana/dashboards/iperf-exporter-tcp-quality.json \
  --from-file=iperf-exporter-udp-quality.json=grafana/dashboards/iperf-exporter-udp-quality.json \
  --dry-run=client -o yaml | kubectl --context "${KUBECTL_CONTEXT}" apply -f -

kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" create configmap grafana-provisioning-dashboards \
  --from-file=dashboards.yml=demo/docker-compose/grafana/provisioning/dashboards/dashboards.yml \
  --dry-run=client -o yaml | kubectl --context "${KUBECTL_CONTEXT}" apply -f -

kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" create configmap grafana-provisioning-datasources \
  --from-file=prometheus.yml=demo/docker-compose/grafana/provisioning/datasources/prometheus.yml \
  --dry-run=client -o yaml | kubectl --context "${KUBECTL_CONTEXT}" apply -f -

helm upgrade --install iperf-operator helm/charts/iperf-operator \
  --kube-context "${KUBECTL_CONTEXT}" --namespace "${NAMESPACE}" \
  --set-string image.repository="${OPERATOR_IMAGE_NAME%:*}" \
  --set-string image.tag="${OPERATOR_IMAGE_NAME##*:}" \
  --set-string exporter.image.repository="${EXPORTER_IMAGE_NAME%:*}" \
  --set-string exporter.image.tag="${EXPORTER_IMAGE_NAME##*:}" \
  --set-string localClusterName="${LOCAL_CLUSTER_ID}" \
  --wait --timeout 180s
kubectl --context "${KUBECTL_CONTEXT}" apply -k "${DEMO_TMP_DIR}/manifests"

kubectl --context "${KUBECTL_CONTEXT}" delete -f "${DEMO_TMP_DIR}/examples/measurement-tcp-probe.yaml" --ignore-not-found=true
kubectl --context "${KUBECTL_CONTEXT}" delete -f "${DEMO_TMP_DIR}/examples/measurement-udp-probe.yaml" --ignore-not-found=true
kubectl --context "${KUBECTL_CONTEXT}" delete -f "${DEMO_TMP_DIR}/examples/measurement-tcp-cross-cluster.yaml" --ignore-not-found=true
kubectl --context "${KUBECTL_CONTEXT}" delete -f "${DEMO_TMP_DIR}/examples/remote-cluster-b.yaml" --ignore-not-found=true

shopt -s nullglob
for manifest in "${DEMO_TMP_DIR}"/examples/profile-*.yaml; do
  kubectl --context "${KUBECTL_CONTEXT}" apply -f "${manifest}"
done
kubectl --context "${KUBECTL_CONTEXT}" apply -f "${DEMO_TMP_DIR}/examples/remote-cluster-b.yaml"
for manifest in "${DEMO_TMP_DIR}"/examples/measurement-*.yaml; do
  kubectl --context "${KUBECTL_CONTEXT}" apply -f "${manifest}"
done
shopt -u nullglob

kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" rollout restart \
  deploy/iperf-operator \
  deploy/prometheus \
  deploy/grafana

EXPORTER_PODS=()
while IFS= read -r pod_name; do
  [[ -n "${pod_name}" ]] && EXPORTER_PODS+=("${pod_name}")
done < <(
  kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" get pod \
    -l app.kubernetes.io/name=iperf-exporter -o name || true
)
if ((${#EXPORTER_PODS[@]} > 0)); then
  kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" delete \
    "${EXPORTER_PODS[@]}" --ignore-not-found=true >/dev/null
fi

SERVER_WORKLOADS="$(kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" get statefulset -l app.kubernetes.io/name=iperf-exporter,app.kubernetes.io/component=server -o name || true)"
if [[ -n "${SERVER_WORKLOADS}" ]]; then
  for workload in ${SERVER_WORKLOADS}; do
    kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" get "${workload}" >/dev/null 2>&1 || continue
    kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" rollout status "${workload}" --timeout=180s
  done
fi

CLIENT_WORKLOADS="$(kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" get deploy -l app.kubernetes.io/name=iperf-exporter,app.kubernetes.io/component=client -o name || true)"
if [[ -n "${CLIENT_WORKLOADS}" ]]; then
  for workload in ${CLIENT_WORKLOADS}; do
    kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" get "${workload}" >/dev/null 2>&1 || continue
    kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" rollout status "${workload}" --timeout=180s
  done
fi

CLUSTER_NAME="${CLUSTER_NAME}" REMOTE_CLUSTER_NAME="${REMOTE_CLUSTER_NAME}" \
  REMOTE_CLUSTER_ID="${REMOTE_CLUSTER_ID}" INGRESS_HOST_SUFFIX="${INGRESS_HOST_SUFFIX}" \
  "${ROOT_DIR}/demo/kind/verify.sh"

INGRESS_HTTPS_PORT="$(docker inspect "${CLUSTER_NAME}-control-plane" --format '{{(index (index .NetworkSettings.Ports "443/tcp") 0).HostPort}}')"
echo "Grafana is available at https://grafana.${INGRESS_HOST_SUFFIX}:${INGRESS_HTTPS_PORT}"
echo "Prometheus is available at https://prometheus.${INGRESS_HOST_SUFFIX}:${INGRESS_HTTPS_PORT}"
echo "The demo uses a self-signed TLS certificate."
