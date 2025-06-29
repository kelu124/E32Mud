
async def broadcast(sender_ws, message):
    for client in clients:
        if client != sender_ws:
            try:
                client.send(message)
            except:
                pass

async def describe_room(ws):
    player = players[ws]
    #@ TODO says who is there
    room = rooms[player['room']]
    desc = room['description']
    exits = ", ".join(room['exits'].keys())
    await ws.send(f"\n{desc}\nExits: {exits}\n")

async def handle_command(ws, msg):
    player = players[ws]
    name = player['name']
    tokens = msg.strip().split()
    if not tokens:
        return
    cmd = tokens[0].lower()

    if cmd == 'look':
        await describe_room(ws)

    elif cmd == 'go' and len(tokens) > 1:
        direction = tokens[1].lower()
        current_room = rooms[player['room']]
        if direction in current_room['exits']:
            new_room = current_room['exits'][direction]
            broadcast(ws, f"{name} leaves {direction}.")
            player['room'] = new_room
            known_players[name] = {'room': new_room}
            save_players()
            await ws.send(f"You go {direction}.")
            await broadcast(ws, f"{name} enters from the {opposite_direction(direction)}.")
            await describe_room(ws)
        else:
            await ws.send("You can't go that way.")

    elif cmd == 'say' and len(tokens) > 1:
        message = " ".join(tokens[1:])
        await send_to_room(ws, f"{name} says: {message}")

    elif cmd == 'write' and len(tokens) > 1:
        note = " ".join(tokens[1:])
        room = player['room']
        filename = f"wiki_{room}.txt"
        timestamp = time.time()
        with open(filename, 'a') as f:
            f.write(f"{name} @ {timestamp}: {note}\n")
        await ws.send("Note saved.")

    elif cmd == 'read':
        room = player['room']
        filename = f"wiki_{room}.txt"
        if os.path.exists(filename):
            with open(filename) as f:
                notes = f.read()
            await ws.send(f"Notes in this room:\n{notes}")
        else:
            await ws.send("No notes in this room.")

    elif cmd == 'list':
        files = [f[5:-4] for f in os.listdir() if f.startswith('wiki_') and f.endswith('.txt')]
        if files:
            await ws.send("Rooms with notes: " + ", ".join(files))
        else:
            await ws.send("No rooms have notes yet.")

    else:
        await ws.send("Unknown command.")

async def send_to_room(sender_ws, message):
    sender_room = players[sender_ws]['room']
    for ws in clients:
        if players.get(ws, {}).get('room') == sender_room:
            try:
                await ws.send(message)
            except:
                pass

def opposite_direction(direction):
    opposites = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}
    return opposites.get(direction, '?')
