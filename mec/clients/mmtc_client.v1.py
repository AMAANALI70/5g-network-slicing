#!/usr/bin/env python3
"""
mMTC UE Client — Real IoT Sensor Publisher
Publishes realistic multi-sensor telemetry via MQTT to Mosquitto broker.
Simulates: temperature, humidity, GPS, speed, motion, heartbeat sensors.
Binding to uesimtun interface ensures traffic flows through the mMTC 5G slice.
"""
import paho.mqtt.client as mqtt
import socket
import json
import time
import sys
import random
import math
import threading

# Sensor profiles — realistic intervals for different sensor types
SENSOR_PROFILES = [
    {"topic": "sensors/{id}/temperature", "interval": 30, "type": "temp"},
    {"topic": "sensors/{id}/humidity",    "interval": 60, "type": "humidity"},
    {"topic": "vehicles/{id}/gps",        "interval": 5,  "type": "gps"},
    {"topic": "vehicles/{id}/speed",      "interval": 1,  "type": "speed"},
    {"topic": "devices/heartbeat/{id}",   "interval": 10, "type": "heartbeat"},
    {"topic": "alerts/motion/{id}",       "interval": None, "type": "motion"},  # event-driven
]

class SensorDevice:
    def __init__(self, device_id, interface, broker_ip, broker_port=1883):
        self.device_id = device_id
        self.interface = interface
        self.broker_ip = broker_ip
        self.broker_port = broker_port
        self.client = mqtt.Client(client_id=f"ue-{device_id}",
                                  clean_session=True)  # True avoids duplicate-session kick
        self.msg_count = 0
        self.connected = False
        self.t_start = time.time()

        # State for continuous sensors
        self.lat = 12.9716 + random.uniform(-0.1, 0.1)
        self.lon = 77.5946 + random.uniform(-0.1, 0.1)
        self.speed_kmh = random.uniform(0, 60)
        self.temp_base = random.uniform(20, 35)
        self.humidity_base = random.uniform(40, 80)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            print(f"[mMTC] {self.interface} ({self.device_id}): Connected to Mosquitto ✓")
        else:
            print(f"[mMTC] {self.interface} ({self.device_id}): Connection failed rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        print(f"[mMTC] {self.interface} ({self.device_id}): Disconnected (rc={rc})")

    def _on_publish(self, client, userdata, mid):
        self.msg_count += 1

    def _bind_to_interface(self):
        """Patch the MQTT socket to bind to uesimtun interface."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                       self.interface.encode() + b'\x00')
        sock.connect((self.broker_ip, self.broker_port))
        self.client.socket = lambda: sock
        return sock

    def make_temp_payload(self, t):
        temp = self.temp_base + 3 * math.sin(t * 0.001) + random.gauss(0, 0.3)
        return {"value": round(temp, 2), "unit": "celsius",
                "sensor_id": self.device_id, "ts": time.time()}

    def make_humidity_payload(self, t):
        hum = self.humidity_base + 5 * math.sin(t * 0.0005) + random.gauss(0, 1)
        return {"value": round(max(0, min(100, hum)), 1), "unit": "percent",
                "sensor_id": self.device_id, "ts": time.time()}

    def make_gps_payload(self):
        # Simulate vehicle movement along a path
        self.lat += random.gauss(0, 0.0001)
        self.lon += random.gauss(0, 0.0001)
        return {"lat": round(self.lat, 6), "lon": round(self.lon, 6),
                "alt_m": round(920 + random.gauss(0, 2), 1),
                "hdop": round(random.uniform(0.8, 2.5), 2),
                "device_id": self.device_id, "ts": time.time()}

    def make_speed_payload(self):
        self.speed_kmh += random.gauss(0, 2)
        self.speed_kmh = max(0, min(120, self.speed_kmh))
        return {"speed_kmh": round(self.speed_kmh, 1),
                "rpm": int(self.speed_kmh * 40 + random.gauss(0, 50)),
                "device_id": self.device_id, "ts": time.time()}

    def make_heartbeat_payload(self):
        uptime = int(time.time() - self.t_start)
        return {"device_id": self.device_id, "status": "online",
                "uptime_s": uptime, "msgs_sent": self.msg_count,
                "ts": time.time()}

    def run(self):
        """Main sensor loop — connects via 5G uesimtun and publishes at realistic rates."""
        print(f"[mMTC] {self.interface}: Starting sensor device {self.device_id}")

        # Get the UE's own IP on this uesimtun interface
        # Traffic sourced from this IP routes via uesimtun → GTP → UPF → DNAT → Mosquitto
        import subprocess
        result = subprocess.run(
            ['ip', '-4', 'addr', 'show', self.interface],
            capture_output=True, text=True)
        ue_ip = None
        for line in result.stdout.splitlines():
            if 'inet ' in line:
                ue_ip = line.strip().split()[1].split('/')[0]
                break
        if not ue_ip:
            print(f"[mMTC] {self.interface}: Cannot get IP, using unbound connection")

        print(f"[mMTC] {self.interface}: UE IP = {ue_ip}, binding to {self.interface} via SO_BINDTODEVICE")

        # Monkey-patch socket to use SO_BINDTODEVICE — forces traffic via uesimtun (GTP path)
        # This is equivalent to `curl --interface uesimtunX` and ensures symmetric routing
        import socket as _sock_mod
        _orig_socket = _sock_mod.socket
        _iface_bytes = (self.interface + '\x00').encode()

        class _BoundSocket(_orig_socket):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                try:
                    self.setsockopt(_sock_mod.SOL_SOCKET, 25, _iface_bytes)
                except OSError:
                    pass

        while True:
            try:
                _sock_mod.socket = _BoundSocket
                try:
                    self.client.connect(self.broker_ip, self.broker_port,
                                        keepalive=60,
                                        bind_address="")
                finally:
                    _sock_mod.socket = _orig_socket
                self.client.loop_start()

                # Wait for connection
                timeout = 10
                while not self.connected and timeout > 0:
                    time.sleep(0.5)
                    timeout -= 0.5

                if not self.connected:
                    print(f"[mMTC] {self.interface}: Timeout connecting, retrying...")
                    self.client.loop_stop()
                    time.sleep(5)
                    continue

                # Track last publish times for each sensor type
                last_published = {p["type"]: 0 for p in SENSOR_PROFILES}
                t_start = time.monotonic()

                while self.connected:
                    t = time.monotonic() - t_start
                    now = time.time()

                    for profile in SENSOR_PROFILES:
                        if profile["interval"] is None:
                            continue
                        if now - last_published[profile["type"]] >= profile["interval"]:
                            topic = profile["topic"].replace("{id}", self.device_id)
                            ptype = profile["type"]

                            if ptype == "temp":
                                payload = self.make_temp_payload(t)
                            elif ptype == "humidity":
                                payload = self.make_humidity_payload(t)
                            elif ptype == "gps":
                                payload = self.make_gps_payload()
                            elif ptype == "speed":
                                payload = self.make_speed_payload()
                            elif ptype == "heartbeat":
                                payload = self.make_heartbeat_payload()
                            else:
                                continue

                            self.client.publish(topic, json.dumps(payload), qos=1)
                            last_published[ptype] = now

                    # Occasional motion event (random, event-driven)
                    if random.random() < 0.001:  # ~0.1% chance per 100ms tick
                        topic = f"alerts/motion/{self.device_id}"
                        self.client.publish(topic, json.dumps({
                            "zone": f"zone-{random.randint(1,5)}",
                            "confidence": round(random.uniform(0.7, 0.99), 2),
                            "ts": time.time()
                        }), qos=1)

                    # Status every 10 messages (visible quickly)
                    if self.msg_count > 0 and self.msg_count % 10 == 0:
                        print(f"[mMTC] {self.interface} ({self.device_id}): "
                              f"{self.msg_count} msgs published", flush=True)

                    time.sleep(0.1)  # 100ms main loop

            except KeyboardInterrupt:
                print(f"[mMTC] {self.interface}: Stopped. Total: {self.msg_count} msgs")
                self.client.loop_stop()
                self.client.disconnect()
                break
            except Exception as e:
                print(f"[mMTC] {self.interface}: Error: {e}. Retrying in 10s...")
                time.sleep(10)

if __name__ == "__main__":
    iface = sys.argv[1] if len(sys.argv) > 1 else "uesimtun1"
    broker = sys.argv[2] if len(sys.argv) > 2 else "192.168.49.172"
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 1883
    # Use device ID from interface name suffix
    dev_id = f"dev-{iface.replace('uesimtun', 'ue')}"
    sensor = SensorDevice(dev_id, iface, broker, port)
    sensor.run()
