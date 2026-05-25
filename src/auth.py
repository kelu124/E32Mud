"""
Authentication helpers for E32Mud.
Password hashing (sha256 + salt) and auth-state constants.
"""
import hashlib
import binascii
import os
import time


class AuthState:
    """Named constants for the per-connection authentication state machine."""
    AWAIT_NAME     = 'await_name'
    AWAIT_LOGIN_PW = 'await_login_pw'
    AWAIT_NEW_PW   = 'await_new_pw'
    AUTHENTICATED  = 'authenticated'


def gen_salt():
    try:
        return binascii.hexlify(os.urandom(8)).decode()
    except Exception:
        # Poor fallback if os.urandom is unavailable
        return binascii.hexlify(str(time.time()).encode()).decode()[:16]


def hash_pw(password, salt):
    h = hashlib.sha256((salt + password).encode())
    return binascii.hexlify(h.digest()).decode()


def set_password(record, password):
    """Set a new password on a player record (mutates in place)."""
    salt = gen_salt()
    record['salt'] = salt
    record['pw_hash'] = hash_pw(password, salt)


def check_password(record, password):
    """Return True if `password` matches the hash stored in `record`."""
    salt = record.get('salt')
    pw_hash = record.get('pw_hash')
    if not salt or not pw_hash:
        return False
    return hash_pw(password, salt) == pw_hash
