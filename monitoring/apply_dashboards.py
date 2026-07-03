#!/usr/bin/env python3
"""
apply_dashboards.py
Reads all grafana-*-dashboard.yaml files, extracts the embedded JSON,
and pushes them all to Grafana. Also patches the enhanced dashboard thresholds.
"""
import json, yaml, base64, urllib.request, urllib.error, re, sys, os

GRAFANA = "http://192.168.49.174:30300"
AUTH    = ("admin", "admin")

def api(method, path, body=None):
    url  = GRAFANA + path
    data = json.dumps(body).encode() if body else None
    r    = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    creds = base64.b64encode(f"{AUTH[0]}:{AUTH[1]}".encode()).decode()
    r.add_header("Authorization", f"Basic {creds}")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode()[:200]}

MONITORING_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 1. Apply legacy YAML-embedded dashboards ────────────────────────────────
yaml_files = [
    "grafana-app-dashboard.yaml",
    "grafana-hierarchical-dashboard.yaml",
    "grafana-orchestrator-dashboard.yaml",
]

for fname in yaml_files:
    fpath = os.path.join(MONITORING_DIR, fname)
    if not os.path.exists(fpath):
        print(f"  SKIP {fname} (not found)")
        continue
    try:
        with open(fpath) as f:
            docs = list(yaml.safe_load_all(f.read()))
        # Find ConfigMap with dashboard JSON
        for doc in docs:
            if not doc or doc.get("kind") != "ConfigMap":
                continue
            data_section = doc.get("data", {})
            for key, val in data_section.items():
                if not key.endswith(".json"):
                    continue
                dash_json = json.loads(val)
                # Null id so Grafana matches by uid and overwrites cleanly
                dash_json["id"] = None
                dash_json.pop("version", None)
                result = api("POST", "/api/dashboards/db", {
                    "dashboard": dash_json,
                    "folderId": 0,
                    "overwrite": True,
                })
                status = result.get("status", result.get("error", "?"))
                detail = result.get("detail", result.get("message", ""))[:80]
                url    = result.get("url", "")
                print(f"  {'✅' if status == 'success' else '❌'} {fname}/{key}: {status} {url} {detail}")
    except Exception as e:
        print(f"  ❌ {fname}: {e}")


# ── 2. Patch grafana.yaml (5G Network Slice Monitor) via ConfigMap ──────────
print("\nApplying grafana.yaml (5G Network Slice Monitor datasource config)...")
try:
    import subprocess
    r = subprocess.run(
        ["kubectl", "apply", "-f", os.path.join(MONITORING_DIR, "grafana.yaml")],
        capture_output=True, text=True, timeout=15
    )
    if r.returncode == 0:
        print(f"  ✅ grafana.yaml applied via kubectl")
    else:
        print(f"  ⚠️  kubectl apply: {r.stderr.strip()[:100]}")
except Exception as e:
    print(f"  ⚠️  kubectl apply skipped: {e}")

print("\nDone.")
