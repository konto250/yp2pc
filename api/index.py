"""Vercel Python FunctionsとローカルHTTPサーバーの共通ハンドラー。"""

import hashlib
import json
import logging
import re
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from yp2pc.core import AppError, PLAYLIST_ID, base_url, playlist_id, rss_document, video_id
from yp2pc.youtube import audio_source, build_feed, open_media

PUBLIC = Path(__file__).resolve().parents[1] / "public"
RANGE = re.compile(r"bytes=(?:[0-9]{1,18}-[0-9]{0,18}|-[0-9]{1,18})\Z")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
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

    def do_OPTIONS(self):
        self.respond(405, b"", {"Allow": "GET, HEAD, POST"})

    def dispatch(self):
        self.started = False
        try:
            path = urlsplit(self.path).path
            if path in STATIC and self.command in {"GET", "HEAD"}:
                name, media_type = STATIC[path]
                return self.respond(200, (PUBLIC / name).read_bytes(), {"Content-Type": media_type})
            if path == "/api/feeds":
                if self.command != "POST":
                    return self.respond(405, b"", {"Allow": "POST"})
                origin = base_url(self.headers.get("Host"))
                supplied_origin = self.headers.get("Origin")
                if supplied_origin and supplied_origin != origin:
                    # プレビュー環境でも同じオリジンの画面からの操作は許可します。
                    if urlsplit(supplied_origin).netloc != self.headers.get("Host"):
                        raise AppError("この画面から再試行してください。", 403, "invalid_origin")
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
                feed = build_feed(playlist_id(body.get("url")))
                result = {**feed, "feedUrl": origin + "/feed/" + feed["id"] + ".xml",
                          "playlistUrl": "https://www.youtube.com/playlist?list=" + feed["id"],
                          "local": origin.startswith("http://")}
                return self.json_response(200, result)
            if path.startswith("/feed/") and path.endswith(".xml"):
                if self.command not in {"GET", "HEAD"}:
                    return self.respond(405, b"", {"Allow": "GET, HEAD"})
                identifier = path[len("/feed/"):-4]
                if not PLAYLIST_ID.fullmatch(identifier):
                    raise AppError("フィードが見つかりません。", 404, "not_found")
                content = rss_document(build_feed(identifier), base_url(self.headers.get("Host")))
                etag = '"' + hashlib.sha256(content).hexdigest() + '"'
                headers = {"Content-Type": "application/rss+xml; charset=utf-8", "ETag": etag,
                           "Cache-Control": "public, max-age=300, s-maxage=300"}
                if self.headers.get("If-None-Match") == etag:
                    return self.respond(304, b"", headers)
                return self.respond(200, content, headers)
            if path.startswith("/audio/") and path.endswith(".m4a"):
                if self.command not in {"GET", "HEAD"}:
                    return self.respond(405, b"", {"Allow": "GET, HEAD"})
                return self.stream_audio(video_id(path[len("/audio/"):-4]))
            raise AppError("ページが見つかりません。", 404, "not_found")
        except AppError as error:
            if not self.started:
                self.json_response(error.status, {"error": str(error), "code": error.code})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
        except Exception as error:
            logging.error("リクエスト処理に失敗しました: %s", type(error).__name__)
            if not self.started:
                self.json_response(500, {"error": "処理に失敗しました。時間をおいて再試行してください。", "code": "internal_error"})
            self.close_connection = True

    def respond(self, status, content, headers=None):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        if status != 304:
            self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.started = True
        if self.command != "HEAD" and status != 304:
            self.wfile.write(content)

    def json_response(self, status, value):
        return self.respond(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                            {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"})

    def stream_audio(self, identifier):
        byte_range = self.headers.get("Range")
        if byte_range and not RANGE.fullmatch(byte_range):
            raise AppError("単一のバイト範囲を指定してください。", 416, "invalid_range")
        deadline = time.monotonic() + 265
        for attempt in range(2):
            source = audio_source(identifier, refresh=attempt > 0)
            try:
                # YouTubeがHEADを拒否しても、GETの範囲確認からHEADを構成できます。
                probe_range = byte_range or ("bytes=0-0" if self.command == "HEAD" else None)
                upstream = open_media(source, "GET", probe_range)
                break
            except HTTPError as error:
                code = error.code
                content_range = error.headers.get("Content-Range")
                error.close()
                if code in {401, 403, 410} and attempt == 0:
                    continue
                if code == 416:
                    headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}
                    if content_range:
                        headers["Content-Range"] = content_range
                    return self.respond(416, b"", headers)
                raise AppError("YouTubeの音声を取得できませんでした。時間をおいて再試行してください。", 502, "audio_unavailable") from None
            except (URLError, TimeoutError):
                raise AppError("音声配信元への接続がタイムアウトしました。", 504, "audio_timeout") from None
        with upstream:
            if upstream.status not in {200, 206}:
                raise AppError("音声配信元の応答を確認できませんでした。", 502, "invalid_upstream")
            # 最初のデータを読めることを確かめてからレスポンスを開始します。
            chunk = upstream.read(64 * 1024) if self.command != "HEAD" else b""
            is_head_probe = self.command == "HEAD" and not byte_range and upstream.status == 206
            self.send_response(200 if is_head_probe else upstream.status)
            self.send_header("Content-Type", "audio/x-m4a")
            self.send_header("Content-Disposition", 'inline; filename="' + identifier + '.m4a"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name in ("Content-Length", "Content-Range", "ETag", "Last-Modified"):
                value = upstream.headers.get(name)
                if is_head_probe and name == "Content-Range":
                    continue
                if is_head_probe and name == "Content-Length":
                    value = upstream.headers.get("Content-Range", "").rsplit("/", 1)[-1]
                if value:
                    self.send_header(name, value)
            self.end_headers()
            self.started = True
            while chunk:
                self.wfile.write(chunk)
                self.wfile.flush()
                if time.monotonic() > deadline:
                    self.close_connection = True
                    return
                chunk = upstream.read(64 * 1024)

    def log_message(self, format, *args):
        # URLのクエリーや署名付き配信URLをログに残しません。
        pass
