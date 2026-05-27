# E32Mud — Test Suite

The integration test suite covers **75 checks** across 10 groups, all passing. It lives in `src/test_mud.py`.

## How to run

```bash
cd src
pip install websockets
python test_mud.py
```

Or pass the source directory explicitly:

```bash
python test_mud.py /path/to/src
```

The runner copies the server files to a temporary directory, patches `ADMINS` and `PORT` so it doesn't collide with a running dev server, starts the server as a subprocess on port 5111, runs all tests, stops the server, cleans up the temp directory, and exits with code 0 on success or 1 on any failure.

---

## Test groups

**Auth (9 tests)** — register admin, register user, correct login, wrong password, case-insensitive name lookup, name too long, empty name, double login rejected, no duplicate registration via casing.

**Navigation (5 tests)** — `look`, `go north`, bare direction shortcut (`south`), invalid direction, unknown command.

**Communication (6 tests)** — `say` echoed to sender, `say` received by another player in room, `who` lists both players, departure broadcast on movement, `say` does not leak across rooms, logout broadcast on disconnect.

**Wiki (5 tests)** — `read` empty room, `write` a note, `read` it back, admin `list` shows rooms with notes, note too long rejected.

**Admin building (15 tests)** — `create room`, duplicate room rejected (case-insensitive), reserved title rejected, title too long, `create direction` with auto-reverse verified, `teleport` + `look` to confirm reverse exit exists, reserved direction name rejected, duplicate direction rejected, `describe` + verify persistence, description too long, `list rooms`, teleport-already-there, teleport-nonexistent.

**Admin deletion (8 tests)** — `delete direction` + reverse also removed, delete nonexistent direction, `delete room`, can't delete spawn room, delete nonexistent, delete occupied room rejected, delete after vacated.

**Non-admin restrictions (10 tests)** — all 9 admin commands individually rejected for a non-admin user, plus `help` hides the admin section.

**Admin help (6 tests)** — admin section present in `help` output, each key command mentioned.

**Input limits (2 tests)** — `say` too long, global input cap.

**Persistence (10 tests)** — both JSON files exist, are valid, are pretty-printed, both accounts persisted with password hashes, no stale `.tmp` files left behind.

---

## What the tests verify

- **Auth state machine**: new registration, login, double-login rejection, case-insensitive name matching, length limits.
- **World navigation**: movement between rooms via `go`, bare direction shortcuts, invalid directions, unknown commands.
- **Room-scoped chat**: `say` reaches players in the same room only; movement generates arrival/departure broadcasts; logout is announced.
- **Wiki system**: per-room notes are written, read back, and size-capped.
- **Admin world-building**: rooms and exits can be created and destroyed; auto-reverse exits are created and cleaned up; guards prevent reserved names, duplicates, and deleting occupied or spawn rooms.
- **Permission gating**: every admin command is individually rejected for non-admin players.
- **Crash-safe persistence**: JSON files survive the test run, are valid, pretty-printed, contain hashed passwords, and leave no `.tmp` artefacts.
