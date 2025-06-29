import socket

def start_dns_server(ip="192.168.4.1"):
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp.bind(('', 53))

    print("DNS server started...")

    while True:
        try:
            data, addr = udp.recvfrom(512)
            if data:
                udp.sendto(data[:2] + b'\x81\x80' + data[4:6]*2 + b'\x00\x00\x00\x00' + data[12:] + b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x1e\x00\x04' + bytes(map(int, ip.split('.'))), addr)
                print("Message received from ",addr,":",data)
        except Exception as e:
            print("DNS error:", e)