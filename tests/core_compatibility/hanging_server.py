#!/usr/bin/env python3
"""Accept controller connections without ever returning an HTTP response."""

import socket
import time


with socket.socket() as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen()
    print(server.getsockname()[1], flush=True)
    while True:
        connection, _ = server.accept()
        with connection:
            connection.recv(4096)
            time.sleep(3600)
