# E32Mud

A self-contained MUD (Multi-User Dungeon) server that runs on an **ESP32-C3** microcontroller. Flash the firmware, power up the board, and it becomes a pocket WiFi hotspot running a live text adventure — accessible from any phone or laptop browser with no apps required.

---

## What it does

When the ESP32 boots, it:

1. Creates a WiFi access point called **OpenMUD_4000**
2. Starts a captive-portal DNS server so any HTTP request on the network resolves to the device
3. Starts a Microdot web server on port 80 that serves a browser-based terminal and accepts WebSocket connections

Anyone who connects to the hotspot and opens a browser is dropped straight into the game. Multiple players can be in the world simultaneously. Player accounts, room state, and room notes all survive reboots.

It also runs on a normal PC for development — `python mud.py` starts it on port 5000.

---

## Architecture

```
main.py          ESP32 entry point — starts AP, DNS thread, then mud.py
mud.py           Microdot app; WebSocket handler; auth state machine; config
commands.py      Game class (all shared state) + command handlers + dispatch
auth.py          Password hashing (SHA-256 + salt) and auth state constants
persistence.py   Atomic JSON writes, crash recovery, filesystem helpers
homepage.py      Browser terminal (served as HTML at /)
captive.py       UDP DNS server — redirects all queries to 192.168.4.1
sysinfo.py       System diagnostics (RAM, flash, CPU, WiFi, uptime)
client_bare.py   Python desktop client (alternative to the browser UI)
test_mud.py      Integration test suite — 75 checks across 10 groups
```

The `microdot/` package (inside `src/`) is a third-party MicroPython-compatible web framework included as a vendored dependency. Do not edit files inside it.

---

## Key components

### `mud.py` — Server and configuration

All tunable settings live at the top of this file:

| Setting | Default | Meaning |
|---|---|---|
| `ADMINS` | `set()` | Set of admin usernames, e.g. `{'alice'}` |
| `start_room` | `'hall'` | Spawn room for new players |
| `store_dir` | `'usr_store'` | Directory for persisted JSON and wiki files |
| `max_input_len` | 1024 | Hard cap on any single message |
| `max_say_len` | 400 | Cap on `say` messages |
| `max_note_len` | 300 | Cap on a single wiki note |
| `max_wiki_bytes` | 10 240 | Total wiki bytes per room |
| `max_title_len` | 64 | Room title length |
| `max_description_len` | 500 | Room description length |

The server auto-detects its platform: port 80 on ESP32, port 5000 on a regular Python interpreter.

### `commands.py` — Game world and commands

All in-game mutable state lives in the `Game` class. It loads `known_players.json` and `rooms.json` from `usr_store/` on startup (or seeds defaults if they don't exist). The default world has three rooms: **hall**, **library**, and **kitchen**.

Player commands are split into two dispatch tables:

**Public commands** (any authenticated player):

| Command | Effect |
|---|---|
| `look` | Describe the current room, exits, and other players present |
| `go <direction>` | Move through an exit; also accepts a bare direction name |
| `say <message>` | Broadcast a message to everyone in the same room |
| `who` | List all online players and their locations |
| `write <note>` | Append a timestamped note to the current room's wiki file |
| `read` | Show all notes left in the current room |
| `help` | Print available commands |

**Admin commands** (username must be in `ADMINS`):

| Command | Effect |
|---|---|
| `teleport <room>` | Instantly move to any room |
| `describe <text>` | Set the current room's description |
| `create room <title>` | Create a new (empty) room |
| `create direction <dir> <room>` | Link current room to a target; auto-creates the reverse exit |
| `delete direction <dir>` | Remove an exit (and its automatic reverse) |
| `delete room <title>` | Delete a room (refused if occupied; migrates offline players) |
| `list` | Show rooms that have wiki notes |
| `list rooms` | Show all rooms |
| `sysinfo` | Print platform, RAM, flash, WiFi, and uptime info |

### `auth.py` — Authentication

Each connection steps through a state machine: `AWAIT_NAME` → `AWAIT_LOGIN_PW` or `AWAIT_NEW_PW` → `AUTHENTICATED`. Passwords are stored as SHA-256 hashes with a random 8-byte salt. Player names are case-insensitive; the canonical casing from first registration is preserved.

The browser client caches the player name in `localStorage` and sends it as `__auth <name>` on reconnect, so returning players skip the name prompt.

### `persistence.py` — Crash-safe storage

JSON files are written atomically: data goes to a `.tmp` file first, then `os.rename()` replaces the target. On load, if the main file is missing or corrupt it is backed up as `.corrupt` and the `.tmp` survivor (if any) is recovered. This guards against data loss from sudden power cuts — normal on battery-powered embedded hardware.

Wiki notes are stored as plain text files in `usr_store/`, named `wiki_<sanitised_room_key>.txt`.

### `captive.py` — Captive portal DNS

A minimal UDP DNS server that answers every query with the ESP32's own IP (`192.168.4.1`). This triggers the captive-portal popup on most mobile operating systems, dropping the user directly into the browser UI without needing to know the IP.

### `homepage.py` — Browser terminal

A single-page HTML/JS app served at `/`. It opens a WebSocket to `/ws`, displays server messages in a scrolling monospace terminal, and sends user input on Enter. Green-on-black colour scheme.

---

## Running on a PC (development)

```bash
cd src
pip install microdot websockets
python mud.py
# → Starting MUD server locally...
# → http://127.0.0.1:5000/
```

Open `http://localhost:5000` in a browser, or connect with the Python client:

```bash
python client_bare.py 127.0.0.1 5000 YourName
```

---

## Flashing to an ESP32-C3

1. Install [esptool](https://github.com/espressif/esptool): `pip install esptool`
2. Flash the bundled MicroPython firmware:
   ```bash
   esptool.py --chip esp32c3 --port /dev/ttyUSB0 erase_flash
   esptool.py --chip esp32c3 --port /dev/ttyUSB0 write_flash -z 0x0 \
       micropython/ESP32_GENERIC_C3-20250415-v1.25.0.bin
   ```
3. Copy the `src/` files to the board using [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html) or [ampy](https://github.com/scientifichackers/ampy):
   ```bash
   mpremote cp src/auth.py src/captive.py src/commands.py src/homepage.py \
       src/main.py src/mud.py src/persistence.py src/sysinfo.py :
   mpremote cp -r src/microdot :microdot
   ```
4. Reset the board. It will create the **OpenMUD_4000** hotspot automatically on every boot.

To set admin usernames, edit `ADMINS` in `mud.py` before copying:
```python
ADMINS = {'alice', 'bob'}
```

---

## Running tests

```bash
cd src
pip install websockets
python test_mud.py
```

The test suite spins up the server in a temporary directory on port 5111, runs 75 checks across 10 groups (auth, navigation, communication, wiki, admin building, admin deletion, non-admin restrictions, help, input limits, persistence), then shuts down and cleans up. Exits 0 on success, 1 on any failure.

See [Testing](./Readme_test_mud.md) for the full test-group breakdown.
