"""セルフホスト用の音声・画像保存。完成ファイルだけを公開します。"""

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
from yp2pc.media import MEDIA_VERSION, normalize

_download_lock = threading.Lock()
feed_operation = threading.RLock()


def root():
    directory = Path(os.environ.get("MEDIA_DIR") or Path(__file__).resolve().parents[1] / ".local" / "media")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def media_path(identifier, suffix=".m4a"):
    if suffix not in {".m4a", ".jpg", ".json", ".am.m4a", ".am.json"}:
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


def read_am_episode(identifier):
    from yp2pc.radio import RADIO_VERSION
    original = read_episode(identifier)
    if not original:
        return None
    try:
        details = json.loads(media_path(identifier, ".am.json").read_text(encoding="utf-8"))
        if (details["source_sha256"] != original["sha256"] or details["radio_version"] != RADIO_VERSION
                or details["size"] <= 0 or media_path(identifier, ".am.m4a").stat().st_size != details["size"]):
            return None
        return {**original, **details}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def prepare_am_episode(identifier):
    from yp2pc.radio import convert
    with _download_lock:
        saved = read_am_episode(identifier)
        if saved:
            return saved
        original = read_episode(identifier)
        if not original:
            raise AppError("通常版の保存済み音声がありません。", 404, "not_found")
        target = media_path(identifier, ".am.m4a")
        temporary = target.with_suffix(".m4a.part")
        check_space(max(original["size"], int(original.get("duration", 0) * 7000)), copies=2)
        try:
            details = convert(media_path(identifier), temporary, original.get("duration"))
            details["source_sha256"] = original["sha256"]
            temporary.replace(target)
            write_json(media_path(identifier, ".am.json"), details)
            return {**original, **details}
        finally:
            temporary.unlink(missing_ok=True)


def prepare_am_feed(feed):
    """管理操作・定期更新で事前生成します。公開RSSへのアクセスでは生成しません。"""
    issues = []
    with feed_operation:
        for episode in feed["episodes"]:
            try:
                prepare_am_episode(episode["id"])
            except (AppError, OSError) as error:
                issues.append({"id": episode["id"], "message": "AM版の生成に失敗しました。通常版は利用できます。"})
                logging.warning("AM版生成失敗: %s", getattr(error, "code", type(error).__name__))
    return issues


def am_feed(feed):
    episodes = [saved for episode in feed["episodes"] if (saved := read_am_episode(episode["id"]))]
    if not episodes:
        raise AppError("AM版の音声を準備中です。管理画面でプレイリストを再登録してください。", 503, "am_not_ready")
    return {**feed, "episodes": episodes}


def check_space(size, copies=1):
    try:
        limit = int(os.environ.get("MEDIA_MAX_BYTES", str(5 * 1024 ** 3)))
    except ValueError:
        raise AppError("MEDIA_MAX_BYTESには保存容量をバイト数で指定してください。", 503, "configuration_error") from None
    used = sum(path.stat().st_size for path in root().iterdir() if path.is_file())
    if size <= 0 or size > 1024 ** 3:
        raise AppError("1件の保存上限は1GiBです。", 422, "media_too_large")
    if used + size * copies + 8 * 1024 ** 2 > limit or shutil.disk_usage(root()).free < size * copies + 100 * 1024 ** 2:
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
                    written += len(chunk)
                if received != expected:
                    raise AppError("音声の取得が途中で終了しました。再試行してください。", 502, "download_incomplete")


def prepare_episode(identifier):
    from yp2pc.youtube import audio_source, open_media

    identifier = video_id(identifier)
    saved = read_episode(identifier)
    if saved and saved.get("artwork") and saved.get("media_version") == MEDIA_VERSION:
        return saved
    # 個人用の単一プロセスで、重複取得と保存容量の競合を防ぎます。
    with _download_lock:
        saved = read_episode(identifier)
        if not saved:
            target = media_path(identifier)
            temporary = target.with_suffix(".m4a.part")
            normalized = target.with_suffix(".normalized.part")
            try:
                for attempt in range(2):
                    source = audio_source(identifier, refresh=attempt > 0)
                    check_space(source["size"], copies=2)
                    try:
                        download_audio(source, temporary, open_media)
                        break
                    except HTTPError as error:
                        status = error.code
                        error.close()
                        if attempt == 0 and status in {401, 403, 410}:
                            continue
                        raise AppError("音声を保存できませんでした。再試行してください。", 502, "download_failed") from None
                saved = {key: source.get(key) for key in ("id", "title", "description", "duration", "published", "size")}
                saved.update(normalize(temporary, normalized, source.get("duration")))
                normalized.replace(target)
                write_json(media_path(identifier, ".json"), saved)
            except (URLError, TimeoutError, OSError) as error:
                logging.warning("音声保存に失敗しました: %s", type(error).__name__)
                raise AppError("音声を保存できませんでした。通信と保存先の空き容量を確認してください。", 502, "download_failed") from None
            finally:
                temporary.unlink(missing_ok=True)
                normalized.unlink(missing_ok=True)
        elif saved.get("media_version") != MEDIA_VERSION:
            # 旧形式の保存音声も、YouTubeへ再接続せずに補正します。
            target = media_path(identifier)
            normalized = target.with_suffix(".normalized.part")
            check_space(saved["size"])
            try:
                details = normalize(target, normalized, saved.get("duration"))
                normalized.replace(target)
                saved.update(details)
                write_json(media_path(identifier, ".json"), saved)
            finally:
                normalized.unlink(missing_ok=True)
        try:
            saved["artwork"] = save_artwork(identifier)
        except ImportError:
            logging.warning("サムネイル生成にはrequirements.txtのPillowが必要です。")
            saved["artwork"] = False
        return saved


def save_feed(feed):
    with feed_operation:
        write_json(root() / ("feed-" + playlist_id(feed["id"]) + ".json"), feed)


def registered(identifier):
    return (root() / ("feed-" + playlist_id(identifier) + ".json")).is_file()


def list_feeds():
    feeds = []
    with feed_operation:
        for path in root().glob("feed-*.json"):
            try:
                feed = json.loads(path.read_text(encoding="utf-8"))
                if path.name != "feed-" + playlist_id(feed["id"]) + ".json":
                    continue
                feeds.append({"id": feed["id"], "title": feed["title"], "episodeCount": len(feed["episodes"]),
                              "updated": path.stat().st_mtime})
            except (OSError, ValueError, KeyError, TypeError, AppError):
                continue
    return sorted(feeds, key=lambda feed: feed["updated"], reverse=True)


def delete_feed(identifier, remove_media=True):
    from yp2pc.youtube import cache

    identifier = playlist_id(identifier)
    with feed_operation:
        path = root() / ("feed-" + identifier + ".json")
        if not path.is_file():
            raise AppError("フィードが見つかりません。", 404, "not_found")
        feed = json.loads(path.read_text(encoding="utf-8"))
        retained_ids = set()
        if remove_media:
            # 他フィードを読み取れない場合は、誤削除を防ぐため操作を止めます。
            for other in root().glob("feed-*.json"):
                if other != path:
                    document = json.loads(other.read_text(encoding="utf-8"))
                    retained_ids.update(episode["id"] for episode in document["episodes"])
        # 再登録しても削除済みの購読URLを復活させません。
        from yp2pc import subscriptions
        subscriptions.remove(identifier)
        path.unlink()
        for limit in range(1, 11):
            cache.remove(f"feed:{identifier}:{limit}")
        removed, failures = 0, []
        if remove_media:
            with _download_lock:
                for episode in feed["episodes"]:
                    if episode["id"] not in retained_ids:
                        for suffix in (".m4a", ".jpg", ".json", ".am.m4a", ".am.json"):
                            target = media_path(episode["id"], suffix)
                            try:
                                if target.is_file():
                                    target.unlink()
                                    removed += 1
                            except OSError:
                                failures.append(target.name)
        return {"deleted": identifier, "removedFiles": removed, "cleanupFailures": failures}


def load_feed(identifier, normalize_media=True):
    try:
        feed = json.loads((root() / ("feed-" + playlist_id(identifier) + ".json")).read_text(encoding="utf-8"))
        episodes = []
        for episode in feed["episodes"]:
            saved = read_episode(episode["id"])
            if saved:
                episodes.append(prepare_episode(episode["id"]) if normalize_media and saved.get("media_version") != MEDIA_VERSION else saved)
        feed["episodes"] = episodes
        return feed if feed["episodes"] else None
    except (OSError, ValueError, KeyError, TypeError):
        return None
