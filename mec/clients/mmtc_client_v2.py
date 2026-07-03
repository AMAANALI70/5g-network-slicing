#!/usr/bin/env python3
"""
mmtc_client.py v2 — IoT Sensor Publisher with configurable rate multiplier.

Rate differentiation per load level:
  Low  : rate_mult=1.0  (baseline sensor intervals: GPS 5s, speed 1s, heartbeat 10s)
  Med  : rate_mult=2.0  (2× faster: GPS 2.5s, speed 0.5s, heartbeat 5s)
  High : rate_mult=4.0  (4× faster: GPS 1.25s, speed 0.25s, heartbeat 2.5s)

With 4 UEs: total mMTC message rate = sum(1/interval_i) × rate_mult × 4
"""
import paho.mqtt.client as mqtt
import socket, json, time, sys, random, math, threading

SENSOR_PROFILES = [
    {"topic": "sensors/{id}/temperature", "interval": 30,   "type": "temp"},
    {"topic": "sensors/{id}/humidity",    "interval": 60,   "type": "humidity"},
    {"topic": "vehicles/{id}/gps",        "interval": 5,    "type": "gps"},
    {"topic": "vehicles/{id}/speed",      "interval": 1,    "type": "speed"},
    {"topic": "devices/heartbeat/{id}",   "interval": 10,   "type": "heartbeat"},
]


class SensorDevice:
    def __init__(self, device_id, interface, broker_ip, broker_port=1883, rate_mult=1.0):
        self.device_id  = device_id
        self.interface  = interface
        self.broker_ip  = broker_ip
        self.broker_port = broker_port
        self.rate_mult  = max(0.1, rate_mult)
        self.client     = mqtt.Client(client_id=f"ue-{device_id}", clean_session=True)
        self.msg_count  = 0
        self.connected  = False
        self.t_start    = time.time()

        self.lat        = 12.9716 + random.uniform(-0.1, 0.1)
        self.lon        = 77.5946 + random.uniform(-0.1, 0.1)
        self.speed_kmh  = random.uniform(0, 60)
        self.temp_base  = random.uniform(20, 35)
        self.humidity_base = random.uniform(40, 80)

        self.client.on_connect    = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish    = self._on_publish

    def _on_connect(self, client, userdata, flags, rc):
        self.connected = (rc == 0)
        status = "✓" if rc == 0 else f"failed rc={rc}"
        print(f"[mMTC] {self.interface} ({self.device_id}): Connected {status}", flush=True)

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        print(f"[mMTC] {self.interface} ({self.device_id}): Disconnected (rc={rc})", flush=True)

    def _on_publish(self, client, userdata, mid):
        self.msg_count += 1

    def _make_payload(self, profile_type):
        t = time.time() - self.t_start
        if profile_type == "temp":
            return {"value": round(self.temp_base + 3*math.sin(t*0.001) + random.gauss(0,0.3), 2),
                    "unit": "celsius", "sensor_id": self.device_id, "ts": time.time()}
        elif profile_type == "humidity":
            return {"value": round(max(0, min(100, self.humidity_base + 5*math.sin(t*0.0005) + random.gauss(0,1))), 1),
                    "unit": "percent", "sensor_id": self.device_id, "ts": time.time()}
        elif profile_type == "gps":
            self.lat += random.gauss(0, 0.0001)
            self.lon += random.gauss(0, 0.0001)
            return {"lat": round(self.lat,6), "lon": round(self.lon,6),
                    "device_id": self.device_id, "ts": time.time()}
        elif profile_type == "speed":
            self.speed_kmh = max(0, min(120, self.speed_kmh + random.gauss(0,2)))
            return {"speed_kmh": round(self.speed_kmh,1), "device_id": self.device_id, "ts": time.time()}
        else:  # heartbeat
            return {"device_id": self.device_id, "status": "online",
                    "uptime_s": int(time.time()-self.t_start), "msgs_sent": self.msg_count,
                    "ts": time.time()}

    def run(self):
        print(f"[mMTC] {self.interface}: Starting device={self.device_id} "
              f"rate_mult={self.rate_mult}x", flush=True)

        import subprocess as _sp
        result = _sp.run(['ip','-4','addr','show',self.interface], capture_output=True, text=True)
        ue_ip = None
        for line in result.stdout.splitlines():
            if 'inet ' in line:
                ue_ip = line.strip().split()[1].split('/')[0]
                break

        import socket as _sock
        _orig = _sock.socket
        _iface_bytes = (self.interface + '\x00').encode()

        def _patched_socket(*args, **kwargs):
            s = _orig(*args, **kwargs)
            try:
                s.setsockopt(_sock.SOL_SOCKET, _sock.SO_BINDTODEVICE, _iface_bytes)
            except Exception:
                pass
            return s

        _sock.socket = _patched_socket
        try:
            self.client.connect(self.broker_ip, self.broker_port, keepalive=60)
        finally:
            _sock.socket = _orig

        self.client.loop_start()
        time.sleep(2)

        # Per-sensor publish threads
        def _publish_loop(profile):
            interval = profile["interval"] / self.rate_mult   # shorter = faster
            topic    = profile["topic"].format(id=self.device_id)
            while True:
                try:
                    if self.connected:
                        payload = self._make_payload(profile["type"])
                        self.client.publish(topic, json.dumps(payload), qos=0)
                    time.sleep(interval)
                except Exception:
                    time.sleep(1)

        threads = [threading.Thread(target=_publish_loop, args=(p,), daemon=True)
                   for p in SENSOR_PROFILES]
        for th in threads:
            th.start()

        try:
            while True:
                time.sleep(30)
                print(f"[mMTC] {self.interface}: msgs={self.msg_count} "
                      f"connected={self.connected} rate_mult={self.rate_mult}x", flush=True)
        except KeyboardInterrupt:
            print(f"[mMTC] {self.interface}: Stopped. msgs={self.msg_count}", flush=True)
            self.client.loop_stop()
            self.client.disconnect()


if __name__ == "__main__":
    iface     = sys.argv[1] if len(sys.argv) > 1 else "uesimtun2"
    broker_ip = sys.argv[2] if len(sys.argv) > 2 else "192.168.49.172"
    broker_port = int(sys.argv[3]) if len(sys.argv) > 3 else 1883
    rate_mult = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    dev_id    = f"sensor-{iface.replace('uesimtun','ue')}"
    device    = SensorDevice(dev_id, iface, broker_ip, broker_port, rate_mult)
    device.run()
