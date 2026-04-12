"""
Persistence utilities for E32Mud.
Atomic JSON writes, safe loading with corruption recovery, filesystem helpers.
"""
import json
import os
import sys


# Platform-aware file existence check.
if 'esp' in sys.platform:
    def isfile(path):
        try:
            return (os.stat(path)[0] & 0x4000) == 0
        except OSError:
            return False
else:
    def isfile(path):
        return os.path.exists(path)


def ensure_store(store_dir):
    """Create the store directory if it doesn't already exist."""
    try:
        os.mkdir(store_dir)
        print("Created store directory:", store_dir)
    except OSError:
        pass  # Already exists (both CPython and MicroPython raise OSError)


def store_path(store_dir, filename):
    return store_dir + '/' + filename


def atomic_write_json(path, obj):
    """Write JSON via a temp file + rename to guard against power-loss corruption."""
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(obj, f, indent=2)
    try:
        os.remove(path)
    except OSError:
        pass
    os.rename(tmp, path)


def load_json(path, what):
    """Load a JSON file. Returns the parsed object, or None on missing/corrupt.

    On corruption the bad file is backed up to <path>.corrupt.
    If a .tmp file survives from a crashed atomic_write_json, it is recovered.
    """
    if isfile(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            backup = path + '.corrupt'
            print("WARNING:", what, "at", path, "is corrupt:", e, "- backing up to", backup)
            try:
                try:
                    os.remove(backup)
                except OSError:
                    pass
                os.rename(path, backup)
            except OSError as move_err:
                print("  (could not back it up:", move_err, ")")
    # Crash recovery: a .tmp may have survived a power cut between
    # the remove(target) and the rename(tmp -> target).
    tmp = path + '.tmp'
    if isfile(tmp):
        try:
            with open(tmp) as f:
                data = json.load(f)
            print("Recovered", what, "from", tmp)
            return data
        except Exception:
            pass
    return None


def safe_wiki_filename(store_dir, room_key):
    """Return the wiki-notes path for a room, with the key sanitised for the filesystem."""
    sanitized = "".join(c if (c.isalnum() or c == '_') else '_' for c in room_key)
    return store_path(store_dir, "wiki_" + sanitized + ".txt")
