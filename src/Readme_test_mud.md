
# Tests

The test suite covers **75 checks** across 10 groups, all passing. Here's what it exercises:

**Auth (9 tests)** — register admin, register user, correct login, wrong password, case-insensitive name lookup, name too long, empty name, double login rejected, no duplicate registration via casing.

**Navigation (5)** — `look`, `go north`, bare direction shortcut (`south`), invalid direction, unknown command.

**Communication (6)** — `say` echoed to sender, `say` received by another player in room, `who` lists both players, departure broadcast on movement, `say` does *not* leak across rooms, logout broadcast on disconnect.

**Wiki (5)** — `read` empty room, `write` a note, `read` it back, admin `list` shows rooms with notes, note too long rejected.

**Admin building (15)** — `create room`, duplicate room rejected (case-insensitive), reserved title rejected, title too long, `create direction` with auto-reverse verified, `teleport` + `look` to confirm reverse exit exists, reserved direction name rejected, duplicate direction rejected, `describe` + verify persistence, description too long, `list rooms`, teleport-already-there, teleport-nonexistent.

**Admin deletion (8)** — `delete direction` + reverse also removed, delete nonexistent direction, `delete room`, can't delete spawn, delete nonexistent, delete occupied room rejected, delete after vacated.

**Non-admin restrictions (9)** — all 8 admin commands individually rejected for a non-admin user, plus `help` hides the admin section.

**Admin help (6)** — admin section present, each key command mentioned.

**Input limits (2)** — `say` too long, global input cap.

**Persistence (10)** — both JSON files exist, are valid, are pretty-printed, both accounts persisted with password hashes, no stale `.tmp` files left behind.

**How to run it yourself:**

```bash
python test_mud.py /path/to/mudfiles
```

It copies the server files to a temp directory, patches `ADMINS` and `PORT` so it doesn't collide with a running dev server, starts the server as a subprocess, runs all tests, stops the server, cleans up the temp directory, and exits with code 0 on success or 1 on any failure.