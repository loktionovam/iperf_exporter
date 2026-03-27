# Demo Layout

The demo area is now split into two independent catalogs:

- [docker-compose](./docker-compose/README.md)
  Local containers with Prometheus and Grafana.
- [kind](./kind/README.md)
  `kopf` operator, CRDs, example `MeasurementProfile` / `LinkMeasurement` resources, and an in-cluster Prometheus + Grafana stack with provisioned dashboards.

Use the docker-compose demo when you want quick local dashboards without Kubernetes.

Use the kind demo when you want to validate the operator and generated `MeasurementSession` resources.

Reusable non-demo `MeasurementProfile` examples are documented in
[docs/profile-catalog.md](../docs/profile-catalog.md).
