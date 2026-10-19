# Ceph + Grafana Dashboard Setup

This adds a ready-made Grafana dashboard and provisioning to visualize your Ceph cluster using Prometheus metrics scraped from `ceph-mgr`.

Prereqs
- Ceph cluster with `ceph-mgr` running
- Prometheus reachable from Grafana
- Tailscale MagicDNS preferred for stable hostnames

1) Enable ceph-mgr Prometheus exporter
```bash
ceph mgr module enable prometheus
# default bind :9283 on the active mgr node
# Optional: set address/port
ceph config set mgr mgr/prometheus/server_addr 0.0.0.0
ceph config set mgr mgr/prometheus/server_port 9283
```

2) Prometheus scrape job
Add to your `prometheus.yml` (aggregator on `opi5` per your notes):
```yaml
scrape_configs:
  - job_name: ceph
    scrape_interval: 15s
    static_configs:
      - targets:
          - mgr1.velociraptor-scylla.ts.net:9283
          - mgr2.velociraptor-scylla.ts.net:9283
```
Use your actual Tailscale hostnames for mgr nodes.

3) Grafana provisioning
- Datasource file: `grafana/provisioning/datasources/prometheus.yaml`
  - Set env `PROMETHEUS_URL` to your aggregator, e.g. `http://opi5.velociraptor-scylla.ts.net:9090`
- Dashboards file: `grafana/provisioning/dashboards/ceph.yaml` points Grafana to load JSON from `/var/lib/grafana/dashboards/ceph`
- Dashboard JSON: `grafana/dashboards/ceph/cluster-overview.json`

If you run Grafana via Docker, mount:
```yaml
  grafana:
    image: grafana/grafana:10.4.3
    environment:
      - PROMETHEUS_URL=http://opi5.velociraptor-scylla.ts.net:9090
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
    ports:
      - "3000:3000"
```

4) What you get
- Cluster health, OSD up/in, PG states
- Capacity used %, client throughput, pool ops/s

5) Troubleshooting
- No data: check Prometheus has `ceph_*` metrics at `/graph` and targets Up
- Health panel shows numbers 0/1/2:
  - 0 OK, 1 WARN, 2 ERROR
- Adjust panel queries if your Ceph exporter exposes different metric names (older releases)
