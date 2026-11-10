"""指定プレイリストのRSS・HEAD・音声の部分取得を実サーバーで確認します。"""

import argparse
import getpass
import sys
from pathlib import Path
from http.cookiejar import CookieJar
import json
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yp2pc.core import playlist_id

parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://127.0.0.1:3000")
parser.add_argument("--playlist", default="https://www.youtube.com/playlist?list=PLF119azDj_Og")
parser.add_argument("--create", action="store_true", help="管理パスワードを入力してフィードを追加する")
args = parser.parse_args()
opener = build_opener(HTTPCookieProcessor(CookieJar()))


def checked_open(request, timeout=90):
    try:
        return opener.open(request, timeout=timeout)
    except HTTPError as error:
        print(f"HTTP {error.code}: {error.read(4096).decode('utf-8', errors='replace')}")
        raise SystemExit(1) from None


if args.create:
    password = getpass.getpass("管理パスワード: ")
    with checked_open(Request(args.base + "/api/login", data=json.dumps({"password": password}).encode(), headers={"Content-Type": "application/json"})):
        pass
    with checked_open(Request(args.base + "/api/feeds", data=json.dumps({"url": args.playlist}).encode(), headers={"Content-Type": "application/json"}), timeout=3600):
        pass
rss_url = args.base + "/feed/" + playlist_id(args.playlist) + ".xml"
with checked_open(rss_url, timeout=3600) as response:
    rss = ET.fromstring(response.read())
print(json.dumps({"番組": rss.findtext("channel/title"), "エピソード数": len(rss.findall("channel/item")), "RSS": rss_url}, ensure_ascii=False))
enclosure = rss.find("channel/item/enclosure")
assert enclosure is not None
audio_parts = urlsplit(enclosure.attrib["url"])
audio_url = args.base + audio_parts.path + ("?" + audio_parts.query if audio_parts.query else "")
with checked_open(Request(audio_url, method="HEAD"), timeout=90) as response:
    length = int(response.headers["Content-Length"])
    assert length == int(enclosure.attrib["length"])
    print(f"音声HEAD: HTTP {response.status}、{length} バイト")
for byte_range in ["bytes=0-1023", f"bytes={length // 2}-{length // 2 + 1023}", f"bytes={length - 1024}-{length - 1}"]:
    started = time.perf_counter()
    with checked_open(Request(audio_url, headers={"Range": byte_range}), timeout=90) as response:
        audio = response.read()
        assert response.status == 206, response.status
        assert len(audio) == 1024, len(audio)
        if byte_range == "bytes=0-1023":
            assert b"ftyp" in audio[:32], "M4Aコンテナーを確認できません。"
        print(f"音声部分取得: HTTP {response.status}、{response.headers['Content-Range']}、{len(audio)} バイト、{(time.perf_counter() - started) * 1000:.1f}ms")
image = rss.find("channel/item/{http://www.itunes.com/dtds/podcast-1.0.dtd}image")
assert image is not None, "エピソード画像がありません。"
with checked_open(args.base + urlsplit(image.attrib["href"]).path) as response:
    assert response.headers["Content-Type"] == "image/jpeg"
    assert response.read(2) == b"\xff\xd8"
    print("エピソード画像: JPEG取得に成功しました。")
print("RSS・音声HEAD・先頭/中間/末尾の部分取得・画像に成功しました。iPadでの操作感と画像表示は別途確認してください。")
