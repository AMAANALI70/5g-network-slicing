#!/usr/bin/env python3
"""
embb_client.py — 5G eMBB Realistic Video Streaming (Session Model)
===================================================================
Real-world behaviour this models:
  - Netflix/YouTube streams continuously, not in tiny bursts
  - Users watch 20-45 min of content before pausing/switching
  - ABR adjusts quality based on available bandwidth
  - Multiple concurrent UEs create natural aggregate variation

Traffic pattern per UE:
  ACTIVE phase (25-45s): Download segments at full GTP speed back-to-back
  BREAK  phase  (5-15s): Idle (user paused, buffering, content switch)

With 3 UEs and randomised start offsets:
  - 2-3 UEs active simultaneously most of the time → 300-600 Mbps aggregate
  - 0-1 UEs active occasionally → drops to 0-200 Mbps (natural valley)
  - CoV > 40%: clearly bursty but sustained high average ≈ 200-400 Mbps

Why not the buffer model?
  Our nginx is local (10Gbps). A 5 MB segment downloads in 0.2s but represents
  4s of video → 20× real-time. With buffer_target=16s you get 0.8s burst / 12s
  idle = 5% duty cycle → 10 Mbps average. That's why throughput dropped.
  The session model avoids this by basing the active window on wall-clock time,
  not video seconds, matching the real relationship where a viewer watches for
  N real seconds and expects N seconds of video to have been served.
"""
import subprocess, sys, time, random

QUALITIES = ["360p", "720p", "1080p"]

# Session timing (seconds of real wall-clock time)
SESSION_MIN = 25    # Minimum active streaming window per session
SESSION_MAX = 45    # Maximum active streaming window per session
BREAK_MIN   = 5     # Minimum pause between sessions
BREAK_MAX   = 15    # Maximum pause between sessions

# ABR thresholds (segment fetch time vs 4s segment duration)
ABR_DOWNGRADE = 1.5   # Downgrade quality if fetch > 1.5× seg duration
ABR_UPGRADE   = 0.15  # Upgrade if fetch < 15% of seg duration


def fetch_segment(url, interface, timeout=20):
    cmd = ["curl", "--interface", interface, "--max-time", str(timeout),
           "--silent", "--output", "/dev/null", "--write-out", "%{size_download}", url]
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        return r.returncode == 0, time.monotonic() - t0, int(r.stdout.strip() or 0)
    except subprocess.TimeoutExpired:
        return False, timeout, 0
    except Exception as e:
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


def run(interface, server_ip="192.168.49.172", port=30880):
    base    = f"http://{server_ip}:{port}/hls"
    master  = f"{base}/master.m3u8"
    quality = "1080p"

    # Random start offset so UEs don't all burst together at t=0
    offset = random.uniform(0, 12)
    print(f"[eMBB] {interface}: start offset={offset:.1f}s quality={quality}", flush=True)
    time.sleep(offset)

    total_bytes = 0
    total_segs  = 0
    t_start     = time.monotonic()
    segments    = []
    seg_idx     = 0
    session_n   = 0

    while True:
        try:
            # ── Refresh segment list if needed ──────────────────────────────
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

            # ── ACTIVE SESSION ───────────────────────────────────────────────
            session_n += 1
            session_s  = random.uniform(SESSION_MIN, SESSION_MAX)
            t_end      = time.monotonic() + session_s
            session_m  = (time.monotonic() - t_start) / 60

            print(f"[eMBB] {interface}: 🟢 SESSION {session_n} start "
                  f"({session_s:.0f}s)  quality={quality}  "
                  f"total={total_bytes//1024//1024}MB  {session_m:.1f}min", flush=True)

            seg_count = 0
            while time.monotonic() < t_end:
                seg_url = f"{base}/{quality}/{segments[seg_idx % len(segments)]}"
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

                    # ABR quality switch
                    qi = QUALITIES.index(quality)
                    if fetch_s > 4.0 * ABR_DOWNGRADE and qi > 0:
                        quality = QUALITIES[qi - 1]
                        print(f"[eMBB] {interface}: ⬇ ABR → {quality}", flush=True)
                    elif fetch_s < 4.0 * ABR_UPGRADE and qi < len(QUALITIES) - 1:
                        if random.random() < 0.5:
                            quality = QUALITIES[qi + 1]
                            print(f"[eMBB] {interface}: ⬆ ABR → {quality}", flush=True)

                    # Refresh segment list when exhausted mid-session
                    if seg_idx >= len(segments):
                        segments = get_segments(base, quality, interface) or segments
                        seg_idx  = 0

                else:
                    print(f"[eMBB] {interface}: ✗ Segment failed — retry 2s", flush=True)
                    time.sleep(2)

            # ── BREAK ────────────────────────────────────────────────────────
            break_s   = random.uniform(BREAK_MIN, BREAK_MAX)
            session_m = (time.monotonic() - t_start) / 60
            print(f"[eMBB] {interface}: 🔴 BREAK {break_s:.0f}s  "
                  f"(session had {seg_count} segs)  {session_m:.1f}min", flush=True)
            time.sleep(break_s)

        except KeyboardInterrupt:
            print(f"[eMBB] {interface}: Stopped  "
                  f"{total_segs} segs  {total_bytes//1024//1024}MB", flush=True)
            break
        except Exception as e:
            print(f"[eMBB] {interface}: Error: {e}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    iface  = sys.argv[1] if len(sys.argv) > 1 else "uesimtun1"
    server = sys.argv[2] if len(sys.argv) > 2 else "192.168.49.172"
    port   = int(sys.argv[3]) if len(sys.argv) > 3 else 30880
    run(iface, server, port)
