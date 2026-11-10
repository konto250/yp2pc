"""セルフホスト用の音声・画像保存。完成ファイルだけを公開します。"""

import hashlib
import io
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from yp2pc.core import AppError, playlist_id, video_id

_download_lock = threading.Lock()


def root():
    directory = Path(os.environ.get("MEDIA_DIR") or Path(__file__).resolve().parents[1] / ".local" / "media")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def media_path(identifier, suffix=".m4a"):
    if suffix not in {".m4a", ".jpg", ".json"}:
        raise ValueError("保存形式が正しくありません。")
    return root() / (video_id(identifier) + suffix)


def read_episode(identifier):
    try:
        metadata = json.loads(media_path(identifier, ".json").read_text(encoding="utf-8"))
        if (metadata["id"] != identifier or metadata["size"] <= 0
                or media_path(identifier).stat().st_size != metadata["size"]):
            return None
        metadata["artwork"] = media_path(identifier, ".jpg").is_file()
        return metadata
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_json(path, value):
    temporary = path.with_suffix(".json.part")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def check_space(size):
    try:
        limit = int(os.environ.get("MEDIA_MAX_BYTES", str(5 * 1024 ** 3)))
    except ValueError:
        raise AppError("MEDIA_MAX_BYTESには保存容量をバイト数で指定してください。", 503, "configuration_error") from None
    used = sum(path.stat().st_size for path in root().iterdir() if path.is_file())
    if size <= 0 or size > 1024 ** 3:
        raise AppError("1件の保存上限は1GiBです。", 422, "media_too_large")
    if used + size + 8 * 1024 ** 2 > limit or shutil.disk_usage(root()).free < size + 100 * 1024 ** 2:
        raise AppError("音声の保存容量が不足しています。保存先とMEDIA_MAX_BYTESを確認してください。", 507, "storage_full")


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def save_artwork(identifier):
    """動画IDから固定のYouTube画像URLを構成し、余白付きの正方形にします。"""
    from PIL import Image, ImageOps

    identifier = video_id(identifier)
    target = media_path(identifier, ".jpg")
    if target.is_file():
        return True
    temporary = target.with_suffix(".jpg.part")
    try:
        for name in ("maxresdefault", "hqdefault"):
            try:
                request = Request(f"https://i.ytimg.com/vi/{identifier}/{name}.jpg", headers={"User-Agent": "YP2PC/1.0"})
                with build_opener(NoRedirects()).open(request, timeout=10) as response:
                    raw = response.read(8 * 1024 ** 2 + 1)
                if len(raw) > 8 * 1024 ** 2:
                    continue
                with Image.open(io.BytesIO(raw)) as source:
                    if source.width < 120 or source.height < 90 or source.width * source.height > 20_000_000:
                        continue
                    fitted = ImageOps.contain(source.convert("RGB"), (1400, 1400))
                    image = Image.new("RGB", (1400, 1400), (24, 24, 28))
                    image.paste(fitted, ((1400 - fitted.width) // 2, (1400 - fitted.height) // 2))
                    image.save(temporary, format="JPEG", quality=92)
                temporary.replace(target)
                return True
            except (HTTPError, URLError, OSError, ValueError, TimeoutError):
                continue
        return False
    finally:
        temporary.unlink(missing_ok=True)


def download_audio(source, temporary, open_media):
    # YouTubeは全体GETを拒否することがあるため、上限付きのRangeで保存します。
    digest = hashlib.sha256()
    written = 0
    size = source["size"]
    deadline = time.monotonic() + 240
    with temporary.open("wb") as output:
        while written < size:
            end = min(written + 1024 * 1024, size) - 1
            expected = end - written + 1
            with open_media(source, "GET", f"bytes={written}-{end}") as upstream:
                if (upstream.status != 206
                        or upstream.headers.get("Content-Range") != f"bytes {written}-{end}/{size}"):
                    raise AppError("音声の取得範囲を確認できませんでした。", 502, "invalid_range_response")
                received = 0
                while True:
                    chunk = upstream.read(256 * 1024)
                    if not chunk:
                        break
                    if written == 0 and b"ftyp" not in chunk[:32]:
                        raise AppError("取得したデータがM4A音声ではありません。", 502, "invalid_audio")
                    received += len(chunk)
                    if received > expected or time.monotonic() > deadline:
                        raise AppError("音声の保存が上限を超えました。再試行してください。", 504, "download_failed")
                    output.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                if received != expected:
                    raise AppError("音声の取得が途中で終了しました。再試行してください。", 502, "download_incomplete")
    return digest


def prepare_episode(identifier):
    from yp2pc.youtube import audio_source, open_media

    identifier = video_id(identifier)
    saved = read_episode(identifier)
    if saved and saved.get("artwork"):
        return saved
    # 個人用の単一プロセスで、重複取得と保存容量の競合を防ぎます。
    with _download_lock:
        saved = read_episode(identifier)
        if not saved:
            target = media_path(identifier)
            temporary = target.with_suffix(".m4a.part")
            try:
                for attempt in range(2):
                    source = audio_source(identifier, refresh=attempt > 0)
                    check_space(source["size"])
                    try:
                        digest = download_audio(source, temporary, open_media)
                        break
                    except HTTPError as error:
                        status = error.code
                        error.close()
                        if attempt == 0 and status in {401, 403, 410}:
                            continue
                        raise AppError("音声を保存できませんでした。再試行してください。", 502, "download_failed") from None
                saved = {key: source.get(key) for key in ("id", "title", "description", "duration", "published", "size")}
                saved.update({"sha256": digest.hexdigest(), "stored": True})
                temporary.replace(target)
                write_json(media_path(identifier, ".json"), saved)
            except (URLError, TimeoutError, OSError) as error:
                logging.warning("音声保存に失敗しました: %s", type(error).__name__)
                raise AppError("音声を保存できませんでした。通信と保存先の空き容量を確認してください。", 502, "download_failed") from None
            finally:
                temporary.unlink(missing_ok=True)
        try:
            saved["artwork"] = save_artwork(identifier)
        except ImportError:
            logging.warning("サムネイル生成にはrequirements.txtのPillowが必要です。")
            saved["artwork"] = False
        return saved


def save_feed(feed):
    with _download_lock:
        write_json(root() / ("feed-" + playlist_id(feed["id"]) + ".json"), feed)


def load_feed(identifier):
    try:
        feed = json.loads((root() / ("feed-" + playlist_id(identifier) + ".json")).read_text(encoding="utf-8"))
        feed["episodes"] = [saved for episode in feed["episodes"] if (saved := read_episode(episode["id"]))]
        return feed if feed["episodes"] else None
    except (OSError, ValueError, KeyError, TypeError):
        return None
