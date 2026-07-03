#!/usr/bin/env python3
"""Find correct mosquitto pod IP and fix mMTC DNAT"""
import subprocess

UPF = "upf-embb-849c45b856-ns98k"

def kexec(cmd):
    r = subprocess.run(["kubectl","exec","-n","embb",UPF,"--","bash","-c",cmd],
                       capture_output=True, text=True, timeout=15)
    out = (r.stdout+r.stderr).strip()
    if out: print(out)
    return r.returncode == 0

def kubectl(args):
    r = subprocess.run(["kubectl"]+args, capture_output=True, text=True, timeout=15)
    return r.stdout.strip()

print("=== All pods in mmtc namespace ===")
print(kubectl(["get","pods","-n","mmtc","-o","wide","--no-headers"]))

print("\n=== Services in mmtc namespace ===")
print(kubectl(["get","svc","-n","mmtc","--no-headers"]))

print("\n=== Finding mosquitto pod specifically ===")
# Try different selectors
for label in ["app=mosquitto","app=mmtc-mosquitto","app=mmtc-app","component=mqtt","app=mqtt"]:
    ip = kubectl(["get","pod","-n","mmtc",f"-l{label}",
                  "-o","jsonpath={.items[0].status.podIP}"])
    if ip and ip != "<no value>":
        print(f"  {label} → {ip}")

print("\n=== Test port 1883 on current mmtc-app pod (10.244.2.9) ===")
kexec("timeout 3 bash -c '</dev/tcp/10.244.2.9/1883' && echo '1883:OPEN' || echo '1883:REFUSED'")

print("\n=== Scan mmtc pods for open MQTT port ===")
pods_raw = kubectl(["get","pods","-n","mmtc","-o",
                    "jsonpath={range .items[*]}{.metadata.name}={.status.podIP}\\n{end}"])
for line in pods_raw.splitlines():
    if "=" in line:
        name, ip = line.split("=",1)
        if ip:
            result = subprocess.run(
                ["kubectl","exec","-n","embb",UPF,"--","bash","-c",
                 f"timeout 2 bash -c '</dev/tcp/{ip}/1883' && echo OPEN || echo CLOSED"],
                capture_output=True, text=True, timeout=10)
            status = (result.stdout+result.stderr).strip()
            print(f"  {name} ({ip}):1883 → {status}")
