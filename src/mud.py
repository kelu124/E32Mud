"""
E32Mud server — entry point.

Thin shell: Microdot app, WebSocket handler with authentication state
machine, delegates all in-game commands to commands.dispatch().

Configuration is at the top of this file.  Change ADMINS, PORT, limits,
etc. here; everything else is imported.
"""
from microdot import Microdot, Response
from microdot.websocket import with_websocket
try:
    from microdot.websocket import WebSocketError
except ImportError:
    class WebSocketError(Exception):
        pass

import sys

from homepage import html
from auth import AuthState, set_password, check_password
from commands import Game, dispatch

# ══════════════════════════════════════════════════════════════════════════
#  Configuration — edit these for your deployment
# ══════════════════════════════════════════════════════════════════════════

if 'esp' in sys.platform:
    print("Running on ESP32")
    PORT = 80
else:
    print("Running classically")
    PORT = 5000

ADMINS = set()  # e.g. {'kelu', 'alice'}

CONFIG = {
    'admins':            ADMINS,
    'start_room':        'hall',
    'store_dir':         'usr_store',
    'players_file':      'known_players.json',
    'rooms_file':        'rooms.json',
    # Input limits
    'max_input_len':     1024,
    'max_name_len':      32,
    'max_password_len':  128,
    'max_title_len':     64,
    'max_description_len': 500,
    'max_say_len':       400,
    'max_note_len':      300,
    'max_wiki_bytes':    10 * 1024,
}

# ══════════════════════════════════════════════════════════════════════════
#  Game + Microdot app
# ══════════════════════════════════════════════════════════════════════════

game = Game(CONFIG)

app = Microdot()
Response.default_content_type = 'text/html'


@app.route('/')
def index(request):
    print("Serving index page")
    return html(PORT)


@app.route('/ws', methods=['GET', 'WEBSOCKET'])
@with_websocket
async def websocket_handler(request, ws):
    # ws is NOT added to game.clients until auth succeeds, so broadcasts
    # don't leak to someone still at the login prompt.
    spawn = game.spawn_room()
    game.players[ws] = {
        'name':        None,
        'room':        spawn,
        'auth_state':  AuthState.AWAIT_NAME,
        'pending_name': None,
    }
    try:
        await ws.send("Welcome to the MUD!\nPlease enter your name:")
        while True:
            msg = await ws.receive()
            if msg is None:
                break
            if not isinstance(msg, str):
                continue
            if len(msg) > game.max_input_len:
                await ws.send("Input too long (max " + str(game.max_input_len) + " characters).")
                continue

            p = game.players[ws]
            state = p['auth_state']

            # ── AWAIT NAME ─────────────────────────────────────────────
            if state == AuthState.AWAIT_NAME:
                if msg.startswith('__auth '):
                    name = msg.split(' ', 1)[1].strip()
                else:
                    name = msg.strip()
                if not name:
                    await ws.send("Name cannot be empty. Please enter your name:")
                    continue
                if len(name) > game.max_name_len:
                    await ws.send("Name too long (max " + str(game.max_name_len) + " characters). Please enter your name:")
                    continue

                existing_key = game.find_player_key(name)
                if existing_key is not None:
                    name = existing_key  # canonical casing
                    rec = game.known_players[name]
                    p['pending_name'] = name
                    if 'pw_hash' not in rec:
                        p['auth_state'] = AuthState.AWAIT_NEW_PW
                        await ws.send("Welcome back, " + name + ". Please set a password for your account:")
                    else:
                        p['auth_state'] = AuthState.AWAIT_LOGIN_PW
                        await ws.send("Welcome back, " + name + ". Please enter your password:")
                else:
                    p['pending_name'] = name
                    p['auth_state'] = AuthState.AWAIT_NEW_PW
                    await ws.send("Hello, " + name + ". Please choose a password:")

            # ── AWAIT LOGIN PASSWORD ───────────────────────────────────
            elif state == AuthState.AWAIT_LOGIN_PW:
                name = p['pending_name']
                rec = game.known_players.get(name, {})
                if len(msg) > game.max_password_len:
                    await ws.send("Wrong password. Please enter your name:")
                    p['auth_state'] = AuthState.AWAIT_NAME
                    p['pending_name'] = None
                    continue
                if check_password(rec, msg):
                    if game.is_name_online(name):
                        await ws.send(
                            "This account is already logged in elsewhere. "
                            "Close the other session first.\nPlease enter your name:"
                        )
                        p['auth_state'] = AuthState.AWAIT_NAME
                        p['pending_name'] = None
                        continue
                    p['name'] = name
                    room_key = rec.get('room', spawn)
                    if room_key not in game.rooms:
                        room_key = spawn
                    p['room'] = room_key
                    p['auth_state'] = AuthState.AUTHENTICATED
                    p['pending_name'] = None
                    game.clients.add(ws)
                    await ws.send("Welcome back, " + name + "!")
                    await game.broadcast(ws, name + " has entered the game.")
                    await game.describe_room(ws)
                else:
                    await ws.send("Wrong password. Please enter your name:")
                    p['auth_state'] = AuthState.AWAIT_NAME
                    p['pending_name'] = None

            # ── AWAIT NEW PASSWORD (registration / legacy upgrade) ─────
            elif state == AuthState.AWAIT_NEW_PW:
                password = msg
                if not password:
                    await ws.send("Password cannot be empty. Please choose a password:")
                    continue
                if len(password) > game.max_password_len:
                    await ws.send("Password too long (max " + str(game.max_password_len) + " characters). Please choose a password:")
                    continue
                name = p['pending_name']
                rec = game.known_players.get(name, {'room': spawn})
                set_password(rec, password)
                if 'room' not in rec or rec['room'] not in game.rooms:
                    rec['room'] = spawn
                game.known_players[name] = rec
                game.save_players()
                p['name'] = name
                p['room'] = rec['room']
                p['auth_state'] = AuthState.AUTHENTICATED
                p['pending_name'] = None
                game.clients.add(ws)
                await ws.send("Password set. Welcome, " + name + "! Type 'look' to see your surroundings, or 'help' for commands.")
                await game.broadcast(ws, name + " has entered the game.")
                await game.describe_room(ws)

            # ── AUTHENTICATED — dispatch command ───────────────────────
            else:
                await dispatch(game, ws, msg)

    except WebSocketError:
        pass
    except OSError as e:
        print("WebSocket connection dropped:", e)
    except Exception as e:
        print("WebSocket error:", type(e).__name__, e)
    finally:
        game.clients.discard(ws)
        p = game.players.pop(ws, None) or {}
        name = p.get('name')
        if name and name in game.known_players:
            game.known_players[name]['room'] = p.get('room', spawn)
            game.save_players()
            for other in list(game.clients):
                try:
                    await other.send(name + " has left the game.")
                except Exception:
                    pass
        try:
            await ws.close()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════
#  Start
# ══════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import logging
    print("Starting MUD server locally...")
    logging.basicConfig(level=logging.INFO)
else:
    print("Starting MUD server on ESP32...")
app.run(port=PORT)
