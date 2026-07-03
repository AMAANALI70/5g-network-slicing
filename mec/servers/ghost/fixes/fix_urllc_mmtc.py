#!/usr/bin/env python3
"""Fix URLLC (port 1880) and mMTC (port 30883) by DNATting to pod IPs directly."""
import subprocess

UPF = "upf-embb-849c45b856-ns98k"

def kexec(cmd):
    r = subprocess.run(
        ["kubectl", "exec", "-n", "embb", UPF, "--", "bash", "-c", cmd],
        capture_output=True, text=True, timeout=15)
    out = (r.stdout + r.stderr).strip()
    if out: print(out)
    return r.returncode == 0

def kubectl(args):
    r = subprocess.run(["kubectl"] + args, capture_output=True, text=True, timeout=15)
    return r.stdout.strip()

# Get current pod IPs
print("=== Getting current pod IPs ===")
urllc_ip = kubectl(["get", "pod", "-n", "urllc", "-l", "app=urllc-app",
                     "-o", "jsonpath={.items[0].status.podIP}"])
mmtc_ip  = kubectl(["get", "pod", "-n", "mmtc",  "-l", "app=mmtc-app",
                     "-o", "jsonpath={.items[0].status.podIP}"])
print(f"  urllc-app pod IP: {urllc_ip}")
print(f"  mmtc-app  pod IP: {mmtc_ip}")

if not urllc_ip or not mmtc_ip:
    print("ERROR: Could not get pod IPs")
    exit(1)

# Remove stale 1880 DNAT (ClusterIP based) and replace with pod IP
print("\n=== Removing old 1880 DNAT (ClusterIP) ===")
kexec("iptables -t nat -D PREROUTING -p tcp --dport 1880 -j DNAT --to-destination 10.102.49.22:1880 2>/dev/null && echo 'Removed old 1880 DNAT' || echo 'Not found (ok)'")

print("\n=== Adding DNAT: port 1880 → urllc pod IP (Node-RED) ===")
kexec(f"iptables -t nat -A PREROUTING -p tcp --dport 1880 -j DNAT --to-destination {urllc_ip}:1880 && echo 'Added 1880→{urllc_ip}'")

print("\n=== Adding DNAT: port 30883 → mmtc pod IP (Mosquitto) ===")
kexec(f"iptables -t nat -D PREROUTING -p tcp --dport 30883 -j DNAT --to-destination {mmtc_ip}:1883 2>/dev/null; true")
kexec(f"iptables -t nat -A PREROUTING -p tcp --dport 30883 -j DNAT --to-destination {mmtc_ip}:1883 && echo 'Added 30883→{mmtc_ip}'")

print("\n=== Verify POSTROUTING MASQUERADE for UE subnets ===")
kexec("iptables -t nat -L POSTROUTING -n | grep -E '(MASQ|10\\.4[5-7])' || echo 'No MASQUERADE rules!'")

print("\n=== Adding MASQUERADE if missing ===")
kexec("iptables -t nat -C POSTROUTING -s 10.46.0.0/16 -j MASQUERADE 2>/dev/null || (iptables -t nat -A POSTROUTING -s 10.46.0.0/16 -j MASQUERADE && echo 'Added MASQUERADE 10.46')")
kexec("iptables -t nat -C POSTROUTING -s 10.47.0.0/16 -j MASQUERADE 2>/dev/null || (iptables -t nat -A POSTROUTING -s 10.47.0.0/16 -j MASQUERADE && echo 'Added MASQUERADE 10.47')")

print("\n=== Final PREROUTING state ===")
kexec("iptables -t nat -L PREROUTING -n")

print("\n=== Test connectivity from UPF pod ===")
kexec(f"curl -s -o /dev/null -w 'urllc-direct:%{{http_code}}\\n' --max-time 3 http://{urllc_ip}:1880/")
kexec(f"bash -c 'echo -e \"CONNECT\\n\" | timeout 3 bash -c \"cat </dev/tcp/{mmtc_ip}/1883\" && echo mqtt-direct:OK || echo mqtt-direct:FAIL' 2>/dev/null || echo 'mqtt test done'")

print(f"""
=== Now test from UERANSIM ===
  curl --interface uesimtun2 --max-time 5 -w "%{{http_code}}" http://192.168.49.171:1880/
  nc -w 3 -z 192.168.49.171 30883 && echo "MQTT OK"
""")
