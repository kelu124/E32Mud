from microdot import Microdot, Response
from microdot.websocket import WebSocket
from microdot.websocket import with_websocket
import json
import os
import time
import sys
import hashlib
import binascii


if 'esp' in sys.platform:
    print("Running on ESP32")
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


app = Microdot()
Response.default_content_type = 'text/html'

clients = set()
players = {}

PLAYER_DATA_FILE = 'known_players.json'
ROOMS_DATA_FILE = 'rooms.json'
START_ROOM = 'hall'

# Usernames with admin privileges. Admins can teleport, list rooms/notes,
# and delete directions. Add your player name(s) here.
ADMINS = {'luc', 'kelu', 'alice'}

def is_admin(name):
    return name in ADMINS

# All persisted user data lives in this folder, next to the .py files.
STORE_DIR = 'usr_store'

def ensure_store():
    try:
        os.mkdir(STORE_DIR)
        print(f"Created store directory '{STORE_DIR}'")
    except OSError:
        # Already exists (both CPython and MicroPython raise OSError)
        pass

ensure_store()

def store_path(filename):
    return STORE_DIR + '/' + filename

# Command verbs. Reserved so they can't be used as room titles or direction
# names (otherwise the "bare direction" shortcut below would be ambiguous).
RESERVED_WORDS = {
    'look', 'go', 'teleport', 'say', 'describe',
    'create', 'delete', 'write', 'read', 'list', 'help',
}


# ---------- Password helpers ----------

def _gen_salt():
    try:
        return binascii.hexlify(os.urandom(8)).decode()
    except Exception:
        # Poor fallback if os.urandom is unavailable
        return binascii.hexlify(str(time.time()).encode()).decode()[:16]

def _hash_pw(password, salt):
    h = hashlib.sha256((salt + password).encode())
    return binascii.hexlify(h.digest()).decode()

def set_password(record, password):
    salt = _gen_salt()
    record['salt'] = salt
    record['pw_hash'] = _hash_pw(password, salt)

def check_password(record, password):
    salt = record.get('salt')
    pw_hash = record.get('pw_hash')
    if not salt or not pw_hash:
        return False
    return _hash_pw(password, salt) == pw_hash


# ---------- Player persistence ----------

try:
    with open(store_path(PLAYER_DATA_FILE)) as f:
        known_players = json.load(f)
    print("Loaded", len(known_players), "known players")
except:
    known_players = {}

def save_players():
    with open(store_path(PLAYER_DATA_FILE), 'w') as f:
        json.dump(known_players, f, indent=2)


# ---------- Rooms persistence ----------

DEFAULT_ROOMS = {
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

def save_rooms():
    with open(store_path(ROOMS_DATA_FILE), 'w') as f:
        json.dump(rooms, f, indent=2)

try:
    with open(store_path(ROOMS_DATA_FILE)) as f:
        rooms = json.load(f)
    print("Loaded", len(rooms), "rooms")
except:
    rooms = dict(DEFAULT_ROOMS)
    save_rooms()
    print("Seeded default rooms")


def find_room_key(title):
    """Case-insensitive title lookup. Returns the actual stored key, or None."""
    if not title:
        return None
    t = title.strip().lower()
    for key in rooms:
        if key.lower() == t:
            return key
    return None

def safe_room_filename(key):
    return store_path("wiki_" + "".join(c if (c.isalnum() or c == '_') else '_' for c in key) + ".txt")


# ---------- Routes ----------

@app.route('/')
def index(request):
    print("Serving index page")
    return html(PORT)

@app.route('/ws', methods=['GET', 'WEBSOCKET'])
@with_websocket
async def websocket_handler(request, ws):
    clients.add(ws)
    spawn = START_ROOM if START_ROOM in rooms else next(iter(rooms))
    players[ws] = {
        'name': None,
        'room': spawn,
        'auth_state': 'await_name',
        'pending_name': None,
    }
    try:
        await ws.send("Welcome to the MUD!\nPlease enter your name:")
        while True:
            msg = await ws.receive()
            if msg is None:
                break
            p = players[ws]
            state = p['auth_state']

            if state == 'await_name':
                if msg.startswith('__auth '):
                    name = msg.split(' ', 1)[1].strip()
                else:
                    name = msg.strip()
                if not name:
                    await ws.send("Name cannot be empty. Please enter your name:")
                    continue
                if name in known_players:
                    rec = known_players[name]
                    p['pending_name'] = name
                    if 'pw_hash' not in rec:
                        # Legacy account: prompt to set a password now
                        p['auth_state'] = 'await_new_password'
                        await ws.send(f"Welcome back, {name}. Please set a password for your account:")
                    else:
                        p['auth_state'] = 'await_login_password'
                        await ws.send(f"Welcome back, {name}. Please enter your password:")
                else:
                    p['pending_name'] = name
                    p['auth_state'] = 'await_new_password'
                    await ws.send(f"Hello, {name}. Please choose a password:")

            elif state == 'await_login_password':
                name = p['pending_name']
                rec = known_players.get(name, {})
                if check_password(rec, msg):
                    p['name'] = name
                    room_key = rec.get('room', spawn)
                    if room_key not in rooms:
                        room_key = spawn
                    p['room'] = room_key
                    p['auth_state'] = 'authenticated'
                    p['pending_name'] = None
                    await ws.send(f"Welcome back, {name}!")
                    await broadcast(ws, f"{name} has entered the game.")
                    await describe_room(ws)
                else:
                    await ws.send("Wrong password. Please enter your name:")
                    p['auth_state'] = 'await_name'
                    p['pending_name'] = None

            elif state == 'await_new_password':
                password = msg
                if not password:
                    await ws.send("Password cannot be empty. Please choose a password:")
                    continue
                name = p['pending_name']
                rec = known_players.get(name, {'room': spawn})
                set_password(rec, password)
                if 'room' not in rec or rec['room'] not in rooms:
                    rec['room'] = spawn
                known_players[name] = rec
                save_players()
                p['name'] = name
                p['room'] = rec['room']
                p['auth_state'] = 'authenticated'
                p['pending_name'] = None
                await ws.send(f"Password set. Welcome, {name}! Type 'look' to see your surroundings, or 'help' for commands.")
                await broadcast(ws, f"{name} has entered the game.")
                await describe_room(ws)

            else:  # authenticated
                await handle_command(ws, msg)

    except Exception as e:
        print("WebSocket error:", e)
    finally:
        clients.discard(ws)
        p = players.get(ws, {})
        name = p.get('name')
        if name and name in known_players:
            known_players[name]['room'] = p.get('room', spawn)
            save_players()
        players.pop(ws, None)
        try:
            await ws.close()
        except:
            pass


# ---------- Messaging helpers ----------

async def broadcast(sender_ws, message):
    for client in list(clients):
        if client != sender_ws:
            try:
                await client.send(message)
            except:
                pass

async def send_to_room(sender_ws, message, include_sender=True):
    sender_room = players[sender_ws]['room']
    for ws in list(clients):
        if players.get(ws, {}).get('room') == sender_room:
            if not include_sender and ws == sender_ws:
                continue
            try:
                await ws.send(message)
            except:
                pass

async def describe_room(ws):
    player = players[ws]
    key = player['room']
    room = rooms.get(key)
    if not room:
        await ws.send("You are lost in the void.")
        return
    desc = room.get('description', '(no description)')
    exits = room.get('exits', {})
    exits_txt = ", ".join(exits.keys()) if exits else "none"
    others = [players[c]['name'] for c in clients
              if c != ws
              and players.get(c, {}).get('room') == key
              and players.get(c, {}).get('name')]
    here = ("\nAlso here: " + ", ".join(others)) if others else ""
    await ws.send(f"\n[{key}]\n{desc}\nExits: {exits_txt}{here}\n")

def opposite_direction(direction):
    return {'north': 'south', 'south': 'north',
            'east': 'west', 'west': 'east',
            'up': 'down', 'down': 'up'}.get(direction, '?')

async def do_move(ws, direction):
    player = players[ws]
    name = player['name']
    current = rooms.get(player['room'], {})
    exits = current.get('exits', {})
    if direction not in exits:
        await ws.send("You can't go that way.")
        return
    target = exits[direction]
    if target not in rooms:
        await ws.send(f"The exit leads nowhere (missing room '{target}').")
        return
    await broadcast(ws, f"{name} leaves {direction}.")
    player['room'] = target
    known_players[name]['room'] = target
    save_players()
    await ws.send(f"You go {direction}.")
    await broadcast(ws, f"{name} enters from the {opposite_direction(direction)}.")
    await describe_room(ws)


# ---------- Command handling ----------

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
        await do_move(ws, tokens[1].lower())

    elif cmd == 'teleport' and len(tokens) > 1:
        if not is_admin(name):
            await ws.send("You are not allowed to use that command.")
            return
        title = " ".join(tokens[1:])
        key = find_room_key(title)
        if not key:
            await ws.send(f"No room titled '{title}'.")
            return
        if key == player['room']:
            await ws.send("You are already there.")
            return
        await broadcast(ws, f"{name} vanishes in a puff of smoke.")
        player['room'] = key
        known_players[name]['room'] = key
        save_players()
        await ws.send(f"You teleport to '{key}'.")
        await broadcast(ws, f"{name} appears out of thin air.")
        await describe_room(ws)

    elif cmd == 'say' and len(tokens) > 1:
        message = " ".join(tokens[1:])
        await send_to_room(ws, f"{name} says: {message}")

    elif cmd == 'describe' and len(tokens) > 1:
        new_desc = " ".join(tokens[1:])
        key = player['room']
        if key not in rooms:
            await ws.send("You are nowhere.")
            return
        rooms[key]['description'] = new_desc
        save_rooms()
        await ws.send("Room description updated.")
        await send_to_room(ws, f"{name} reshapes the room.", include_sender=False)

    elif cmd == 'create' and len(tokens) >= 2:
        sub = tokens[1].lower()
        if sub == 'room' and len(tokens) >= 3:
            title = " ".join(tokens[2:]).strip()
            if not title:
                await ws.send("Usage: create room <title>")
                return
            if title.lower() in RESERVED_WORDS:
                await ws.send(f"'{title}' is a reserved command name and can't be used as a room title.")
                return
            if find_room_key(title) is not None:
                await ws.send(f"A room titled '{title}' already exists.")
                return
            rooms[title] = {
                'description': 'An empty, featureless room.',
                'exits': {}
            }
            save_rooms()
            await ws.send(
                f"Room '{title}' created. "
                f"Use 'teleport {title}' to visit it, "
                f"or 'create direction <dir> {title}' from another room to link it."
            )
        elif sub == 'direction' and len(tokens) >= 4:
            direction = tokens[2].lower()
            if direction in RESERVED_WORDS:
                await ws.send(f"'{direction}' is a reserved command name and can't be used as a direction.")
                return
            target_title = " ".join(tokens[3:]).strip()
            target_key = find_room_key(target_title)
            if not target_key:
                await ws.send(f"No room titled '{target_title}'.")
                return
            current_key = player['room']
            if current_key not in rooms:
                await ws.send("You are nowhere.")
                return
            exits = rooms[current_key].setdefault('exits', {})
            if direction in exits:
                await ws.send(
                    f"There is already an exit '{direction}' from this room "
                    f"(to '{exits[direction]}')."
                )
                return
            exits[direction] = target_key

            # Auto-create the reverse exit when we know the opposite and the
            # slot is free on the target side.
            reverse_msg = ""
            opposite = opposite_direction(direction)
            if opposite == '?':
                reverse_msg = f" (no known opposite for '{direction}', no reverse exit created)"
            elif target_key == current_key:
                reverse_msg = ""  # self-loop: nothing to reverse
            else:
                target_exits = rooms[target_key].setdefault('exits', {})
                if opposite in target_exits:
                    reverse_msg = (
                        f" (reverse exit '{opposite}' in '{target_key}' "
                        f"already leads to '{target_exits[opposite]}', left untouched)"
                    )
                else:
                    target_exits[opposite] = current_key
                    reverse_msg = f" Reverse exit '{opposite}' from '{target_key}' now leads back to '{current_key}'."

            save_rooms()
            await ws.send(
                f"Exit '{direction}' from '{current_key}' now leads to '{target_key}'."
                + reverse_msg
            )
        else:
            await ws.send(
                "Usage:\n"
                "  create room <title>\n"
                "  create direction <dir> <target title>"
            )

    elif cmd == 'write' and len(tokens) > 1:
        note = " ".join(tokens[1:])
        filename = safe_room_filename(player['room'])
        timestamp = time.time()
        with open(filename, 'a') as f:
            f.write(f"{name} @ {timestamp}: {note}\n")
        await ws.send("Note saved.")

    elif cmd == 'read':
        filename = safe_room_filename(player['room'])
        if isfile(filename):
            with open(filename) as f:
                notes = f.read()
            await ws.send(f"Notes in this room:\n{notes}")
        else:
            await ws.send("No notes in this room.")

    elif cmd == 'list':
        if not is_admin(name):
            await ws.send("You are not allowed to use that command.")
            return
        if len(tokens) > 1 and tokens[1].lower() == 'rooms':
            if rooms:
                titles = sorted(rooms.keys(), key=lambda s: s.lower())
                await ws.send("All rooms (" + str(len(titles)) + "):\n  " + "\n  ".join(titles))
            else:
                await ws.send("No rooms defined.")
        else:
            try:
                entries = os.listdir(STORE_DIR)
            except OSError:
                entries = []
            files = [f[5:-4] for f in entries
                     if f.startswith('wiki_') and f.endswith('.txt')]
            if files:
                await ws.send("Rooms with notes: " + ", ".join(files))
            else:
                await ws.send("No rooms have notes yet.")

    elif cmd == 'delete' and len(tokens) >= 2:
        if not is_admin(name):
            await ws.send("You are not allowed to use that command.")
            return
        sub = tokens[1].lower()
        if sub == 'direction' and len(tokens) >= 3:
            direction = tokens[2].lower()
            current_key = player['room']
            if current_key not in rooms:
                await ws.send("You are nowhere.")
                return
            exits = rooms[current_key].get('exits', {})
            if direction not in exits:
                await ws.send(f"No exit '{direction}' from this room.")
                return
            target_key = exits.pop(direction)
            reverse_msg = ""
            opposite = opposite_direction(direction)
            if opposite != '?' and target_key in rooms:
                target_exits = rooms[target_key].get('exits', {})
                if target_exits.get(opposite) == current_key:
                    del target_exits[opposite]
                    reverse_msg = f" Reverse exit '{opposite}' in '{target_key}' also removed."
                elif opposite in target_exits:
                    reverse_msg = (
                        f" (reverse exit '{opposite}' in '{target_key}' "
                        f"points elsewhere, left alone)"
                    )
            save_rooms()
            await ws.send(f"Exit '{direction}' from '{current_key}' removed." + reverse_msg)
        else:
            await ws.send("Usage: delete direction <dir>")

    elif cmd == 'help':
        public = (
            "Commands:\n"
            "  look\n"
            "  go <direction>   (or just type the direction)\n"
            "  say <message>\n"
            "  write <note>  |  read\n"
            "  describe <new room description>\n"
            "  create room <title>\n"
            "  create direction <dir> <target title>\n"
        )
        admin = (
            "\nAdmin commands:\n"
            "  teleport <room title>\n"
            "  list                (rooms with wiki notes)\n"
            "  list rooms          (all rooms)\n"
            "  delete direction <dir>\n"
        )
        if is_admin(name):
            await ws.send(public + admin)
        else:
            await ws.send(public)

    else:
        # Shortcut: a bare direction name works like "go <direction>".
        current = rooms.get(player['room'], {})
        if cmd in current.get('exits', {}):
            await do_move(ws, cmd)
        else:
            await ws.send("Unknown command. Type 'help'.")


if __name__ == '__main__':
    import logging
    print("Starting MUD server locally...")
    logging.basicConfig(level=logging.INFO)
else:
    print("Starting MUD server on ESP32...")
app.run(port=PORT)