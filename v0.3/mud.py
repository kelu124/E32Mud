from microdot import Microdot, Response
from microdot.websocket import WebSocket
from microdot.websocket import with_websocket
import json
import os
import time
import sys



if 'esp' in sys.platform:
    print("Running on ESP32")
    import os
    PORT = 80
    def isfile(path):
        try:
            return (os.stat(path)[0] & 0x4000) == 0
        except OSError:
            return False
else:
    print("Running classically")
    PORT = 5000
    def isfile(path):
        return os.path.exists(path)

from homepage import html

from mud import *



app = Microdot()
Response.default_content_type = 'text/html'

clients = set()
players = {}


PLAYER_DATA_FILE = 'known_players.json'
try:
    with open(PLAYER_DATA_FILE) as f:
        known_players = json.load(f)
    print(f"Loaded {len(known_players)} known players from {PLAYER_DATA_FILE}")
except:
    known_players = {}

def save_players():
    with open(PLAYER_DATA_FILE, 'w') as f:
        json.dump(known_players, f)



@app.route('/')
def index(request):
    print("Serving index page")
    return html(PORT)

@app.route('/ws', methods=['GET', 'WEBSOCKET'])
@with_websocket
async def websocket_handler(request, ws):
    clients.add(ws)

    players[ws] = {'name': None, 'room': 'hall'}
    try:
        await ws.send("Welcome to the MUD!\nPlease enter your name:")
        while True:
            msg = await ws.receive()
            if msg is None:
                break
            if msg.startswith('__auth '):
                name = msg.split(' ', 1)[1]
                print(known_players, name)
                if name in known_players:
                    players[ws]['name'] = name
                    players[ws]['room'] = known_players[name].get('room', 'hall')
                    await ws.send(f"Welcome back, {name}!")
                    await broadcast(ws, f"{name} has entered the game.")
                    await describe_room(ws)
                else:
                    await ws.send("Name not recognized. Please enter your name:")
            elif players[ws]['name'] is None:
                players[ws]['name'] = msg
                known_players[msg] = {'room': 'hall'}
                save_players()
                await ws.send(f"Hello, {msg}! Type 'look' to see your surroundings.")
                await broadcast(ws, f"{msg} has entered the game.")
                await describe_room(ws)
            else:
                await handle_command(ws, msg)
    except Exception as e:
        print("WebSocket error:", e)
    finally:
        clients.remove(ws)
        name = players[ws]['name']
        if name:
            known_players[name] = {'room': players[ws]['room']}
            save_players()
        del players[ws]
        await ws.close()



rooms = {
    'hall': {
        'description': 'You are in a grand hall with arched ceilings.',
        'exits': {'north': 'library', 'east': 'kitchen'}
    },
    'library': {
        'description': 'Dusty books line the walls of this quiet library.',
        'exits': {'south': 'hall'}
    },
    'kitchen': {
        'description': 'A warm kitchen filled with the smell of bread.',
        'exits': {'west': 'hall'}
    }
}





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
            await broadcast(ws, f"{name} leaves {direction}.")
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
        # os.path.exists -- WebSocket error: 'module' object has no attribute 'path' 
        if isfile(filename): 
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



if __name__ == '__main__':
    import logging
    print("Starting MUD server locally...")
    logging.basicConfig(level=logging.INFO)
else:
    print("Starting MUD server on ESP32...")
app.run(port=PORT)
