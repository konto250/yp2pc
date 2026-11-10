"""指定プレイリストのRSS・HEAD・音声の部分取得を実サーバーで確認します。"""

import argparse
import json
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://127.0.0.1:3000")
parser.add_argument("--playlist", default="https://www.youtube.com/playlist?list=PLF119azDj_Og")
args = parser.parse_args()


def checked_open(request, timeout=90):
    try:
        return urlopen(request, timeout=timeout)
    except HTTPError as error:
        print(f"HTTP {error.code}: {error.read(4096).decode('utf-8', errors='replace')}")
        raise SystemExit(1) from None


with checked_open(Request(args.base + "/api/feeds", data=json.dumps({"url": args.playlist}).encode(), headers={"Content-Type": "application/json"}), timeout=3600) as response:
    feed = json.load(response)
print(json.dumps({"番組": feed["title"], "エピソード数": len(feed["episodes"]), "RSS": feed["feedUrl"]}, ensure_ascii=False))
with checked_open(args.base + urlsplit(feed["feedUrl"]).path, timeout=280) as response:
    rss = ET.fromstring(response.read())
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
with checked_open(image.attrib["href"]) as response:
    assert response.headers["Content-Type"] == "image/jpeg"
    assert response.read(2) == b"\xff\xd8"
    print("エピソード画像: JPEG取得に成功しました。")
print("RSS・音声HEAD・先頭/中間/末尾の部分取得・画像に成功しました。iPadでの操作感と画像表示は別途確認してください。")
