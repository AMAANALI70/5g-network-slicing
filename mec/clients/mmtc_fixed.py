#!/usr/bin/env python3
"""
mmtc_fixed.py — Reliable mMTC MQTT client
Binds to specific uesimtun interface IP, publishes every 2s.
Usage: python3 mmtc_fixed.py <interface> <broker_ip> <broker_port>
"""
import sys, time, random, socket, subprocess, re
import paho.mqtt.client as mqtt

IF   = sys.argv[1]
HOST = sys.argv[2]
PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 30883

# Get IP of the specified interface
def get_iface_ip(iface):
    try:
        out = subprocess.check_output(f"ip -4 addr show {iface}", shell=True, text=True)
        m = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', out)
        return m.group(1) if m else None
    except Exception:
        return None

bind_ip = get_iface_ip(IF)
if not bind_ip:
    print(f"[mMTC] ERROR: Cannot get IP for {IF}", flush=True)
    sys.exit(1)

print(f"[mMTC] {IF}: bind_ip={bind_ip} broker={HOST}:{PORT}", flush=True)

msg_count = 0
connected  = False

def on_connect(client, userdata, flags, rc):
    global connected
    if rc == 0:
        connected = True
        print(f"[mMTC] {IF}: Connected to Mosquitto ✓", flush=True)
    else:
        print(f"[mMTC] {IF}: Connect failed rc={rc}", flush=True)

def on_disconnect(client, userdata, rc):
    global connected
    connected = False
    print(f"[mMTC] {IF}: Disconnected rc={rc}", flush=True)

def on_publish(client, userdata, mid):
    pass  # silent publish confirmation

client = mqtt.Client(client_id=f"mmtc-{IF}-{random.randint(1000,9999)}")
client.on_connect    = on_connect
client.on_disconnect = on_disconnect
client.on_publish    = on_publish

# Bind to specific interface IP so traffic goes through GTP tunnel
try:
    client.connect(HOST, PORT, keepalive=120, bind_address=bind_ip)
except Exception as e:
    print(f"[mMTC] {IF}: Initial connect error: {e}", flush=True)

client.loop_start()

while True:
    if connected:
        msg_count += 1
        payload = (f'{{"ue":"{IF}","seq":{msg_count},'
                   f'"temp":{random.uniform(20,35):.1f},'
                   f'"humidity":{random.uniform(40,80):.1f},'
                   f'"ts":{int(time.time())}}}')
        result = client.publish(f"sensor/{IF}", payload, qos=0)
        print(f"[mMTC] {IF}: msg#{msg_count} published rc={result.rc}", flush=True)
    else:
        # Try reconnect
        try:
            client.reconnect()
        except Exception:
            time.sleep(2)
            try:
                client.connect(HOST, PORT, keepalive=120, bind_address=bind_ip)
            except Exception as e:
                print(f"[mMTC] {IF}: Reconnect failed: {e}", flush=True)
    time.sleep(2)
