"""管理画面用のパスワード検証と、期限付きのサーバー側セッション。"""

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import OrderedDict, deque
from http.cookies import SimpleCookie, CookieError

from yp2pc.core import AppError

COOKIE = "yp2pc_session"
LIFETIME = 12 * 60 * 60
sessions = OrderedDict()
attempts = deque()
lock = threading.Lock()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
    return "scrypt:" + salt + ":" + digest.hex()


def configured_hash():
    value = os.environ.get("ADMIN_PASSWORD_HASH", "")
    try:
        algorithm, salt, digest = value.split(":")
        if algorithm != "scrypt" or len(bytes.fromhex(salt)) != 16 or len(bytes.fromhex(digest)) != 32:
            raise ValueError
    except ValueError:
        raise AppError("管理パスワードが未設定です。ADMIN_PASSWORD_HASHを設定してください。", 503, "auth_unconfigured") from None
    return value


def verify_password(password):
    expected = configured_hash()
    if not isinstance(password, str) or not password or len(password.encode("utf-8")) > 1024:
        return False
    with lock:
        now = time.monotonic()
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= 10:
            raise AppError("ログインの試行が多すぎます。1分ほど待って再試行してください。", 429, "login_rate_limited")
        attempts.append(now)
    return hmac.compare_digest(password_hash(password, expected.split(":")[1]), expected)


def create_session():
    fingerprint = configured_hash()
    token = secrets.token_urlsafe(32)
    with lock:
        sessions[hashlib.sha256(token.encode()).hexdigest()] = (time.time() + LIFETIME, fingerprint)
        while len(sessions) > 128:
            sessions.popitem(last=False)
    return token


def session_key(header):
    try:
        cookie = SimpleCookie()
        cookie.load(header or "")
        token = cookie[COOKIE].value
        if len(token) != 43:
            return None
        return hashlib.sha256(token.encode()).hexdigest()
    except (CookieError, KeyError):
        return None


def authenticated(header):
    key = session_key(header)
    with lock:
        entry = sessions.get(key)
        if entry and entry[0] > time.time() and entry[1] == os.environ.get("ADMIN_PASSWORD_HASH"):
            return True
        sessions.pop(key, None)
    return False


def revoke(header):
    with lock:
        sessions.pop(session_key(header), None)


def cookie_header(token, secure):
    return (f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={LIFETIME if token else 0}"
            + ("; Secure" if secure else ""))
