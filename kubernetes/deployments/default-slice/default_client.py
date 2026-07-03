#!/usr/bin/env python3
"""
default_client.py — Best-Effort Slice Traffic Generator
========================================================
Generates low-priority HTTP traffic toward the default-slice
echo server via the GTP-U tunnel (uesimtun interface).

Uses SO_BINDTODEVICE to force traffic through the uesimtun
interface so it routes via GTP-U → UPF → default-slice pod.

Usage:
    sudo python3 default_client.py <uesimtun_iface> <node_ip> [port]

Example:
    sudo python3 default_client.py uesimtun9 192.168.49.171 30800

NOTE: Requires sudo because SO_BINDTODEVICE needs CAP_NET_RAW.
"""
import sys, time, socket, random, json
from datetime import datetime

def get_ue_ip(iface: str) -> str:
    import subprocess
    r = subprocess.run(['ip', '-4', 'addr', 'show', iface],
                       capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if 'inet ' in line:
            return line.strip().split()[1].split('/')[0]
    return ""

def http_get_via_iface(iface: str, host: str, port: int, path: str = "/") -> tuple:
    """Perform HTTP GET bound to a specific network interface using SO_BINDTODEVICE."""
    t0 = time.monotonic()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        # Bind to specific interface — forces traffic via GTP tunnel
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                     iface.encode() + b'\x00')
        s.connect((host, port))
        request = (f"GET {path} HTTP/1.1\r\n"
                   f"Host: {host}:{port}\r\n"
                   f"Connection: close\r\n\r\n")
        s.sendall(request.encode())
        response = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            response += chunk
        s.close()
        rtt_ms = (time.monotonic() - t0) * 1000
        status = int(response.split(b' ')[1]) if response else 0
        return True, status, rtt_ms
    except Exception as e:
        rtt_ms = (time.monotonic() - t0) * 1000
        return False, 0, rtt_ms

def run(iface: str, host: str, port: int):
    ue_ip = get_ue_ip(iface)
    if not ue_ip:
        print(f"[default] ERROR: Cannot find IP on {iface}. Is the UE connected?")
        sys.exit(1)

    print(f"[default] {iface} ({ue_ip}) → http://{host}:{port}/ (best-effort via SO_BINDTODEVICE)")
    print(f"[default] Traffic path: {iface} → GTP-U → ogstun-embb HTB 1:20 → kube-proxy → default-slice pod")

    req_count = 0
    err_count = 0
    rtt_sum   = 0.0
    t_start   = time.time()

    while True:
        ok, status, rtt_ms = http_get_via_iface(iface, host, port)

        if ok:
            req_count += 1
            rtt_sum += rtt_ms
            if req_count % 10 == 0:
                elapsed = time.time() - t_start
                avg_rtt = rtt_sum / req_count
                rate    = req_count / elapsed
                print(f"[default] {datetime.now().strftime('%H:%M:%S')} | "
                      f"reqs={req_count} | RTT={rtt_ms:.1f}ms avg={avg_rtt:.1f}ms | "
                      f"rate={rate:.2f}req/s | errors={err_count}")
        else:
            err_count += 1
            if err_count % 5 == 0:
                print(f"[default] {iface}: {err_count} errors | last_rtt={rtt_ms:.1f}ms")

        # Best-effort: random gap 1–4s (not aggressive — lowest priority)
        time.sleep(random.uniform(1.0, 4.0))

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: sudo python3 default_client.py <iface> <node_ip> [port]")
        sys.exit(1)
    iface = sys.argv[1]
    host  = sys.argv[2]
    port  = int(sys.argv[3]) if len(sys.argv) > 3 else 30800  # NodePort → nginx:80
    run(iface, host, port)
