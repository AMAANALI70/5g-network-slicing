#!/usr/bin/env python3
"""
Fix: Remove custom DNAT for NodePorts — let kube-proxy handle them.
Our DNAT intercepts 30880/30883 before kube-proxy, then FORWARD chain drops it.
kube-proxy already handles NodePorts correctly with its own SNAT/DNAT.
"""
import subprocess

UPF = "upf-embb-849c45b856-ns98k"

def kexec(cmd):
    r = subprocess.run(
        ["kubectl", "exec", "-n", "embb", UPF, "--", "bash", "-c", cmd],
        capture_output=True, text=True, timeout=15)
    out = (r.stdout + r.stderr).strip()
    if out:
        print(out)
    return r.returncode == 0

print("=== Step 1: Flush ALL custom PREROUTING DNAT rules ===")
kexec("iptables -t nat -F PREROUTING && echo 'Flushed'")

print("\n=== Step 2: Add ONLY port 1880 DNAT (not a NodePort, needs manual DNAT) ===")
kexec("iptables -t nat -A PREROUTING -p tcp --dport 1880 -j DNAT --to-destination 10.102.49.22:1880 && echo 'Added 1880'")

print("\n=== Step 3: Check host routes for UE subnets ===")
print("-- Routes for 10.45/46/47.x:")
kexec("ip route | grep -E '10\\.4[5-7]\\.' || echo 'NO UE SUBNET ROUTES!'")

print("\n=== Step 4: Check kube-proxy NodePort rules exist ===")
kexec("iptables -t nat -L KUBE-NODEPORTS -n 2>/dev/null | grep -E '(30880|30883|30180)' | head -10 || echo 'No kube-proxy rules found'")

print("\n=== Step 5: Verify PREROUTING now ===")
kexec("iptables -t nat -L PREROUTING -n")

print("\n=== Step 6: Test from UPF pod → services ===")
kexec("curl -s -o /dev/null -w 'embb:%{http_code}\\n' --max-time 3 http://192.168.49.171:30880/hls/master.m3u8 || true")
kexec("curl -s -o /dev/null -w 'urllc:%{http_code}\\n' --max-time 3 http://192.168.49.171:1880/ || true")
kexec("nc -w 3 -z 192.168.49.171 30883 && echo 'mqtt30883:OK' || echo 'mqtt30883:FAIL'")
kexec("nc -w 3 -z 192.168.49.171 1883  && echo 'mqtt1883:OK'  || echo 'mqtt1883:FAIL'")

print("\nDone. Now test from UERANSIM:")
print("  curl --interface uesimtun0 --max-time 5 -w '%{http_code}' http://192.168.49.171:30880/hls/master.m3u8")
