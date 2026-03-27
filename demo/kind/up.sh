#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-iperf-demo}"
EXPORTER_IMAGE_NAME="${EXPORTER_IMAGE_NAME:-iperf_exporter:kind-demo}"
OPERATOR_IMAGE_NAME="${OPERATOR_IMAGE_NAME:-iperf_operator:kind-demo}"
KUBECTL_CONTEXT="kind-${CLUSTER_NAME}"
NAMESPACE="iperf-exporter-demo"
INGRESS_HOST_SUFFIX="${INGRESS_HOST_SUFFIX:-127.0.0.1.nip.io}"
INGRESS_HTTP_PORT="${INGRESS_HTTP_PORT:-8080}"
INGRESS_NGINX_VERSION="${INGRESS_NGINX_VERSION:-controller-v1.15.1}"
INGRESS_MANIFEST_URL="https://raw.githubusercontent.com/kubernetes/ingress-nginx/${INGRESS_NGINX_VERSION}/deploy/static/provider/kind/deploy.yaml"

cd "${ROOT_DIR}"

cluster_exists() {
  kind get clusters | grep -qx "${CLUSTER_NAME}"
}

cluster_has_ingress_ports() {
  local ports_json

  ports_json="$(docker inspect "${CLUSTER_NAME}-control-plane" --format '{{json .NetworkSettings.Ports}}' 2>/dev/null || true)"
  [[ "${ports_json}" == *'"80/tcp"'* && "${ports_json}" == *'"443/tcp"'* ]]
}

if cluster_exists && ! cluster_has_ingress_ports; then
  echo "Recreating kind cluster ${CLUSTER_NAME} to add ingress port mappings"
  kind delete cluster --name "${CLUSTER_NAME}"
fi

if ! cluster_exists; then
  kind create cluster --name "${CLUSTER_NAME}" --config demo/kind/cluster.yaml
fi

kubectl --context "${KUBECTL_CONTEXT}" label node "${CLUSTER_NAME}-control-plane" ingress-ready=true --overwrite
kubectl --context "${KUBECTL_CONTEXT}" apply -f "${INGRESS_MANIFEST_URL}"
kubectl --context "${KUBECTL_CONTEXT}" -n ingress-nginx patch deploy ingress-nginx-controller --type merge \
  -p '{"spec":{"template":{"spec":{"nodeSelector":{"kubernetes.io/os":"linux","ingress-ready":"true"}}}}}'
kubectl --context "${KUBECTL_CONTEXT}" -n ingress-nginx rollout status deploy/ingress-nginx-controller --timeout=180s

docker build -t "${EXPORTER_IMAGE_NAME}" .
docker build -f Dockerfile.operator -t "${OPERATOR_IMAGE_NAME}" .
kind load docker-image "${EXPORTER_IMAGE_NAME}" --name "${CLUSTER_NAME}"
kind load docker-image "${OPERATOR_IMAGE_NAME}" --name "${CLUSTER_NAME}"

kubectl --context "${KUBECTL_CONTEXT}" apply -f demo/kind/manifests/namespace.yaml

kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" create configmap prometheus-config \
  --from-file=prometheus.yml=demo/kind/prometheus/prometheus.yml \
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

kubectl --context "${KUBECTL_CONTEXT}" apply -k demo/kind/manifests
kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" set image deploy/iperf-exporter-operator operator="${OPERATOR_IMAGE_NAME}"
kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" set env deploy/iperf-exporter-operator IPERF_OPERATOR_DEFAULT_EXPORTER_IMAGE="${EXPORTER_IMAGE_NAME}"
kubectl --context "${KUBECTL_CONTEXT}" -n iperf-exporter-demo rollout status deploy/iperf-exporter-operator --timeout=180s

kubectl --context "${KUBECTL_CONTEXT}" delete -f demo/kind/examples/measurement-tcp-probe.yaml --ignore-not-found=true
kubectl --context "${KUBECTL_CONTEXT}" delete -f demo/kind/examples/measurement-udp-probe.yaml --ignore-not-found=true
kubectl --context "${KUBECTL_CONTEXT}" apply -f demo/kind/examples

kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" rollout restart \
  deploy/iperf-exporter-operator \
  deploy/prometheus \
  deploy/grafana

EXPORTER_PODS="$(kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" get pod -l app.kubernetes.io/name=iperf-exporter -o name || true)"
if [[ -n "${EXPORTER_PODS}" ]]; then
  kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" delete ${EXPORTER_PODS} --ignore-not-found=true >/dev/null
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

"${ROOT_DIR}/demo/kind/verify.sh"

echo "Grafana is available at http://grafana.${INGRESS_HOST_SUFFIX}:${INGRESS_HTTP_PORT}"
echo "Prometheus is available at http://prometheus.${INGRESS_HOST_SUFFIX}:${INGRESS_HTTP_PORT}"
