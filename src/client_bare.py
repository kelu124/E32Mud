import asyncio
import sys
import websockets

message_log = []  # Store all received messages

async def on_message(ws, message):
    # Store the message
    message_log.append(message)

    # Print it for visibility
    print(message)

    # Example automation: react to room description
    if "keyword" in message.lower():
        await ws.send("say I found the keyword!")

async def mud_client(ip, port, name=None):
    uri = f"ws://{ip}:{port}/ws"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as ws:
            print("Connected.")
            if name:
                await ws.send(f"__auth {name}")
            else:
                name = input("Enter your name: ")
                await ws.send(name)

            async def receive():
                try:
                    async for msg in ws:
                        await on_message(ws, msg)
                except websockets.ConnectionClosed:
                    print("Connection closed.")

            async def send():
                while True:
                    try:
                        command = await asyncio.get_event_loop().run_in_executor(None, input, "> ")
                        await ws.send(command)
                    except (EOFError, KeyboardInterrupt):
                        break

            await asyncio.gather(receive(), send())

    except Exception as e:
        print(f"Could not connect to server: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python mud_client.py <ip> <port> [player_name]")
        sys.exit(1)

    ip = sys.argv[1]
    port = int(sys.argv[2])
    name = sys.argv[3] if len(sys.argv) > 3 else None

    asyncio.run(mud_client(ip, port, name))
