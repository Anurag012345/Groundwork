"""Forward the WSL gateway address to the Windows-only Ollama, so containers in WSL can use it.

Ollama listens on 127.0.0.1 only, which WSL cannot reach. This binds just the private
Windows<->WSL adapter (not 0.0.0.0), so nothing off this machine can connect.
Usage: python evals/wsl_relay.py <gateway-ip> [port=11434]   (find the IP: wsl ip route show default)
"""

import asyncio
import sys


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


async def handle(client_reader, client_writer, port):
    upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", port)
    await asyncio.gather(
        pipe(client_reader, upstream_writer), pipe(upstream_reader, client_writer),
        return_exceptions=True,
    )


async def main(host, port):
    server = await asyncio.start_server(lambda r, w: handle(r, w, port), host, port)
    print(f"relaying {host}:{port} -> 127.0.0.1:{port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 11434))
