#!/usr/bin/env python3
"""Fix missing MASQUERADE + missing port 30883 DNAT rule"""
import subprocess

def kexec(cmd):
    upf = "upf-embb-849c45b856-ns98k"
    r = subprocess.run(
        ["kubectl", "exec", "-n", "embb", upf, "--", "bash", "-c", cmd],
        capture_output=True, text=True, timeout=15)
    print(r.stdout.strip() or r.stderr.strip())
    return r.returncode == 0

MMTC_IP  = "10.99.208.6"
URLLC_IP = "10.102.49.22"
EMBB_IP  = "10.109.126.231"

print("=== Adding MASQUERADE for UE subnets ===")
# Without this, return packets from pods can't reach UE IPs (10.45/46/47.x)
kexec("iptables -t nat -A POSTROUTING -s 10.45.0.0/16 -j MASQUERADE")
kexec("iptables -t nat -A POSTROUTING -s 10.46.0.0/16 -j MASQUERADE")
kexec("iptables -t nat -A POSTROUTING -s 10.47.0.0/16 -j MASQUERADE")
print("MASQUERADE rules added")

print("\n=== Adding missing port 30883 DNAT (mMTC NodePort) ===")
kexec(f"iptables -t nat -A PREROUTING -p tcp --dport 30883 -j DNAT --to-destination {MMTC_IP}:1883")
kexec(f"iptables -t nat -A PREROUTING -p udp --dport 30883 -j DNAT --to-destination {MMTC_IP}:1883")
print("Port 30883 rules added")

print("\n=== Current PREROUTING rules ===")
kexec("iptables -t nat -L PREROUTING -n")

print("\n=== Current POSTROUTING rules ===")
kexec("iptables -t nat -L POSTROUTING -n | grep -E '(MASQ|Chain)'")

print("\n=== Enable ip_forward on host ===")
kexec("echo 1 > /proc/sys/net/ipv4/ip_forward && echo 'ip_forward enabled'")

print("\nDone. Wait 30s then check orchestrator log.")
