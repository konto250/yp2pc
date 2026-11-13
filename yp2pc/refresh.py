"""配信を取得待ちにしないため、登録済みフィードを定期更新します。"""
import logging
import os
import threading

from yp2pc import storage
from yp2pc.core import AppError
from yp2pc.youtube import build_feed


def interval():
    return max(0, int(os.environ.get("FEED_REFRESH_SECONDS", "0")))


def refresh_once():
    for feed in storage.list_feeds():
        with storage.feed_operation:
            if not storage.registered(feed["id"]):
                continue
            try:
                build_feed(feed["id"])
            except AppError as error:
                logging.warning("フィードの定期更新失敗: %s", error.code)
            except Exception as error:
                logging.error("フィードの定期更新失敗: %s", type(error).__name__)


def start():
    stop = threading.Event()
    seconds = interval()
    if seconds:
        def run():
            while not stop.wait(seconds):
                refresh_once()
        threading.Thread(target=run, name="feed-refresh", daemon=True).start()
    return stop
