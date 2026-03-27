# Local Docker Compose Demo

This stack starts:

- `iperf-exporter-server-udp`
- `iperf-exporter-client-udp`
- `iperf-exporter-server-udp-2`
- `iperf-exporter-client-udp-2`
- `iperf-exporter-server-tcp`
- `iperf-exporter-client-tcp`
- `iperf-exporter-server-tcp-2`
- `iperf-exporter-client-tcp-2`
- `prometheus`
- `grafana`

The TCP pairs run `iperf2` with `--trip-times` on clients and `--histograms=100u,20` on servers, so the TCP quality dashboard includes burst latency, in-progress bytes, net power, latency histograms, path traces, configured client bandwidth limits and server-side socket stats from `ss -tin` in addition to throughput. The UDP dashboard also shows path traces and server-side socket queue depth from `ss -uin`.

Endpoints:

- Grafana: `http://localhost:3000`
- Prometheus: `http://localhost:9090`
- UDP exporter metrics: `http://localhost:9868/metrics`
- UDP exporter metrics 2: `http://localhost:9870/metrics`
- TCP exporter metrics: `http://localhost:9869/metrics`
- TCP exporter metrics 2: `http://localhost:9871/metrics`

Start:

```sh
make demo-compose-up
```

Stop:

```sh
make demo-compose-down
```

Validate config:

```sh
make demo-compose-config
```
