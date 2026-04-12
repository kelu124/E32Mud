#!/usr/bin/env python3
"""
Integration tests for E32Mud v0.3.

Spins up the MUD server in a subprocess with a clean data directory,
connects via WebSocket, exercises every command, and reports pass/fail.

Requirements:
    pip install websockets

Usage:
    python test_mud.py              # from the v0.3 directory (where mud.py lives)
    python test_mud.py /path/to/v0.3  # or specify the source folder explicitly
"""
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback

import websockets

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PORT = 5111               # Avoid colliding with a dev server on 5000
ADMIN_NAME = "TestAdmin"
ADMIN_PW   = "adminpass"
USER_NAME  = "TestUser"
USER_PW    = "userpass"
WS_URI     = f"ws://127.0.0.1:{PORT}/ws"

# How long to wait for server responses (seconds).
RECV_TIMEOUT = 2.0
# How long to wait for the server process to start.
STARTUP_TIMEOUT = 6.0

# Files that must exist in the source directory.
REQUIRED_FILES = ["mud.py", "homepage.py", "commands.py", "persistence.py", "auth.py", "sysinfo.py", "microdot"]

# ---------------------------------------------------------------------------
# Colour helpers (no dependencies)
# ---------------------------------------------------------------------------
GREEN = "\033[92m"
RED   = "\033[91m"
YELLOW = "\033[93m"
BOLD  = "\033[1m"
RESET = "\033[0m"

# ---------------------------------------------------------------------------
# Test bookkeeping
# ---------------------------------------------------------------------------
_results = []  # list of (group, name, passed, detail)

def _record(group, name, passed, detail=""):
    tag = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    print(f"  {tag}  {group} / {name}" + (f"  ({detail})" if detail and not passed else ""))
    _results.append((group, name, passed, detail))

def summary():
    total  = len(_results)
    passed = sum(1 for *_, p, _ in _results if p)
    failed = total - passed
    print()
    print(f"{BOLD}{'='*60}{RESET}")
    print(f"  Total: {total}   {GREEN}Passed: {passed}{RESET}   {RED}Failed: {failed}{RESET}")
    if failed:
        print(f"\n  {RED}Failed tests:{RESET}")
        for g, n, p, d in _results:
            if not p:
                print(f"    • {g} / {n}: {d}")
    print(f"{BOLD}{'='*60}{RESET}")
    return failed == 0

# ---------------------------------------------------------------------------
# WebSocket helpers
# ---------------------------------------------------------------------------
async def recv_all(ws, timeout=RECV_TIMEOUT):
    """Receive all messages the server sends within `timeout`, return as one string."""
    parts = []
    while True:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
            parts.append(msg)
            # After the first message, use a shorter window to drain follow-ups.
            timeout = 0.3
        except asyncio.TimeoutError:
            break
    return "\n".join(parts)

async def send_and_recv(ws, command, timeout=RECV_TIMEOUT):
    """Send a command, then return the combined server response."""
    await ws.send(command)
    return await recv_all(ws, timeout)

async def connect():
    """Open a raw WebSocket connection and return (ws, welcome_text)."""
    ws = await websockets.connect(WS_URI)
    welcome = await recv_all(ws)
    return ws, welcome

async def register(name, password):
    """Connect, register a new account, return (ws, full_response)."""
    ws, welcome = await connect()
    await ws.send(name)
    resp = await recv_all(ws)            # "choose a password"
    await ws.send(password)
    resp2 = await recv_all(ws)           # "Password set. Welcome, ..."
    return ws, welcome + "\n" + resp + "\n" + resp2

async def login(name, password):
    """Connect, log in to an existing account, return (ws, full_response)."""
    ws, welcome = await connect()
    await ws.send(name)
    resp = await recv_all(ws)            # "enter your password"
    await ws.send(password)
    resp2 = await recv_all(ws)           # "Welcome back, ..."
    return ws, welcome + "\n" + resp + "\n" + resp2

# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

async def test_auth():
    group = "Auth"

    # 1. Register admin
    ws, resp = await register(ADMIN_NAME, ADMIN_PW)
    _record(group, "register admin", "Password set" in resp and ADMIN_NAME in resp, resp[:120])
    await ws.close()

    # 2. Register normal user
    ws, resp = await register(USER_NAME, USER_PW)
    _record(group, "register user", "Password set" in resp and USER_NAME in resp, resp[:120])
    await ws.close()

    # 3. Login with correct password
    ws, resp = await login(ADMIN_NAME, ADMIN_PW)
    _record(group, "login correct password", "Welcome back" in resp, resp[:120])
    await ws.close()

    # 4. Login with wrong password
    ws, _ = await connect()
    await ws.send(ADMIN_NAME)
    await recv_all(ws)
    resp = await send_and_recv(ws, "wrongpassword")
    _record(group, "login wrong password", "Wrong password" in resp, resp[:120])
    await ws.close()

    # 5. Case-insensitive login
    ws, _ = await connect()
    await ws.send(ADMIN_NAME.upper())
    resp = await recv_all(ws)
    ok = "Welcome back" in resp or "password" in resp.lower()
    _record(group, "case-insensitive name lookup", ok, resp[:120])
    await ws.close()

    # 6. Name too long
    ws, _ = await connect()
    resp = await send_and_recv(ws, "A" * 50)
    _record(group, "name too long rejected", "too long" in resp.lower(), resp[:120])
    await ws.close()

    # 7. Empty name
    ws, _ = await connect()
    resp = await send_and_recv(ws, "")
    # Empty string might not even trigger the server, but a space-only one should.
    resp2 = await send_and_recv(ws, "   ")
    combined = resp + resp2
    _record(group, "empty name rejected", "cannot be empty" in combined.lower() or "enter your name" in combined.lower(), combined[:120])
    await ws.close()

    # 8. Double login rejected
    ws1, _ = await login(ADMIN_NAME, ADMIN_PW)
    ws2, _ = await connect()
    await ws2.send(ADMIN_NAME)
    await recv_all(ws2)
    resp = await send_and_recv(ws2, ADMIN_PW)
    _record(group, "double login rejected", "already logged in" in resp.lower(), resp[:120])
    await ws2.close()
    await ws1.close()

    # 9. Duplicate registration (case-insensitive)
    ws, _ = await connect()
    await ws.send(USER_NAME.lower())  # "testuser" when "TestUser" exists
    resp = await recv_all(ws)
    ok = "Welcome back" in resp or "password" in resp.lower()
    _record(group, "no duplicate registration (case-insensitive)", ok, resp[:120])
    await ws.close()


async def test_navigation():
    group = "Navigation"
    ws, _ = await login(ADMIN_NAME, ADMIN_PW)

    # 1. look
    resp = await send_and_recv(ws, "look")
    _record(group, "look shows room", "[hall]" in resp and "Exits:" in resp, resp[:120])

    # 2. go north
    resp = await send_and_recv(ws, "go north")
    _record(group, "go north to library", "library" in resp.lower() and "You go north" in resp, resp[:150])

    # 3. Bare direction shortcut: south
    resp = await send_and_recv(ws, "south")
    _record(group, "bare direction shortcut (south)", "You go south" in resp and "hall" in resp.lower(), resp[:150])

    # 4. Invalid direction
    resp = await send_and_recv(ws, "go up")
    _record(group, "invalid direction rejected", "can't go" in resp.lower(), resp[:120])

    # 5. Unknown command
    resp = await send_and_recv(ws, "dance")
    _record(group, "unknown command", "unknown command" in resp.lower(), resp[:120])

    await ws.close()


async def test_communication():
    group = "Communication"

    ws1, _ = await login(ADMIN_NAME, ADMIN_PW)
    ws2, _ = await login(USER_NAME, USER_PW)

    # Both start in hall.

    # 1. say — sender sees it
    resp = await send_and_recv(ws1, "say hello world")
    _record(group, "say echoed to sender", f"{ADMIN_NAME} says: hello world" in resp, resp[:120])

    # 2. say — other player in room sees it
    resp2 = await recv_all(ws2, timeout=0.5)
    _record(group, "say received by other", f"{ADMIN_NAME} says: hello world" in resp2, resp2[:120])

    # 3. who
    resp = await send_and_recv(ws1, "who")
    ok = ADMIN_NAME in resp and USER_NAME in resp and "Players online" in resp
    _record(group, "who lists both players", ok, resp[:150])

    # 4. Movement broadcast — user moves, admin sees departure
    await send_and_recv(ws2, "go north")
    departure = await recv_all(ws1, timeout=0.5)
    _record(group, "departure broadcast", f"{USER_NAME} leaves north" in departure, departure[:120])

    # 5. say in different room — admin should NOT see user's say
    await send_and_recv(ws2, "say secret")
    leaked = await recv_all(ws1, timeout=0.5)
    _record(group, "say does not leak across rooms", "secret" not in leaked, f"leaked: '{leaked[:80]}'")

    # Put user back
    await send_and_recv(ws2, "south")
    await recv_all(ws1, timeout=0.3)  # drain arrival broadcast

    await ws2.close()

    # 6. Logout broadcast
    logout_msg = await recv_all(ws1, timeout=1.0)
    _record(group, "logout broadcast", f"{USER_NAME} has left" in logout_msg, logout_msg[:120])

    await ws1.close()


async def test_wiki():
    group = "Wiki"
    ws, _ = await login(ADMIN_NAME, ADMIN_PW)

    # 1. read empty
    resp = await send_and_recv(ws, "read")
    _record(group, "read empty room", "no notes" in resp.lower(), resp[:120])

    # 2. write
    resp = await send_and_recv(ws, "write This is a test note")
    _record(group, "write note", "note saved" in resp.lower(), resp[:120])

    # 3. read back
    resp = await send_and_recv(ws, "read")
    _record(group, "read note back", "This is a test note" in resp, resp[:150])

    # 4. list (admin) — wiki notes
    resp = await send_and_recv(ws, "list")
    _record(group, "list shows rooms with notes", "hall" in resp.lower(), resp[:120])

    # 5. Note too long
    resp = await send_and_recv(ws, "write " + "x" * 350)
    _record(group, "note too long rejected", "too long" in resp.lower(), resp[:120])

    await ws.close()


async def test_admin_building():
    group = "Admin building"
    ws, _ = await login(ADMIN_NAME, ADMIN_PW)

    # 1. create room
    resp = await send_and_recv(ws, "create room Dungeon")
    _record(group, "create room", "Room 'Dungeon' created" in resp, resp[:120])

    # 2. Duplicate room (case-insensitive)
    resp = await send_and_recv(ws, "create room dungeon")
    _record(group, "duplicate room rejected", "already exists" in resp.lower(), resp[:120])

    # 3. Reserved word as room title
    resp = await send_and_recv(ws, "create room look")
    _record(group, "reserved room title rejected", "reserved" in resp.lower(), resp[:120])

    # 4. Room title too long
    resp = await send_and_recv(ws, "create room " + "A" * 70)
    _record(group, "title too long rejected", "too long" in resp.lower(), resp[:120])

    # 5. create direction (with auto-reverse)
    resp = await send_and_recv(ws, "create direction down Dungeon")
    ok = "Exit 'down'" in resp and "Reverse exit 'up'" in resp
    _record(group, "create direction + auto-reverse", ok, resp[:200])

    # 6. Verify reverse exit exists by teleporting and looking
    resp = await send_and_recv(ws, "teleport Dungeon")
    _record(group, "teleport to Dungeon", "teleport" in resp.lower() and "Dungeon" in resp, resp[:120])

    resp = await send_and_recv(ws, "look")
    _record(group, "Dungeon has reverse exit 'up'", "up" in resp.lower(), resp[:120])

    # 7. Reserved word as direction name
    resp = await send_and_recv(ws, "create direction help library")
    _record(group, "reserved direction name rejected", "reserved" in resp.lower(), resp[:120])

    # 8. Duplicate direction
    resp = await send_and_recv(ws, "create direction up hall")
    _record(group, "duplicate direction rejected", "already an exit" in resp.lower(), resp[:120])

    # 9. describe
    await send_and_recv(ws, "teleport hall")
    resp = await send_and_recv(ws, "describe A shiny new hall.")
    _record(group, "describe room", "description updated" in resp.lower(), resp[:120])

    resp = await send_and_recv(ws, "look")
    _record(group, "description persisted", "shiny new hall" in resp.lower(), resp[:120])

    # 10. Description too long
    resp = await send_and_recv(ws, "describe " + "B" * 510)
    _record(group, "description too long rejected", "too long" in resp.lower(), resp[:120])

    # 11. list rooms
    resp = await send_and_recv(ws, "list rooms")
    ok = "Dungeon" in resp and "hall" in resp and "library" in resp and "kitchen" in resp
    _record(group, "list rooms", ok, resp[:200])

    # 12. teleport — already there
    resp = await send_and_recv(ws, "teleport hall")
    _record(group, "teleport already there", "already there" in resp.lower(), resp[:120])

    # 13. teleport — nonexistent room
    resp = await send_and_recv(ws, "teleport Narnia")
    _record(group, "teleport nonexistent room", "no room" in resp.lower(), resp[:120])

    await ws.close()


async def test_admin_deletion():
    group = "Admin deletion"
    ws, _ = await login(ADMIN_NAME, ADMIN_PW)

    # Setup: create a room to delete, link it
    await send_and_recv(ws, "create room TempRoom")
    await send_and_recv(ws, "create direction west TempRoom")

    # 1. delete direction
    resp = await send_and_recv(ws, "delete direction west")
    ok = "removed" in resp.lower() and "west" in resp.lower()
    _record(group, "delete direction", ok, resp[:150])

    # Verify reverse was also removed
    await send_and_recv(ws, "teleport TempRoom")
    resp = await send_and_recv(ws, "look")
    _record(group, "reverse exit also removed", "east" not in resp.lower() or "none" in resp.lower(), resp[:120])

    # 2. delete nonexistent direction
    resp = await send_and_recv(ws, "delete direction south")
    _record(group, "delete nonexistent direction", "no exit" in resp.lower(), resp[:120])

    # 3. delete room — move out first
    await send_and_recv(ws, "teleport hall")
    resp = await send_and_recv(ws, "delete room TempRoom")
    _record(group, "delete room", "Room 'TempRoom' deleted" in resp, resp[:150])

    # 4. Can't delete spawn room
    resp = await send_and_recv(ws, "delete room hall")
    _record(group, "can't delete spawn room", "can't delete" in resp.lower() or "spawn" in resp.lower(), resp[:120])

    # 5. Delete nonexistent room
    resp = await send_and_recv(ws, "delete room TempRoom")
    _record(group, "delete nonexistent room", "no room" in resp.lower(), resp[:120])

    # 6. Delete occupied room — create, put user2 in it, try to delete
    await send_and_recv(ws, "create room OccupiedRoom")
    await send_and_recv(ws, "create direction west OccupiedRoom")

    ws2, _ = await login(USER_NAME, USER_PW)
    await send_and_recv(ws2, "go west")
    await recv_all(ws, timeout=0.3)  # drain broadcasts

    resp = await send_and_recv(ws, "delete room OccupiedRoom")
    _record(group, "delete occupied room rejected", "occupied" in resp.lower(), resp[:150])

    # Clean up — move user2 back, delete the room
    await send_and_recv(ws2, "east")
    await recv_all(ws, timeout=0.3)
    await ws2.close()
    await recv_all(ws, timeout=0.5)  # drain "left the game"
    resp = await send_and_recv(ws, "delete room OccupiedRoom")
    _record(group, "delete room after vacated", "deleted" in resp.lower(), resp[:150])

    await ws.close()


async def test_non_admin():
    group = "Non-admin restrictions"
    ws, _ = await login(USER_NAME, USER_PW)

    for cmd_name, cmd in [
        ("teleport",          "teleport library"),
        ("list",              "list"),
        ("list rooms",        "list rooms"),
        ("create room",       "create room Forbidden"),
        ("create direction",  "create direction north library"),
        ("describe",          "describe Something"),
        ("delete direction",  "delete direction north"),
        ("delete room",       "delete room library"),
        ("sysinfo",           "sysinfo"),
    ]:
        resp = await send_and_recv(ws, cmd)
        _record(group, f"{cmd_name} rejected", "not allowed" in resp.lower(), resp[:120])

    # help should NOT show admin commands
    resp = await send_and_recv(ws, "help")
    _record(group, "help hides admin commands", "admin" not in resp.lower(), resp[:200])

    await ws.close()


async def test_admin_help():
    group = "Admin help"
    ws, _ = await login(ADMIN_NAME, ADMIN_PW)

    resp = await send_and_recv(ws, "help")
    _record(group, "help shows admin section", "Admin commands" in resp, resp[:120])

    for kw in ["teleport", "describe", "create room", "delete room", "list rooms", "sysinfo"]:
        _record(group, f"help mentions '{kw}'", kw in resp, "")

    await ws.close()


async def test_sysinfo():
    group = "Sysinfo"
    ws, _ = await login(ADMIN_NAME, ADMIN_PW)

    resp = await send_and_recv(ws, "sysinfo")
    _record(group, "sysinfo returns output", len(resp) > 50, f"length={len(resp)}")
    _record(group, "sysinfo has platform", "platform" in resp.lower(), resp[:120])
    _record(group, "sysinfo has version", "version" in resp.lower(), resp[:120])
    _record(group, "sysinfo has RAM section", "ram" in resp.lower(), resp[:200])
    _record(group, "sysinfo has storage section", "storage" in resp.lower(), resp[:200])

    await ws.close()


async def test_say_length():
    group = "Input limits"
    ws, _ = await login(ADMIN_NAME, ADMIN_PW)

    # Say too long
    resp = await send_and_recv(ws, "say " + "x" * 450)
    _record(group, "say too long rejected", "too long" in resp.lower(), resp[:120])

    # Global input cap
    resp = await send_and_recv(ws, "x" * 1100)
    _record(group, "global input cap", "too long" in resp.lower(), resp[:120])

    await ws.close()


async def test_persistence():
    """Verify rooms.json and known_players.json exist and are valid after tests."""
    group = "Persistence"
    store = os.path.join(SERVER_DIR, "usr_store")

    rooms_path = os.path.join(store, "rooms.json")
    ok = os.path.isfile(rooms_path)
    _record(group, "rooms.json exists", ok, rooms_path)

    if ok:
        with open(rooms_path, encoding='utf-8') as f:
            data = json.load(f)
        _record(group, "rooms.json is valid JSON", isinstance(data, dict), f"{len(data)} rooms")
        # Check indentation (pretty-printed)
        raw = open(rooms_path, encoding='utf-8').read()
        _record(group, "rooms.json is pretty-printed", "\n  " in raw, "")

    players_path = os.path.join(store, "known_players.json")
    ok = os.path.isfile(players_path)
    _record(group, "known_players.json exists", ok, players_path)

    if ok:
        with open(players_path, encoding='utf-8') as f:
            data = json.load(f)
        _record(group, "known_players.json is valid JSON", isinstance(data, dict), f"{len(data)} players")
        _record(group, "admin account persisted", any(k.lower() == ADMIN_NAME.lower() for k in data), "")
        _record(group, "user account persisted", any(k.lower() == USER_NAME.lower() for k in data), "")
        # Check password hashes exist
        for uname in [ADMIN_NAME, USER_NAME]:
            key = next((k for k in data if k.lower() == uname.lower()), None)
            if key:
                rec = data[key]
                _record(group, f"{uname} has pw_hash", "pw_hash" in rec and "salt" in rec, "")

    # No stale .tmp files
    if os.path.isdir(store):
        tmps = [f for f in os.listdir(store) if f.endswith('.tmp')]
        _record(group, "no stale .tmp files", len(tmps) == 0, str(tmps))


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------
SERVER_DIR = ""  # set at runtime

def prepare_server(source_dir):
    """Copy server files to a temp directory, patch ADMINS, return the path."""
    global SERVER_DIR
    SERVER_DIR = tempfile.mkdtemp(prefix="mud_test_")
    # Copy source files
    for item in REQUIRED_FILES:
        src = os.path.join(source_dir, item)
        dst = os.path.join(SERVER_DIR, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    # Patch ADMINS and PORT in mud.py
    mud_path = os.path.join(SERVER_DIR, "mud.py")
    with open(mud_path, encoding='utf-8') as f:
        code = f.read()
    code = code.replace("ADMINS = set()", f"ADMINS = {{'{ADMIN_NAME}'}}")
    code = code.replace("PORT = 5000", f"PORT = {PORT}")
    with open(mud_path, "w", encoding='utf-8') as f:
        f.write(code)

    return SERVER_DIR


def start_server(server_dir):
    """Start the MUD server as a subprocess, return the Popen handle."""
    proc = subprocess.Popen(
        [sys.executable, "mud.py"],
        cwd=server_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # Wait for the server to be ready by polling the port.
    deadline = time.time() + STARTUP_TIMEOUT
    import socket
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=0.3)
            s.close()
            return proc
        except (ConnectionRefusedError, OSError):
            time.sleep(0.2)
            # Check if the process died.
            if proc.poll() is not None:
                out = proc.stdout.read()
                raise RuntimeError(f"Server exited early (code {proc.returncode}):\n{out}")
    out = proc.stdout.read()
    proc.kill()
    raise RuntimeError(f"Server did not start within {STARTUP_TIMEOUT}s:\n{out}")


def stop_server(proc):
    """Terminate the server."""
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def run_all_tests():
    test_groups = [
        ("Auth",               test_auth),
        ("Navigation",         test_navigation),
        ("Communication",      test_communication),
        ("Wiki",               test_wiki),
        ("Admin building",     test_admin_building),
        ("Admin deletion",     test_admin_deletion),
        ("Non-admin",          test_non_admin),
        ("Admin help",         test_admin_help),
        ("Sysinfo",            test_sysinfo),
        ("Input limits",       test_say_length),
        ("Persistence",        test_persistence),
    ]
    for group_name, test_fn in test_groups:
        print(f"\n{BOLD}▶ {group_name}{RESET}")
        try:
            await test_fn()
        except Exception as e:
            _record(group_name, "UNEXPECTED EXCEPTION", False, f"{type(e).__name__}: {e}")
            traceback.print_exc()


def main():
    # Determine source directory.
    if len(sys.argv) > 1:
        source_dir = sys.argv[1]
    else:
        source_dir = os.path.dirname(os.path.abspath(__file__))

    # Verify source has what we need.
    for needed in REQUIRED_FILES:
        if not os.path.exists(os.path.join(source_dir, needed)):
            print(f"{RED}ERROR:{RESET} '{needed}' not found in {source_dir}")
            print("Run this script from the v0.3 directory, or pass its path as an argument.")
            sys.exit(1)

    print(f"{BOLD}E32Mud Integration Tests{RESET}")
    print(f"Source: {source_dir}")

    server_dir = prepare_server(source_dir)
    print(f"Server dir: {server_dir}")
    print(f"Port: {PORT}")

    proc = None
    try:
        print(f"\nStarting server...")
        proc = start_server(server_dir)
        print(f"Server running (PID {proc.pid})")

        asyncio.run(run_all_tests())

    except RuntimeError as e:
        print(f"\n{RED}Server failed to start:{RESET} {e}")
        sys.exit(1)
    finally:
        print(f"\nStopping server...")
        stop_server(proc)
        # Optionally clean up (comment out to inspect files after a failure).
        shutil.rmtree(server_dir, ignore_errors=True)

    all_ok = summary()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()