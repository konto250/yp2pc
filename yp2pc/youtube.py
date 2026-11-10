"""yt-dlpによるメタデータ取得。音声ファイルは保存しません。"""

import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from yp2pc.core import AppError, VIDEO_ID, max_episodes, playlist_id, video_id


class MetadataCache:
    def __init__(self, capacity=128):
        self.items = OrderedDict()
        self.lock = threading.Lock()
        self.capacity = capacity

    def get(self, key):
        with self.lock:
            entry = self.items.get(key)
            if entry and entry[0] > time.monotonic():
                self.items.move_to_end(key)
                return entry[1]
            self.items.pop(key, None)
        return None

    def put(self, key, value, ttl):
        with self.lock:
            self.items[key] = (time.monotonic() + ttl, value)
            self.items.move_to_end(key)
            while len(self.items) > self.capacity:
                self.items.popitem(last=False)

    def remove(self, key):
        with self.lock:
            self.items.pop(key, None)


cache = MetadataCache()
# 同一インスタンス上で起動する外部プロセス数を制限します。
extract_slots = threading.BoundedSemaphore(3)


def command_prefix():
    executable = os.environ.get("YTDLP_BIN")
    if executable:
        return [executable]
    if importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    executable = shutil.which("yt-dlp")
    if executable:
        return [executable]
    raise AppError("音声取得ツールが未導入です。requirements.txtをインストールしてください。", 503, "configuration_error")


def extract(url, extra, timeout=40):
    args = command_prefix() + [
        "--ignore-config", "--no-update", "--no-cache-dir", "--skip-download",
        "--dump-single-json", "--socket-timeout", "10", "--retries", "0",
        "--extractor-retries", "0", "--no-warnings", "--extractor-args", "youtube:lang=ja"
    ]
    bundled_deno = Path(__file__).resolve().parents[1] / "vendor" / "deno"
    if bundled_deno.is_file():
        args += ["--js-runtimes", "deno:" + str(bundled_deno)]
    elif importlib.util.find_spec("deno"):
        import deno
        args += ["--js-runtimes", "deno:" + str(deno.find_deno_bin())]
    elif shutil.which("node"):
        args += ["--js-runtimes", "node"]
    if not extract_slots.acquire(timeout=10):
        raise AppError("処理が混み合っています。少し待って再試行してください。", 503, "busy")
    try:
        result = subprocess.run(args + extra + ["--", url], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout,
                                env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path),
                                     "DENO_DIR": os.path.join(os.environ.get("TMPDIR", os.environ.get("TEMP", "/tmp")), "yp2pc-deno")})
    except subprocess.TimeoutExpired:
        raise AppError("YouTubeからの取得がタイムアウトしました。時間をおいて再試行してください。", 504, "youtube_timeout") from None
    except OSError:
        raise AppError("音声取得ツールを起動できませんでした。サーバー設定を確認してください。", 503, "configuration_error") from None
    finally:
        extract_slots.release()
    if result.returncode:
        error = result.stderr.lower()
        # 原因調査用に内部ログを残します。署名付きURLは必ず伏せます。
        safe_error = re.sub(r"https?://\S+", "[URL]", result.stderr)
        logging.warning("yt-dlpの取得失敗: %s", safe_error[-1600:])
        if "no module named" in error or "unrecognized arguments" in error:
            logging.error("音声取得ツールの依存または引数が不正です。終了コード=%s", result.returncode)
            raise AppError("音声取得ツールの実行環境に問題があります。サーバー設定を確認してください。", 503, "configuration_error")
        if "confirm you" in error and "bot" in error:
            logging.warning("YouTubeによる自動アクセス制限を検出しました。")
            raise AppError("YouTubeがこのサーバーからの取得を自動アクセスとして制限しています。音声を取得できません。", 502, "youtube_blocked")
        if "private" in error or "does not exist" in error or "unavailable" in error:
            message = "公開されていない、削除済み、または取得できない動画・プレイリストです。"
        elif "requested format" in error:
            message = "この動画には取得可能なM4A音声がありません。"
        else:
            message = "YouTubeが取得を拒否しました。アクセス制限、年齢制限、または取得ツールの更新が必要な可能性があります。"
        # 署名付きURL、Cookieなどをクライアントへ返しません。
        raise AppError(message, 502, "youtube_unavailable")
    try:
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise AppError("YouTubeの応答を読み取れませんでした。", 502, "invalid_upstream") from None


def trusted_media_url(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".googlevideo.com")
                or parsed.username or parsed.password or parsed.port not in {None, 443}):
            raise ValueError
    except ValueError:
        raise AppError("音声配信先を確認できませんでした。", 502, "invalid_upstream") from None
    return url


class MediaRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        trusted_media_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_media(source, method="GET", byte_range=None):
    headers = {k: v for k, v in source.get("headers", {}).items()
               if k.lower() in {"user-agent", "referer", "origin", "accept", "accept-language"}}
    headers["Accept-Encoding"] = "identity"
    if byte_range:
        headers["Range"] = byte_range
    return build_opener(MediaRedirects()).open(
        Request(trusted_media_url(source["url"]), headers=headers, method=method), timeout=15)


def audio_source(identifier, refresh=False):
    identifier = video_id(identifier)
    key = "audio:" + identifier
    if not refresh:
        cached = cache.get(key)
        if cached:
            return cached
    info = extract("https://www.youtube.com/watch?v=" + identifier,
                   ["--no-playlist", "-f", "bestaudio[ext=m4a][protocol=https]"], timeout=35)
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
        raise AppError("ライブ配信中・処理中の動画には対応していません。", 422, "live_video")
    if info.get("ext") != "m4a" or not info.get("url"):
        raise AppError("対応するM4A音声が見つかりませんでした。", 422, "unsupported_audio")
    url = trusted_media_url(info["url"])
    source = {"id": identifier, "url": url, "headers": info.get("http_headers", {}),
              "title": info.get("title") or identifier, "description": info.get("description", ""),
              "duration": info.get("duration"), "published": info.get("release_timestamp") or info.get("timestamp")}
    if not source["published"] and info.get("upload_date"):
        try:
            source["published"] = datetime.strptime(info["upload_date"], "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    size = info.get("filesize")
    if not isinstance(size, int) or size <= 0:
        try:
            with open_media(source, "GET", "bytes=0-0") as response:
                if response.status == 206:
                    size = int(response.headers.get("Content-Range", "").rsplit("/", 1)[-1])
                else:
                    size = int(response.headers.get("Content-Length", "0"))
        except (HTTPError, URLError, ValueError, TimeoutError):
            raise AppError("音声のファイルサイズを取得できませんでした。", 502, "audio_unavailable") from None
    if size <= 0:
        raise AppError("音声のファイルサイズを確認できませんでした。", 502, "audio_unavailable")
    source["size"] = size
    try:
        expiry = int(parse_qs(urlsplit(url).query).get("expire", ["0"])[0])
        ttl = max(0, min(600, expiry - time.time() - 60)) if expiry else 120
    except ValueError:
        ttl = 120
    cache.put(key, source, ttl)
    return source


def build_feed(identifier):
    identifier = playlist_id(identifier)
    limit = max_episodes()
    key = f"feed:{identifier}:{limit}"
    saved = cache.get(key)
    if saved:
        return saved
    info = extract("https://www.youtube.com/playlist?list=" + identifier,
                   ["--flat-playlist", "--playlist-end", str(limit)])
    entries = info.get("entries") or []
    ids = list(dict.fromkeys(e.get("id") for e in entries if e and VIDEO_ID.fullmatch(e.get("id") or "")))[:limit]
    if not ids:
        raise AppError("取得可能な動画がありません。公開プレイリストか確認してください。", 422, "empty_playlist")

    def resolve(identifier):
        try:
            source = audio_source(identifier)
            # 一時音声URLをRSS・ブラウザへ露出させません。
            return {k: v for k, v in source.items() if k not in {"url", "headers"}}, None
        except AppError as error:
            return None, {"id": identifier, "message": str(error)}

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(resolve, ids))
    episodes = [episode for episode, _ in results if episode]
    issues = [issue for _, issue in results if issue]
    if not episodes:
        raise AppError("再生用の音声を取得できませんでした。" + issues[0]["message"], 502, "no_playable_episodes")
    feed = {"id": identifier, "title": info.get("title") or identifier,
            "description": info.get("description") or "", "author": info.get("uploader") or info.get("channel") or "YouTube",
            "episodes": episodes, "issues": issues, "scannedCount": len(ids),
            "totalCount": info.get("playlist_count"), "limit": limit}
    cache.put(key, feed, 300)
    return feed
