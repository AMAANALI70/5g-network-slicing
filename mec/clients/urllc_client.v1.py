#!/usr/bin/env python3
"""
URLLC UE Client — Industrial HTTP Telemetry via curl subprocess
Uses curl --interface (same as eMBB) to guarantee correct routing through
the 5G slice: uesimtun → GTP-U → UPF DNAT (ogstun-urllc:1880) → Node-RED.

Sends CNC machine telemetry via HTTP POST to Node-RED at /telemetry.
Measures real RTT per request. SLA target: < 20ms. Violations emerge naturally.
Rate: 1 req/sec per UE (realistic for industrial HTTP polling control loop).
"""
import subprocess
import json
import time
import sys
import random
import math

def get_machine_telemetry(machine_id, t):
    spindle_rpm = 3000 + 30 * math.sin(t * 0.1) + random.gauss(0, 5)
    vib_x  = random.gauss(0.02, 0.003) + (0.1 if random.random() < 0.02 else 0)
    vib_y  = random.gauss(0.018, 0.002)
    temp   = 28.5 + 2.0 * math.sin(t * 0.005) + random.gauss(0, 0.1)
    torque = 45.0 + 5.0 * math.sin(t * 0.3) + random.gauss(0, 1.0)
    return {
        "machine_id":   machine_id,
        "spindle_rpm":  round(spindle_rpm, 1),
        "vibration_x":  round(vib_x, 5),
        "vibration_y":  round(vib_y, 5),
        "temp_c":       round(temp, 2),
        "torque_nm":    round(torque, 2),
        "timestamp_ns": time.monotonic_ns()
    }

def curl_post(interface, url, body, timeout=5):
    """POST JSON via curl --interface. Returns (success, rtt_ms, response_text)."""
    t0 = time.monotonic_ns()
    cmd = [
        "curl", "--interface", interface,
        "--max-time", str(timeout),
        "--silent",
        "-X", "POST",
        "-H", "Content-Type: application/json",
        "-d", body,
        "--write-out", "\n%{http_code}",
        url
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 1)
        rtt_ms = (time.monotonic_ns() - t0) / 1_000_000
        lines  = result.stdout.strip().rsplit('\n', 1)
        body   = lines[0] if len(lines) > 1 else ""
        code   = lines[-1] if lines else "0"
        return result.returncode == 0 and code == "200", rtt_ms, body
    except Exception as e:
        return False, (time.monotonic_ns() - t0) / 1_000_000, str(e)

def run_telemetry(interface, server_ip="192.168.49.172", port=30180):
    machine_id  = f"cnc-{interface.replace('uesimtun', 'ue')}"
    url         = f"http://{server_ip}:{port}/api/telemetry"
    rtt_history = []
    msg_count   = 0
    fail_count  = 0
    t_start     = time.monotonic()

    print(f"[URLLC] {interface}: Starting → {url} as {machine_id}")

    while True:
        try:
            t       = time.monotonic() - t_start
            payload = get_machine_telemetry(machine_id, t)
            body    = json.dumps(payload)

            ok, rtt_ms, response = curl_post(interface, url, body)

            if ok:
                msg_count  += 1
                rtt_history.append(rtt_ms)
                if len(rtt_history) > 5:      # 5-sample window = responsive to bursts
                    rtt_history.pop(0)

                # Parse control command from response
                cmd = "?"
                try:
                    r   = json.loads(response)
                    cmd = r.get("control_cmd", "?")
                except Exception:
                    pass

                avg = sum(rtt_history) / len(rtt_history)
                mx  = max(rtt_history)
                sla = "⚠️ SLA VIOLATION" if avg > 25 else "✓"

                # Always print on SLA breach; otherwise every 5 msgs
                if avg > 25 or msg_count % 5 == 0:
                    print(f"[URLLC] {interface}: msgs={msg_count} fails={fail_count} "
                          f"RTT avg={avg:.1f}ms max={mx:.1f}ms {sla}", flush=True)
            else:
                fail_count += 1
                if fail_count % 5 == 1:
                    print(f"[URLLC] {interface}: POST failed (total fails={fail_count})"
                          f" response={response[:60]}")

            # 1 Hz — sleep remainder of 1 second
            elapsed = time.monotonic() - t_start - t
            sleep_t = max(0, 1.0 - elapsed)
            time.sleep(sleep_t)

        except KeyboardInterrupt:
            print(f"[URLLC] {interface}: Stopped. msgs={msg_count} fails={fail_count}")
            break
        except Exception as e:
            print(f"[URLLC] {interface}: Unexpected error: {e}")
            time.sleep(2)

if __name__ == "__main__":
    iface  = sys.argv[1] if len(sys.argv) > 1 else "uesimtun1"
    server = sys.argv[2] if len(sys.argv) > 2 else "192.168.49.172"
    port   = int(sys.argv[3]) if len(sys.argv) > 3 else 30180
    run_telemetry(iface, server, port)
