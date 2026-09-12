#!/usr/bin/env python3
"""
SRE Cluster Monitor (v2.0.1)
----------------------------------------
Real in-cluster health monitor for OpenShift/Kubernetes. Uses the pod's
mounted ServiceAccount token to query the in-cluster API with the Python
standard library only (no pip deps) -> tiny image.

Optimizations vs 2.0.0:
  * ThreadingHTTPServer  -> /healthz stays instant while / does heavy queries
                            (fixes liveness-probe-induced restarts)
  * UTF-8 charset        -> emojis / middots render correctly
  * 10s in-memory cache  -> auto-refresh (10s) won't hammer the API server
                            on large clusters (hundreds of pods)

Reports on the cluster it runs in:
  - node readiness + pressure warnings
  - unhealthy pods + total container restarts
  - deployments not fully available
  - OpenShift ClusterOperators Degraded / not Available

Endpoints:
  /          -> HTML dashboard (auto-refresh 10s)
  /api       -> JSON health summary
  /metrics   -> Prometheus metrics
  /healthz   -> liveness (cheap; 200 unless ALERT_THRESHOLD exceeded)
  /ready     -> readiness (warm-up gate)
"""
import os
import ssl
import json
import time
import socket
import threading
import urllib.request

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SA = "/var/run/secrets/kubernetes.io/serviceaccount"
API = os.environ.get("API", "https://kubernetes.default.svc")
POD = os.environ.get("HOSTNAME", socket.gethostname())
VERSION = os.environ.get("APP_VERSION", "2.0.1")
WARMUP = int(os.environ.get("WARMUP_SECONDS", "5"))
CACHE_TTL = int(os.environ.get("CACHE_TTL_SECONDS", "10"))
# If unhealthy pods exceed this, /healthz returns 503 (self-alerting). 0 disables.
# NOTE: keep 0 on large clusters so /healthz stays cheap.
ALERT_THRESHOLD = int(os.environ.get("ALERT_THRESHOLD", "0"))
START = time.time()

_CACHE = {"t": 0.0, "data": None}
_LOCK = threading.Lock()


def _token():
    with open(f"{SA}/token") as f:
        return f.read().strip()


def _ctx():
    return ssl.create_default_context(cafile=f"{SA}/ca.crt")


def api_get(path):
    req = urllib.request.Request(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {_token()}"},
    )
    with urllib.request.urlopen(req, context=_ctx(), timeout=10) as r:
        return json.load(r)


def cluster_health():
    # Nodes
    nodes = api_get("/api/v1/nodes").get("items", [])
    nodes_ready = 0
    node_warnings = []
    for n in nodes:
        name = n["metadata"]["name"]
        for c in n["status"].get("conditions", []):
            if c["type"] == "Ready":
                if c["status"] == "True":
                    nodes_ready += 1
                else:
                    node_warnings.append(f"{name}: NotReady")
            if c["type"] in ("MemoryPressure", "DiskPressure", "PIDPressure") \
                    and c["status"] == "True":
                node_warnings.append(f"{name}: {c['type']}")

    # Pods
    pods = api_get("/api/v1/pods").get("items", [])
    unhealthy, restarts = [], 0
    for p in pods:
        ns = p["metadata"]["namespace"]
        pn = p["metadata"]["name"]
        phase = p["status"].get("phase")
        for cs in p["status"].get("containerStatuses", []):
            restarts += cs.get("restartCount", 0)
        if phase not in ("Running", "Succeeded"):
            unhealthy.append(f"{ns}/{pn} ({phase})")

    # Deployments not fully available
    deploys = api_get("/apis/apps/v1/deployments").get("items", [])
    deploy_issues = []
    for d in deploys:
        ns = d["metadata"]["namespace"]
        dn = d["metadata"]["name"]
        desired = d["spec"].get("replicas", 0)
        ready = d["status"].get("readyReplicas", 0)
        if ready < desired:
            deploy_issues.append(f"{ns}/{dn} ({ready}/{desired} ready)")

    # OpenShift ClusterOperators (best-effort; ignored on plain k8s)
    co_issues = []
    try:
        cos = api_get("/apis/config.openshift.io/v1/clusteroperators").get("items", [])
        for co in cos:
            name = co["metadata"]["name"]
            conds = {c["type"]: c["status"] for c in co["status"].get("conditions", [])}
            if conds.get("Available") != "True" or conds.get("Degraded") == "True":
                co_issues.append(name)
    except Exception:
        pass

    return {
        "nodes_total": len(nodes),
        "nodes_ready": nodes_ready,
        "node_warnings": node_warnings,
        "pods_total": len(pods),
        "pods_unhealthy": len(unhealthy),
        "unhealthy_list": unhealthy[:25],
        "container_restarts": restarts,
        "deployments_total": len(deploys),
        "deployment_issues": deploy_issues[:25],
        "clusteroperator_issues": co_issues,
    }


def cluster_health_cached():
    """Return cached health if fresh; otherwise refresh (thread-safe)."""
    now = time.time()
    with _LOCK:
        if _CACHE["data"] is not None and (now - _CACHE["t"]) < CACHE_TTL:
            return _CACHE["data"]
    # Query outside the lock so slow API calls don't block other threads
    data = cluster_health()
    with _LOCK:
        _CACHE["data"] = data
        _CACHE["t"] = time.time()
    return data


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_GET(self):
        up = time.time() - START

        # readiness: cheap warm-up gate
        if self.path == "/ready":
            return self._send(200, "ready") if up >= WARMUP \
                else self._send(503, "warming up")

        # liveness: cheap by default (no API call unless self-alerting enabled)
        if self.path == "/healthz":
            if ALERT_THRESHOLD > 0:
                try:
                    h = cluster_health_cached()
                    if h["pods_unhealthy"] > ALERT_THRESHOLD:
                        return self._send(503, f"unhealthy pods={h['pods_unhealthy']}")
                except Exception:
                    pass
            return self._send(200, "ok")

        # everything below needs cluster data
        try:
            h = cluster_health_cached()
        except Exception as e:
            return self._send(500, f"error querying cluster API: {e}")

        if self.path == "/metrics":
            return self._send(200,
                "# TYPE sre_nodes_total gauge\n"
                f"sre_nodes_total {h['nodes_total']}\n"
                "# TYPE sre_nodes_ready gauge\n"
                f"sre_nodes_ready {h['nodes_ready']}\n"
                "# TYPE sre_pods_total gauge\n"
                f"sre_pods_total {h['pods_total']}\n"
                "# TYPE sre_pods_unhealthy gauge\n"
                f"sre_pods_unhealthy {h['pods_unhealthy']}\n"
                "# TYPE sre_container_restarts_total counter\n"
                f"sre_container_restarts_total {h['container_restarts']}\n"
                "# TYPE sre_deployment_issues gauge\n"
                f"sre_deployment_issues {len(h['deployment_issues'])}\n"
                "# TYPE sre_clusteroperator_issues gauge\n"
                f"sre_clusteroperator_issues {len(h['clusteroperator_issues'])}\n")

        if self.path == "/api":
            return self._send(200, json.dumps(h, indent=2), "application/json")

        # HTML dashboard
        def ul(items):
            return "".join(f"<li>{x}</li>" for x in items) or "<li>none 🎉</li>"

        html = f"""<html><head><meta charset="utf-8"><title>SRE Cluster Monitor</title>
<meta http-equiv="refresh" content="10"></head>
<body style="font-family:sans-serif;max-width:760px;margin:40px auto">
<h1>SRE Cluster Monitor <small style="color:#888">v{VERSION}</small></h1>
<p><b>Nodes ready:</b> {h['nodes_ready']}/{h['nodes_total']}
   &nbsp;|&nbsp; <b>Pods:</b> {h['pods_total']} total,
   <b style="color:{'#c00' if h['pods_unhealthy'] else '#080'}">{h['pods_unhealthy']} unhealthy</b>
   &nbsp;|&nbsp; <b>Restarts:</b> {h['container_restarts']}</p>
<h3>Unhealthy pods</h3><ul>{ul(h['unhealthy_list'])}</ul>
<h3>Deployments not fully available</h3><ul>{ul(h['deployment_issues'])}</ul>
<h3>Node warnings</h3><ul>{ul(h['node_warnings'])}</ul>
<h3>ClusterOperators degraded/unavailable</h3><ul>{ul(h['clusteroperator_issues'])}</ul>
<hr><small>Served by pod {POD} · auto-refresh 10s · cache {CACHE_TTL}s · via RHACM + GitOps</small>
</body></html>"""
        self._send(200, html, "text/html")

    def log_message(self, *args):
        return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"SRE Cluster Monitor v{VERSION} on :{port} (threaded, cache {CACHE_TTL}s)")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
