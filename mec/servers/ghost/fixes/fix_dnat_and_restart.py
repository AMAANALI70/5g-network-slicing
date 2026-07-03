#!/usr/bin/env python3
"""
fix_dnat_and_restart.py
=======================
1. Discovers current ClusterIPs for embb-app, urllc-app, mmtc-app services
2. Updates ALL iptables DNAT rules on kube worker to use stable ClusterIPs
   (via kubectl exec on the privileged embb UPF pod)
3. Restarts all UE clients on UERANSIM VM
"""
import subprocess, sys, time

UERANSIM_IP   = "192.168.49.139"
UERANSIM_USER = "shinegami"
UERANSIM_PASS = "123"
EDGE_IP       = "192.168.49.171"

def run(cmd, shell=False, timeout=30):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=shell)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

def kubectl(args, timeout=30):
    code, out, err = run(["kubectl"] + args, timeout=timeout)
    return code == 0, out, err

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ── Step 1: Get service ClusterIPs ────────────────────────────────────────────
log("STEP 1: Discovering service ClusterIPs...")

services = {
    "embb-app":    ("embb",          30880, 8080),    # nginx HLS
    "urllc-app":   ("urllc",         1880,  1880),    # Node-RED
    "mmtc-app":    ("mmtc",          1883,  1883),    # Mosquitto MQTT
    "default-app": ("default-slice", 30800, 80),      # default best-effort
}

clusterips = {}
for svc, (ns, sport, dport) in services.items():
    ok, out, _ = kubectl(["get", "svc", svc, "-n", ns, "-o",
                           "jsonpath={.spec.clusterIP}"])
    if ok and out:
        clusterips[svc] = (out, ns, sport, dport)
        log(f"  {svc} → {out} (src:{sport} → dst:{dport})")
    else:
        log(f"  WARNING: Could not get ClusterIP for {svc} in {ns}")

if not clusterips:
    log("ERROR: No ClusterIPs found. Check kubectl access.")
    sys.exit(1)

# ── Step 2: Get UPF pod name ──────────────────────────────────────────────────
log("\nSTEP 2: Getting embb UPF pod name...")
ok, upf_pod, _ = kubectl(["get", "pod", "-n", "embb", "-l", "app=upf-embb",
                           "--no-headers", "-o", "custom-columns=:metadata.name"])
if not ok or not upf_pod:
    log("ERROR: Cannot find UPF pod")
    sys.exit(1)
upf_pod = upf_pod.split()[0]
log(f"  UPF pod: {upf_pod}")

# ── Step 3: Show current DNAT rules ─────────────────────────────────────────
log("\nSTEP 3: Current DNAT rules (before fix):")
ok, out, err = kubectl(["exec", "-n", "embb", upf_pod, "--",
                         "iptables", "-t", "nat", "-L", "PREROUTING", "-n"])
if ok:
    for line in out.splitlines():
        if "DNAT" in line or "Chain" in line:
            log(f"  {line}")
else:
    log(f"  Could not read iptables: {err}")

# ── Step 4: Build new DNAT rules script ──────────────────────────────────────
log("\nSTEP 4: Rebuilding DNAT rules with stable ClusterIPs...")

# Map: (src_port, ClusterIP, dst_port, interface_hint)
new_rules = []
for svc, (clusterip, ns, sport, dport) in clusterips.items():
    new_rules.append((sport, clusterip, dport, svc))

# Build iptables script
ipt_cmds = []
ipt_cmds.append("# Flush ALL existing DNAT rules in PREROUTING")
ipt_cmds.append("iptables -t nat -F PREROUTING")
ipt_cmds.append("echo 'PREROUTING flushed'")
ipt_cmds.append("")
ipt_cmds.append("# Re-add rules using stable ClusterIPs")

for sport, clusterip, dport, svc in new_rules:
    rule = (f"iptables -t nat -A PREROUTING -p tcp --dport {sport} "
            f"-j DNAT --to-destination {clusterip}:{dport}")
    ipt_cmds.append(f"# {svc}")
    ipt_cmds.append(rule)
    ipt_cmds.append(f"echo 'Added DNAT: :{sport} → {clusterip}:{dport}'")

# Also add the direct-port aliases used by clients
# embb_client uses port 30880 (NodePort proxy), also add port 8080 direct
embb_ip = clusterips.get("embb-app", (None,))[0]
urllc_ip = clusterips.get("urllc-app", (None,))[0]
mmtc_ip  = clusterips.get("mmtc-app", (None,))[0]

if embb_ip:
    ipt_cmds.append(f"# eMBB direct port alias")
    ipt_cmds.append(f"iptables -t nat -A PREROUTING -p tcp --dport 8080 -j DNAT --to-destination {embb_ip}:8080")
    ipt_cmds.append(f"echo 'Added DNAT: :8080 → {embb_ip}:8080'")

if urllc_ip:
    # Also add NodePort 30180 for URLLC Node-RED
    ipt_cmds.append(f"# URLLC Node-RED NodePort alias")
    ipt_cmds.append(f"iptables -t nat -A PREROUTING -p tcp --dport 30180 -j DNAT --to-destination {urllc_ip}:1880")
    ipt_cmds.append(f"echo 'Added DNAT: :30180 → {urllc_ip}:1880'")

ipt_cmds.append("")
ipt_cmds.append("echo '--- Final PREROUTING rules ---'")
ipt_cmds.append("iptables -t nat -L PREROUTING -n")

script = "\n".join(ipt_cmds)
log("  Script built. Applying via kubectl exec...")

# Run via kubectl exec (UPF pod is privileged)
code, out, err = run(
    ["kubectl", "exec", "-n", "embb", upf_pod, "--", "bash", "-c", script],
    timeout=30
)
if code == 0:
    log("  ✅ DNAT rules updated!")
    for line in out.splitlines():
        log(f"    {line}")
else:
    log(f"  ❌ Failed to apply iptables: {err}")
    log(f"  stdout: {out}")

# ── Step 5: Verify new rules ─────────────────────────────────────────────────
log("\nSTEP 5: Verifying new DNAT rules...")
ok, out, _ = kubectl(["exec", "-n", "embb", upf_pod, "--",
                       "iptables", "-t", "nat", "-L", "PREROUTING", "-n"])
if ok:
    for line in out.splitlines():
        if "DNAT" in line or "Chain" in line:
            log(f"  {line}")

# ── Step 6: Restart UE clients on UERANSIM ───────────────────────────────────
log("\nSTEP 6: Restarting UE clients on UERANSIM...")

restart_cmd = (
    "pkill -f embb_client.py 2>/dev/null; "
    "pkill -f urllc_client.py 2>/dev/null; "
    "pkill -f mmtc_client.py 2>/dev/null; "
    "sleep 2; "
    "echo 'Clients killed'; "
    "ip addr | grep uesimtun | grep inet | head -5; "
    "echo '---TUNS---'"
)

cmd = ["sshpass", "-p", UERANSIM_PASS,
       "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=8",
       f"{UERANSIM_USER}@{UERANSIM_IP}", restart_cmd]

code, out, err = run(cmd, timeout=20)
log(f"  Kill result (exit {code}):")
for line in out.splitlines():
    log(f"    {line}")
if err:
    log(f"  stderr: {err[:200]}")

# Check if uesimtun interfaces exist
if "uesimtun" not in out and "No such" not in out:
    log("  ⚠️  No uesimtun interfaces found — PDU sessions may be down!")
    log("  → UEs need to re-attach. Check nr-ue processes on UERANSIM.")
else:
    log("  ✅ uesimtun interfaces present — restarting clients...")

    # Restart all clients
    run_cmd = (
        f"cd /home/{UERANSIM_USER}/mec-clients && "
        f"nohup bash run_all.sh {EDGE_IP} > /tmp/run_all.log 2>&1 &"
        f"echo 'Clients started PID='$!"
    )
    cmd2 = ["sshpass", "-p", UERANSIM_PASS,
            "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=8",
            f"{UERANSIM_USER}@{UERANSIM_IP}", run_cmd]
    code2, out2, err2 = run(cmd2, timeout=15)
    log(f"  Restart result: {out2 or err2}")

# ── Step 7: Quick connectivity test ──────────────────────────────────────────
log("\nSTEP 7: Quick service reachability test from UPF pod...")
time.sleep(3)

for svc, (clusterip, ns, sport, dport) in clusterips.items():
    test_cmd = f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 3 http://{clusterip}:{dport}/ 2>&1 || echo 'failed'"
    ok, out, _ = kubectl(["exec", "-n", "embb", upf_pod, "--", "bash", "-c", test_cmd], timeout=10)
    log(f"  {svc} ({clusterip}:{dport}) → HTTP {out}")

log("\n✅ Fix script complete.")
log("Monitor orchestrator: tail -f /tmp/orchestrator.log")
log("Wait ~60s for clients to produce log entries with RTT/rate data.")
