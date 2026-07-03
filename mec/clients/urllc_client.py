#!/usr/bin/env python3
"""
urllc_client.py v2 — Industrial HTTP Telemetry with configurable request rate.

Rate differentiation per load level:
  Low  : 1.0 Hz  (1 req/s  per UE) — baseline industrial polling
  Med  : 2.0 Hz  (2 req/s  per UE) — elevated sensing frequency
  High : 4.0 Hz  (4 req/s  per UE) — high-frequency control loop

With 4 UEs: total URLLC load = rate_hz × 4 requests/s
"""
import subprocess, json, time, sys, random, math


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
    t0 = time.monotonic_ns()
    cmd = [
        "curl", "--interface", interface,
        "--max-time", str(timeout), "--silent",
        "-X", "POST", "-H", "Content-Type: application/json",
        "-d", body, "--write-out", "\n%{http_code}", url
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 1)
        rtt_ms = (time.monotonic_ns() - t0) / 1_000_000
        lines  = result.stdout.strip().rsplit('\n', 1)
        body_r = lines[0] if len(lines) > 1 else ""
        code   = lines[-1] if lines else "0"
        return result.returncode == 0 and code == "200", rtt_ms, body_r
    except Exception as e:
        return False, (time.monotonic_ns() - t0) / 1_000_000, str(e)


def run_telemetry(interface, server_ip="192.168.49.172", port=30180, rate_hz=1.0):
    machine_id  = f"cnc-{interface.replace('uesimtun', 'ue')}"
    url         = f"http://{server_ip}:{port}/api/telemetry"
    interval_s  = 1.0 / max(rate_hz, 0.1)   # seconds between requests
    rtt_history = []
    msg_count   = 0
    fail_count  = 0
    t_start     = time.monotonic()

    print(f"[URLLC] {interface}: Starting → {url} as {machine_id} "
          f"rate={rate_hz}Hz interval={interval_s:.3f}s", flush=True)

    while True:
        try:
            t       = time.monotonic() - t_start
            payload = get_machine_telemetry(machine_id, t)
            body    = json.dumps(payload)

            ok, rtt_ms, response = curl_post(interface, url, body)

            if ok:
                msg_count  += 1
                rtt_history.append(rtt_ms)
                if len(rtt_history) > 5:
                    rtt_history.pop(0)

                cmd = "?"
                try:
                    r   = json.loads(response)
                    cmd = r.get("control_cmd", "?")
                except Exception:
                    pass

                avg = sum(rtt_history) / len(rtt_history)
                mx  = max(rtt_history)
                sla = "⚠️ SLA VIOLATION" if avg > 25 else "✓"

                if avg > 25 or msg_count % max(1, int(5 * rate_hz)) == 0:
                    print(f"[URLLC] {interface}: msgs={msg_count} fails={fail_count} "
                          f"RTT avg={avg:.1f}ms max={mx:.1f}ms {sla}", flush=True)
            else:
                fail_count += 1
                if fail_count % 5 == 1:
                    print(f"[URLLC] {interface}: POST failed (total fails={fail_count})")

            elapsed = time.monotonic() - t_start - t
            time.sleep(max(0, interval_s - elapsed))

        except KeyboardInterrupt:
            print(f"[URLLC] {interface}: Stopped. msgs={msg_count} fails={fail_count}")
            break


if __name__ == "__main__":
    iface   = sys.argv[1] if len(sys.argv) > 1 else "uesimtun1"
    server  = sys.argv[2] if len(sys.argv) > 2 else "192.168.49.172"
    port    = int(sys.argv[3]) if len(sys.argv) > 3 else 30180
    rate_hz = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    run_telemetry(iface, server, port, rate_hz=rate_hz)
