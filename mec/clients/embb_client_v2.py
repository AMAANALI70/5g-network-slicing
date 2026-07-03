#!/usr/bin/env python3
"""
embb_client.py v2 — 5G eMBB Video Streaming with Load-Level Profiles
======================================================================
Load differentiation is achieved via per-quality session/break timing:

  360p  (LOW  load): session 15–25s, break 20–40s  → ~37% duty cycle
  720p  (MED  load): session 30–40s, break  8–15s  → ~72% duty cycle
  1080p (HIGH load): session 40–50s, break  3– 8s  → ~86% duty cycle

Segment sizes (verified on nginx):
  360p: ~676 KB/seg   720p: ~2.33 MB/seg   1080p: ~4.72 MB/seg

With 4 UEs sharing a 1000-Mbit tc pipe, expected aggregate offered load:
  LOW  ~370 Mbps avg   MEDIUM ~720 Mbps avg   HIGH ~860 Mbps avg
"""
import subprocess, sys, time, random

QUALITIES = ["360p", "720p", "1080p"]

# Per-quality session / break timing (seconds)
QUALITY_PROFILES = {
    "360p":  {"session_min": 15, "session_max": 25,
              "break_min":   20, "break_max":   40},
    "720p":  {"session_min": 30, "session_max": 40,
              "break_min":    8, "break_max":   15},
    "1080p": {"session_min": 40, "session_max": 50,
              "break_min":    3, "break_max":    8},
}

ABR_DOWNGRADE = 1.5
ABR_UPGRADE   = 0.15


def fetch_segment(url, interface, timeout=20):
    cmd = ["curl", "--interface", interface, "--max-time", str(timeout),
           "--silent", "--output", "/dev/null", "--write-out", "%{size_download}", url]
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        return r.returncode == 0, time.monotonic() - t0, int(r.stdout.strip() or 0)
    except subprocess.TimeoutExpired:
        return False, timeout, 0
    except Exception:
        return False, 0, 0


def get_segments(base_url, quality, interface):
    url = f"{base_url}/{quality}/index.m3u8"
    out = f"/tmp/hls_{interface}_{quality}.m3u8"
    subprocess.run(["curl", "--interface", interface, "--max-time", "8",
                    "--silent", "--output", out, url],
                   capture_output=True, timeout=10)
    try:
        with open(out) as f:
            return [l.strip() for l in f if l.strip() and not l.startswith('#') and '.ts' in l]
    except Exception:
        return []


def run(interface, server_ip="192.168.49.172", port=30880, initial_quality="1080p"):
    base    = f"http://{server_ip}:{port}/hls"
    master  = f"{base}/master.m3u8"

    # Validate quality, fall back to 1080p
    if initial_quality not in QUALITY_PROFILES:
        print(f"[eMBB] {interface}: unknown quality '{initial_quality}', using 1080p", flush=True)
        initial_quality = "1080p"

    profile = QUALITY_PROFILES[initial_quality]
    quality = initial_quality

    offset = random.uniform(0, 12)
    print(f"[eMBB] {interface}: start offset={offset:.1f}s quality={quality} "
          f"profile=session{profile['session_min']}-{profile['session_max']}s "
          f"break{profile['break_min']}-{profile['break_max']}s", flush=True)
    time.sleep(offset)

    total_bytes = 0
    total_segs  = 0
    t_start     = time.monotonic()
    segments    = []
    seg_idx     = 0
    session_n   = 0

    while True:
        try:
            if not segments or seg_idx >= len(segments):
                segments = get_segments(base, quality, interface)
                seg_idx  = 0
                if not segments:
                    ok, _, _ = fetch_segment(master, interface, timeout=6)
                    if not ok:
                        print(f"[eMBB] {interface}: ✗ GTP unreachable — retry 15s", flush=True)
                        time.sleep(15)
                    else:
                        time.sleep(3)
                    continue

            # ── ACTIVE SESSION ──────────────────────────────────────────────
            session_n += 1
            session_s  = random.uniform(profile['session_min'], profile['session_max'])
            t_end      = time.monotonic() + session_s
            session_m  = (time.monotonic() - t_start) / 60

            print(f"[eMBB] {interface}: 🟢 SESSION {session_n} start "
                  f"({session_s:.0f}s) quality={quality} "
                  f"total={total_bytes//1024//1024}MB {session_m:.1f}min", flush=True)

            seg_count = 0
            while time.monotonic() < t_end:
                seg_url  = f"{base}/{quality}/{segments[seg_idx % len(segments)]}"
                seg_idx += 1

                ok, fetch_s, size_b = fetch_segment(seg_url, interface, timeout=20)

                if ok and size_b > 0:
                    total_bytes += size_b
                    total_segs  += 1
                    seg_count   += 1
                    rate_mbps    = size_b * 8 / (fetch_s * 1e6) if fetch_s > 0 else 0
                    session_m    = (time.monotonic() - t_start) / 60

                    print(f"[eMBB] {interface}: [{quality}] seg {total_segs} "
                          f"size={size_b//1024}KB fetch={fetch_s:.2f}s "
                          f"rate={rate_mbps:.1f}Mbps "
                          f"total={total_bytes//1024//1024}MB "
                          f"{session_m:.1f}min", flush=True)

                    qi = QUALITIES.index(quality)
                    if fetch_s > 4.0 * ABR_DOWNGRADE and qi > 0:
                        quality = QUALITIES[qi - 1]
                        print(f"[eMBB] {interface}: ⬇ ABR → {quality}", flush=True)
                    elif fetch_s < 4.0 * ABR_UPGRADE and qi < len(QUALITIES) - 1:
                        if random.random() < 0.5:
                            quality = QUALITIES[qi + 1]
                            print(f"[eMBB] {interface}: ⬆ ABR → {quality}", flush=True)

                    if seg_idx >= len(segments):
                        segments = get_segments(base, quality, interface) or segments
                        seg_idx  = 0
                else:
                    print(f"[eMBB] {interface}: ✗ Segment failed — retry 2s", flush=True)
                    time.sleep(2)

            # ── BREAK ────────────────────────────────────────────────────────
            break_s   = random.uniform(profile['break_min'], profile['break_max'])
            session_m = (time.monotonic() - t_start) / 60
            print(f"[eMBB] {interface}: 🔴 BREAK {break_s:.0f}s "
                  f"(session had {seg_count} segs) {session_m:.1f}min", flush=True)
            time.sleep(break_s)

        except KeyboardInterrupt:
            print(f"[eMBB] {interface}: Stopped "
                  f"{total_segs} segs {total_bytes//1024//1024}MB", flush=True)
            break
        except Exception as e:
            print(f"[eMBB] {interface}: Error: {e}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    iface   = sys.argv[1] if len(sys.argv) > 1 else "uesimtun1"
    server  = sys.argv[2] if len(sys.argv) > 2 else "192.168.49.172"
    port    = int(sys.argv[3]) if len(sys.argv) > 3 else 30880
    quality = sys.argv[4] if len(sys.argv) > 4 else "1080p"
    run(iface, server, port, initial_quality=quality)
