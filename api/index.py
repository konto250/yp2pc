"""セルフホスト用のRSS・保存済み音声・画像配信ハンドラー。"""

import hashlib
import json
import logging
import re
import traceback
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

from yp2pc.core import AppError, PLAYLIST_ID, base_url, playlist_id, rss_document, video_id
from yp2pc.youtube import build_feed
from yp2pc import storage, auth
from yp2pc.media import MEDIA_VERSION

PUBLIC = Path(__file__).resolve().parents[1] / "public"
RANGE = re.compile(r"bytes=(?:[0-9]{1,18}-[0-9]{0,18}|-[0-9]{1,18})\Z")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/login": ("login.html", "text/html; charset=utf-8"),
          "/login.js": ("login.js", "text/javascript; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"),
          "/favicon.svg": ("favicon.svg", "image/svg+xml"),
          "/cover.png": ("cover.png", "image/png")}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.dispatch()

    def do_HEAD(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def do_DELETE(self):
        self.dispatch()

    def do_OPTIONS(self):
        self.respond(405, b"", {"Allow": "GET, HEAD, POST"})

    def dispatch(self):
        self.started = False
        try:
            path = urlsplit(self.path).path
            if path == "/health" and self.command in {"GET", "HEAD"}:
                return self.json_response(200, {"status": "ok"})
            if path in STATIC and self.command in {"GET", "HEAD"}:
                logged_in = auth.authenticated(self.headers.get("Cookie"))
                if path == "/" and not logged_in:
                    return self.respond(302, b"", {"Location": "/login", "Cache-Control": "no-store"})
                if path == "/login" and logged_in:
                    return self.respond(302, b"", {"Location": "/", "Cache-Control": "no-store"})
                name, media_type = STATIC[path]
                return self.respond(200, (PUBLIC / name).read_bytes(), {"Content-Type": media_type, "Cache-Control": "private, no-store"})
            if path == "/api/login" and self.command == "POST":
                origin = self.check_origin()
                body = self.read_json()
                if not auth.verify_password(body.get("password")):
                    raise AppError("パスワードが正しくありません。", 401, "invalid_password")
                return self.json_response(200, {"ok": True}, {"Set-Cookie": auth.cookie_header(auth.create_session(), origin.startswith("https://"))})
            if path == "/api/logout" and self.command == "POST":
                origin = self.check_origin()
                auth.revoke(self.headers.get("Cookie"))
                return self.json_response(200, {"ok": True}, {"Set-Cookie": auth.cookie_header("", origin.startswith("https://"))})
            if path == "/api/feeds":
                self.require_admin()
                origin = base_url(self.headers.get("Host"))
                if self.command == "GET":
                    feeds = [{**feed, "feedUrl": origin + "/feed/" + feed["id"] + ".xml"} for feed in storage.list_feeds()]
                    return self.json_response(200, {"feeds": feeds})
                if self.command != "POST":
                    return self.respond(405, b"", {"Allow": "GET, POST"})
                self.check_origin()
                body = self.read_json()
                with storage.feed_operation:
                    feed = build_feed(playlist_id(body.get("url")))
                    storage.save_feed(feed)
                result = {**feed, "feedUrl": origin + "/feed/" + feed["id"] + ".xml",
                          "playlistUrl": "https://www.youtube.com/playlist?list=" + feed["id"],
                          "local": origin.startswith("http://")}
                result["episodes"] = [{**episode, "artworkUrl": origin + "/artwork/" + episode["id"] + ".jpg" if episode.get("artwork") else None}
                                      for episode in feed["episodes"]]
                return self.json_response(200, result)
            if path.startswith("/api/feeds/"):
                self.require_admin()
                if self.command != "DELETE":
                    return self.respond(405, b"", {"Allow": "DELETE"})
                self.check_origin()
                identifier = path[len("/api/feeds/"):]
                if not PLAYLIST_ID.fullmatch(identifier):
                    raise AppError("フィードが見つかりません。", 404, "not_found")
                body = self.read_json()
                remove_media = body.get("removeMedia", True)
                if not isinstance(remove_media, bool):
                    raise AppError("削除オプションが正しくありません。")
                return self.json_response(200, storage.delete_feed(identifier, remove_media))
            if path.startswith("/feed/") and path.endswith(".xml"):
                if self.command not in {"GET", "HEAD"}:
                    return self.respond(405, b"", {"Allow": "GET, HEAD"})
                identifier = path[len("/feed/"):-4]
                if not PLAYLIST_ID.fullmatch(identifier):
                    raise AppError("フィードが見つかりません。", 404, "not_found")
                with storage.feed_operation:
                    if not storage.registered(identifier):
                        raise AppError("未登録または削除済みのフィードです。", 404, "not_found")
                    content = rss_document(build_feed(identifier), base_url(self.headers.get("Host")))
                etag = '"' + hashlib.sha256(content).hexdigest() + '"'
                headers = {"Content-Type": "application/rss+xml; charset=utf-8", "ETag": etag,
                           "Cache-Control": "public, max-age=0, must-revalidate"}
                if self.headers.get("If-None-Match") == etag:
                    return self.respond(304, b"", headers)
                return self.respond(200, content, headers)
            if path.startswith("/audio/") and path.endswith(".m4a"):
                if self.command not in {"GET", "HEAD"}:
                    return self.respond(405, b"", {"Allow": "GET, HEAD"})
                return self.stream_audio(video_id(path[len("/audio/"):-4]))
            if path.startswith("/artwork/") and path.endswith(".jpg") and self.command in {"GET", "HEAD"}:
                identifier = video_id(path[len("/artwork/"):-4])
                return self.serve_file(storage.media_path(identifier, ".jpg"), "image/jpeg")
            raise AppError("ページが見つかりません。", 404, "not_found")
        except AppError as error:
            if not self.started:
                self.json_response(error.status, {"error": str(error), "code": error.code})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
        except Exception as error:
            logging.error("リクエスト処理に失敗しました: %s\n%s", type(error).__name__,
                          "".join(traceback.format_tb(error.__traceback__)))
            if not self.started:
                self.json_response(500, {"error": "処理に失敗しました。時間をおいて再試行してください。", "code": "internal_error"})
            self.close_connection = True

    def require_admin(self):
        if not auth.authenticated(self.headers.get("Cookie")):
            raise AppError("ログインが必要です。", 401, "login_required")

    def check_origin(self):
        origin = base_url(self.headers.get("Host"))
        supplied = self.headers.get("Origin")
        if supplied and supplied != origin and supplied != "http://" + (self.headers.get("Host") or ""):
            raise AppError("この画面から再試行してください。", 403, "invalid_origin")
        return origin

    def read_json(self):
        if self.headers.get_content_type() != "application/json":
            raise AppError("JSON形式で送信してください。", 415)
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise AppError("リクエストサイズが正しくありません。") from None
        if size <= 0 or size > 4096:
            raise AppError("リクエストが大きすぎるか空です。", 413)
        try:
            body = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeError):
            raise AppError("入力を読み取れませんでした。") from None
        if not isinstance(body, dict):
            raise AppError("入力形式が正しくありません。")
        return body

    def respond(self, status, content, headers=None):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        if status != 304:
            self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.started = True
        if self.command != "HEAD" and status != 304:
            self.wfile.write(content)

    def json_response(self, status, value, headers=None):
        return self.respond(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                            {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", **(headers or {})})

    def stream_audio(self, identifier):
        saved = storage.read_episode(identifier)
        if not saved:
            raise AppError("保存済み音声が見つかりません。", 404, "not_found")
        if saved.get("media_version") != MEDIA_VERSION:
            saved = storage.prepare_episode(identifier)
        return self.serve_file(storage.media_path(identifier), "audio/x-m4a", saved["sha256"])

    def serve_file(self, path, media_type, digest=None):
        try:
            source = path.open("rb")
        except FileNotFoundError:
            raise AppError("保存ファイルが見つかりません。", 404, "not_found") from None
        with source:
            stat = path.stat()
            size = stat.st_size
            etag = '"' + (digest or f"{stat.st_mtime_ns:x}-{size:x}") + '"'
            modified = formatdate(stat.st_mtime, usegmt=True)
            headers = {"Content-Type": media_type, "Accept-Ranges": "bytes", "ETag": etag,
                       "Last-Modified": modified, "Cache-Control": "public, max-age=3600"}
            if self.headers.get("If-None-Match") == etag:
                return self.respond(304, b"", headers)
            byte_range = self.headers.get("Range")
            if self.headers.get("If-Range") not in {None, etag, modified}:
                byte_range = None
            start, end = 0, size - 1
            if byte_range:
                try:
                    if not RANGE.fullmatch(byte_range):
                        raise ValueError
                    first, last = byte_range[6:].split("-")
                    if first:
                        start = int(first)
                        end = min(int(last), end) if last else end
                    elif int(last) > 0:
                        start = max(0, size - int(last))
                    else:
                        raise ValueError
                    if start > end or start >= size:
                        raise ValueError
                except ValueError:
                    return self.respond(416, b"", {**headers, "Content-Range": f"bytes */{size}"})
                headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            remaining = end - start + 1
            self.send_response(206 if byte_range else 200)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(remaining))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.started = True
            if self.command == "HEAD":
                return
            source.seek(start)
            while remaining > 0:
                chunk = source.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def log_message(self, format, *args):
        # URLのクエリーや署名付き配信URLをログに残しません。
        pass
