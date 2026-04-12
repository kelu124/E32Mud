"""
Game state, command handlers, and dispatch for E32Mud.

All shared mutable state lives in the Game class.
Command handlers are plain async functions registered in PUBLIC_COMMANDS
and ADMIN_COMMANDS dicts; admin gating is handled once in dispatch().
"""
import os
import time

from persistence import (
    atomic_write_json, load_json, store_path,
    safe_wiki_filename, isfile, ensure_store,
)
from auth import AuthState


# ── Default world ──────────────────────────────────────────────────────────

DEFAULT_ROOMS = {
    'hall': {
        'description': 'You are in a grand hall with arched ceilings.',
        'exits': {'north': 'library', 'east': 'kitchen'},
    },
    'library': {
        'description': 'Dusty books line the walls of this quiet library.',
        'exits': {'south': 'hall'},
    },
    'kitchen': {
        'description': 'A warm kitchen filled with the smell of bread.',
        'exits': {'west': 'hall'},
    },
}

_OPPOSITES = {
    'north': 'south', 'south': 'north',
    'east': 'west', 'west': 'east',
    'up': 'down', 'down': 'up',
}

def opposite_direction(direction):
    return _OPPOSITES.get(direction, '?')


# ── Game class ─────────────────────────────────────────────────────────────

class Game:
    """Central state container.  Created once in mud.py, passed everywhere."""

    def __init__(self, config):
        self.clients = set()
        self.players = {}

        # Config
        self.admins         = config.get('admins', set())
        self.start_room     = config.get('start_room', 'hall')
        self.store_dir      = config.get('store_dir', 'usr_store')
        self.max_input_len      = config.get('max_input_len', 1024)
        self.max_name_len       = config.get('max_name_len', 32)
        self.max_password_len   = config.get('max_password_len', 128)
        self.max_title_len      = config.get('max_title_len', 64)
        self.max_description_len = config.get('max_description_len', 500)
        self.max_say_len        = config.get('max_say_len', 400)
        self.max_note_len       = config.get('max_note_len', 300)
        self.max_wiki_bytes     = config.get('max_wiki_bytes', 10 * 1024)
        players_file = config.get('players_file', 'known_players.json')
        rooms_file   = config.get('rooms_file', 'rooms.json')

        # Derived paths
        ensure_store(self.store_dir)
        self._players_path = store_path(self.store_dir, players_file)
        self._rooms_path   = store_path(self.store_dir, rooms_file)

        # Load persisted data
        self.known_players = load_json(self._players_path, "known_players")
        if self.known_players is None:
            self.known_players = {}
            print("No known_players file yet, starting empty")
        else:
            print("Loaded", len(self.known_players), "known players")

        self.rooms = load_json(self._rooms_path, "rooms")
        if self.rooms is None:
            self.rooms = dict(DEFAULT_ROOMS)
            self.save_rooms()
            print("Seeded default rooms")
        else:
            print("Loaded", len(self.rooms), "rooms")

    # ── Persistence ────────────────────────────────────────────────────

    def save_rooms(self):
        atomic_write_json(self._rooms_path, self.rooms)

    def save_players(self):
        atomic_write_json(self._players_path, self.known_players)

    # ── Queries ────────────────────────────────────────────────────────

    def is_admin(self, name):
        if not name:
            return False
        low = name.lower()
        return any(a.lower() == low for a in self.admins)

    def find_room_key(self, title):
        """Case-insensitive room-title lookup; returns the stored key or None."""
        if not title:
            return None
        t = title.strip().lower()
        for key in self.rooms:
            if key.lower() == t:
                return key
        return None

    def find_player_key(self, name):
        """Case-insensitive player-name lookup; returns the stored key or None."""
        if not name:
            return None
        t = name.strip().lower()
        for key in self.known_players:
            if key.lower() == t:
                return key
        return None

    def is_name_online(self, name):
        for p in self.players.values():
            if p.get('name') == name and p.get('auth_state') == AuthState.AUTHENTICATED:
                return True
        return False

    def spawn_room(self):
        if self.start_room in self.rooms:
            return self.start_room
        return next(iter(self.rooms))

    def wiki_path(self, room_key):
        return safe_wiki_filename(self.store_dir, room_key)

    # ── Messaging ──────────────────────────────────────────────────────

    async def broadcast(self, sender_ws, message):
        """Send to every authenticated client except the sender."""
        for client in list(self.clients):
            if client != sender_ws:
                try:
                    await client.send(message)
                except Exception:
                    pass

    async def send_to_room(self, sender_ws, message, include_sender=True):
        """Send to every authenticated client in the same room as sender."""
        sender_room = self.players[sender_ws]['room']
        for ws in list(self.clients):
            if self.players.get(ws, {}).get('room') == sender_room:
                if not include_sender and ws == sender_ws:
                    continue
                try:
                    await ws.send(message)
                except Exception:
                    pass

    async def describe_room(self, ws):
        """Send the room description + exits + occupants to one client."""
        player = self.players[ws]
        key = player['room']
        room = self.rooms.get(key)
        if not room:
            await ws.send("You are lost in the void.")
            return
        desc = room.get('description', '(no description)')
        exits = room.get('exits', {})
        exits_txt = ", ".join(exits.keys()) if exits else "none"
        others = [
            self.players[c]['name']
            for c in self.clients
            if c != ws
            and self.players.get(c, {}).get('room') == key
            and self.players.get(c, {}).get('name')
        ]
        here = ("\nAlso here: " + ", ".join(others)) if others else ""
        await ws.send("\n[" + key + "]\n" + desc + "\nExits: " + exits_txt + here + "\n")


# ── Movement helper ────────────────────────────────────────────────────────

async def _do_move(game, ws, direction):
    player = game.players[ws]
    name = player['name']
    current = game.rooms.get(player['room'], {})
    exits = current.get('exits', {})
    if direction not in exits:
        await ws.send("You can't go that way.")
        return
    target = exits[direction]
    if target not in game.rooms:
        await ws.send("The exit leads nowhere (missing room '" + target + "').")
        return
    await game.broadcast(ws, name + " leaves " + direction + ".")
    player['room'] = target
    game.known_players[name]['room'] = target
    # Saved on disconnect to spare flash wear.
    await ws.send("You go " + direction + ".")
    await game.broadcast(ws, name + " enters from the " + opposite_direction(direction) + ".")
    await game.describe_room(ws)


# ══════════════════════════════════════════════════════════════════════════
#  Command handlers
#  Signature: async def cmd_xxx(game, ws, player, tokens)
# ══════════════════════════════════════════════════════════════════════════

async def cmd_look(game, ws, player, tokens):
    await game.describe_room(ws)


async def cmd_who(game, ws, player, tokens):
    online = [
        (pl['name'], pl['room'])
        for pl in game.players.values()
        if pl.get('auth_state') == AuthState.AUTHENTICATED and pl.get('name')
    ]
    if not online:
        await ws.send("Nobody's here.")
    else:
        online.sort(key=lambda t: t[0].lower())
        lines = ["  " + n + "  -  " + r for n, r in online]
        await ws.send("Players online (" + str(len(online)) + "):\n" + "\n".join(lines))


async def cmd_go(game, ws, player, tokens):
    if len(tokens) < 2:
        await ws.send("Go where?")
        return
    await _do_move(game, ws, tokens[1].lower())


async def cmd_say(game, ws, player, tokens):
    if len(tokens) < 2:
        await ws.send("Say what?")
        return
    message = " ".join(tokens[1:])
    if len(message) > game.max_say_len:
        await ws.send("Message too long (max " + str(game.max_say_len) + " characters).")
        return
    await game.send_to_room(ws, player['name'] + " says: " + message)


async def cmd_write(game, ws, player, tokens):
    if len(tokens) < 2:
        await ws.send("Write what?")
        return
    note = " ".join(tokens[1:])
    if len(note) > game.max_note_len:
        await ws.send("Note too long (max " + str(game.max_note_len) + " characters).")
        return
    filename = game.wiki_path(player['room'])
    current_size = 0
    try:
        current_size = os.stat(filename)[6]
    except OSError:
        current_size = 0
    if current_size >= game.max_wiki_bytes:
        await ws.send("The walls of this room are full. An elder must clear old notes first.")
        return
    timestamp = time.time()
    with open(filename, 'a') as f:
        f.write(player['name'] + " @ " + str(timestamp) + ": " + note + "\n")
    await ws.send("Note saved.")


async def cmd_read(game, ws, player, tokens):
    filename = game.wiki_path(player['room'])
    if isfile(filename):
        with open(filename) as f:
            notes = f.read()
        await ws.send("Notes in this room:\n" + notes)
    else:
        await ws.send("No notes in this room.")


async def cmd_help(game, ws, player, tokens):
    public = (
        "Commands:\n"
        "  look\n"
        "  who                 (players online)\n"
        "  go <direction>      (or just type the direction)\n"
        "  say <message>\n"
        "  write <note>  |  read\n"
    )
    admin = (
        "\nAdmin commands:\n"
        "  teleport <room title>\n"
        "  describe <new room description>\n"
        "  create room <title>\n"
        "  create direction <dir> <target title>\n"
        "  delete direction <dir>\n"
        "  delete room <title>\n"
        "  list                (rooms with wiki notes)\n"
        "  list rooms          (all rooms)\n"
        "  sysinfo             (system diagnostics)\n"
    )
    if game.is_admin(player['name']):
        await ws.send(public + admin)
    else:
        await ws.send(public)


# ── Admin commands ─────────────────────────────────────────────────────────

async def cmd_teleport(game, ws, player, tokens):
    if len(tokens) < 2:
        await ws.send("Teleport where?")
        return
    title = " ".join(tokens[1:])
    key = game.find_room_key(title)
    if not key:
        await ws.send("No room titled '" + title + "'.")
        return
    if key == player['room']:
        await ws.send("You are already there.")
        return
    name = player['name']
    await game.broadcast(ws, name + " vanishes in a puff of smoke.")
    player['room'] = key
    game.known_players[name]['room'] = key
    # Saved on disconnect.
    await ws.send("You teleport to '" + key + "'.")
    await game.broadcast(ws, name + " appears out of thin air.")
    await game.describe_room(ws)


async def cmd_describe(game, ws, player, tokens):
    if len(tokens) < 2:
        await ws.send("Describe what?")
        return
    new_desc = " ".join(tokens[1:])
    if len(new_desc) > game.max_description_len:
        await ws.send("Description too long (max " + str(game.max_description_len) + " characters).")
        return
    key = player['room']
    if key not in game.rooms:
        await ws.send("You are nowhere.")
        return
    game.rooms[key]['description'] = new_desc
    game.save_rooms()
    await ws.send("Room description updated.")
    await game.send_to_room(ws, player['name'] + " reshapes the room.", include_sender=False)


async def cmd_create(game, ws, player, tokens):
    if len(tokens) < 2:
        await ws.send(
            "Usage:\n"
            "  create room <title>\n"
            "  create direction <dir> <target title>"
        )
        return
    sub = tokens[1].lower()

    if sub == 'room':
        if len(tokens) < 3:
            await ws.send("Usage: create room <title>")
            return
        title = " ".join(tokens[2:]).strip()
        if not title:
            await ws.send("Usage: create room <title>")
            return
        if len(title) > game.max_title_len:
            await ws.send("Title too long (max " + str(game.max_title_len) + " characters).")
            return
        if title.lower() in RESERVED_WORDS:
            await ws.send("'" + title + "' is a reserved command name and can't be used as a room title.")
            return
        if game.find_room_key(title) is not None:
            await ws.send("A room titled '" + title + "' already exists.")
            return
        game.rooms[title] = {'description': 'An empty, featureless room.', 'exits': {}}
        game.save_rooms()
        await ws.send(
            "Room '" + title + "' created. "
            "Use 'teleport " + title + "' to visit it, "
            "or 'create direction <dir> " + title + "' from another room to link it."
        )

    elif sub == 'direction':
        if len(tokens) < 4:
            await ws.send("Usage: create direction <dir> <target title>")
            return
        direction = tokens[2].lower()
        if len(direction) > 20:
            await ws.send("Direction name too long (max 20 characters).")
            return
        if direction in RESERVED_WORDS:
            await ws.send("'" + direction + "' is a reserved command name and can't be used as a direction.")
            return
        target_title = " ".join(tokens[3:]).strip()
        target_key = game.find_room_key(target_title)
        if not target_key:
            await ws.send("No room titled '" + target_title + "'.")
            return
        current_key = player['room']
        if current_key not in game.rooms:
            await ws.send("You are nowhere.")
            return
        exits = game.rooms[current_key].setdefault('exits', {})
        if direction in exits:
            await ws.send(
                "There is already an exit '" + direction + "' from this room "
                "(to '" + exits[direction] + "')."
            )
            return
        exits[direction] = target_key

        # Auto-create the reverse exit when we know the opposite and the
        # slot is free on the target side.
        reverse_msg = ""
        opp = opposite_direction(direction)
        if opp == '?':
            reverse_msg = " (no known opposite for '" + direction + "', no reverse exit created)"
        elif target_key == current_key:
            reverse_msg = ""  # self-loop
        else:
            target_exits = game.rooms[target_key].setdefault('exits', {})
            if opp in target_exits:
                reverse_msg = (
                    " (reverse exit '" + opp + "' in '" + target_key +
                    "' already leads to '" + target_exits[opp] + "', left untouched)"
                )
            else:
                target_exits[opp] = current_key
                reverse_msg = (
                    " Reverse exit '" + opp + "' from '" + target_key +
                    "' now leads back to '" + current_key + "'."
                )

        game.save_rooms()
        await ws.send(
            "Exit '" + direction + "' from '" + current_key +
            "' now leads to '" + target_key + "'." + reverse_msg
        )

    else:
        await ws.send(
            "Usage:\n"
            "  create room <title>\n"
            "  create direction <dir> <target title>"
        )


async def cmd_delete(game, ws, player, tokens):
    if len(tokens) < 2:
        await ws.send("Usage:\n  delete direction <dir>\n  delete room <title>")
        return
    sub = tokens[1].lower()

    if sub == 'direction':
        if len(tokens) < 3:
            await ws.send("Usage: delete direction <dir>")
            return
        direction = tokens[2].lower()
        current_key = player['room']
        if current_key not in game.rooms:
            await ws.send("You are nowhere.")
            return
        exits = game.rooms[current_key].get('exits', {})
        if direction not in exits:
            await ws.send("No exit '" + direction + "' from this room.")
            return
        target_key = exits.pop(direction)
        reverse_msg = ""
        opp = opposite_direction(direction)
        if opp != '?' and target_key in game.rooms:
            target_exits = game.rooms[target_key].get('exits', {})
            if target_exits.get(opp) == current_key:
                del target_exits[opp]
                reverse_msg = " Reverse exit '" + opp + "' in '" + target_key + "' also removed."
            elif opp in target_exits:
                reverse_msg = (
                    " (reverse exit '" + opp + "' in '" + target_key +
                    "' points elsewhere, left alone)"
                )
        game.save_rooms()
        await ws.send("Exit '" + direction + "' from '" + current_key + "' removed." + reverse_msg)

    elif sub == 'room':
        if len(tokens) < 3:
            await ws.send("Usage: delete room <title>")
            return
        title = " ".join(tokens[2:]).strip()
        key = game.find_room_key(title)
        if not key:
            await ws.send("No room titled '" + title + "'.")
            return
        if key == game.start_room:
            await ws.send("Can't delete the spawn room ('" + game.start_room + "').")
            return
        occupants = [
            pl['name'] for pl in game.players.values()
            if pl.get('auth_state') == AuthState.AUTHENTICATED
            and pl.get('room') == key and pl.get('name')
        ]
        if occupants:
            await ws.send(
                "Can't delete '" + key + "': still occupied by " +
                ", ".join(occupants) + "."
            )
            return
        removed_exits = 0
        for other_key in list(game.rooms.keys()):
            if other_key == key:
                continue
            other_exits = game.rooms[other_key].get('exits', {})
            for d in [d for d, t in other_exits.items() if t == key]:
                del other_exits[d]
                removed_exits += 1
        migrated = 0
        for pname, rec in game.known_players.items():
            if rec.get('room') == key:
                rec['room'] = game.start_room
                migrated += 1
        del game.rooms[key]
        game.save_rooms()
        if migrated:
            game.save_players()
        wiki_removed = False
        try:
            os.remove(game.wiki_path(key))
            wiki_removed = True
        except OSError:
            pass
        parts = ["Room '" + key + "' deleted."]
        if removed_exits:
            parts.append("Removed " + str(removed_exits) + " incoming exit(s).")
        if migrated:
            parts.append("Migrated " + str(migrated) + " offline player(s) to '" + game.start_room + "'.")
        if wiki_removed:
            parts.append("Wiki notes cleared.")
        await ws.send(" ".join(parts))

    else:
        await ws.send("Usage:\n  delete direction <dir>\n  delete room <title>")


async def cmd_list(game, ws, player, tokens):
    if len(tokens) > 1 and tokens[1].lower() == 'rooms':
        if game.rooms:
            titles = sorted(game.rooms.keys(), key=lambda s: s.lower())
            await ws.send("All rooms (" + str(len(titles)) + "):\n  " + "\n  ".join(titles))
        else:
            await ws.send("No rooms defined.")
    else:
        try:
            entries = os.listdir(game.store_dir)
        except OSError:
            entries = []
        wiki_files = [f for f in entries if f.startswith('wiki_') and f.endswith('.txt')]
        if wiki_files:
            fname_to_title = {}
            for rk in game.rooms:
                fname = game.wiki_path(rk).rsplit('/', 1)[-1]
                fname_to_title[fname] = rk
            titles = sorted(
                (fname_to_title.get(f, "(orphaned) " + f[5:-4]) for f in wiki_files),
                key=lambda s: s.lower(),
            )
            await ws.send("Rooms with notes:\n  " + "\n  ".join(titles))
        else:
            await ws.send("No rooms have notes yet.")


async def cmd_sysinfo(game, ws, player, tokens):
    # Lazy import — only loaded when an admin actually runs the command.
    from sysinfo import get_sysinfo
    await ws.send(get_sysinfo())


# ══════════════════════════════════════════════════════════════════════════
#  Dispatch tables
# ══════════════════════════════════════════════════════════════════════════

PUBLIC_COMMANDS = {
    'look':  cmd_look,
    'who':   cmd_who,
    'go':    cmd_go,
    'say':   cmd_say,
    'write': cmd_write,
    'read':  cmd_read,
    'help':  cmd_help,
}

ADMIN_COMMANDS = {
    'teleport': cmd_teleport,
    'describe': cmd_describe,
    'create':   cmd_create,
    'delete':   cmd_delete,
    'list':     cmd_list,
    'sysinfo':  cmd_sysinfo,
}

# Auto-derived from the dispatch tables: prevents anyone from creating
# a room or direction named after a command verb.
RESERVED_WORDS = set(PUBLIC_COMMANDS.keys()) | set(ADMIN_COMMANDS.keys())


async def dispatch(game, ws, msg):
    """Route a command string to the appropriate handler."""
    player = game.players[ws]
    name = player['name']
    tokens = msg.strip().split()
    if not tokens:
        return
    cmd = tokens[0].lower()

    handler = PUBLIC_COMMANDS.get(cmd)
    if handler:
        await handler(game, ws, player, tokens)
        return

    handler = ADMIN_COMMANDS.get(cmd)
    if handler:
        if not game.is_admin(name):
            await ws.send("You are not allowed to use that command.")
        else:
            await handler(game, ws, player, tokens)
        return

    # Shortcut: bare direction name → go <direction>
    current = game.rooms.get(player['room'], {})
    if cmd in current.get('exits', {}):
        await _do_move(game, ws, cmd)
    else:
        await ws.send("Unknown command. Type 'help'.")