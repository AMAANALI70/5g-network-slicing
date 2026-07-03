import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", 9000))

print("mMTC UDP Collector Running...")

while True:
    data, addr = sock.recvfrom(1024)
    print("Received:", data.decode())
