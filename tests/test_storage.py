"""保存の完了判定・再利用・画像・障害時のフィード継続を検証します。"""

import io
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from xml.etree import ElementTree as ET

from PIL import Image
from yp2pc import core, storage, youtube

IDENTIFIER = "TbalaZ5EhYA"
PAYLOAD = b"\x00\x00\x00\x20ftypM4A " + b"audio" * 50
SOURCE = {"id": IDENTIFIER, "title": "動画の名前", "description": "説明", "duration": 10,
          "published": 1700000000, "size": len(PAYLOAD), "url": "https://secret.googlevideo.com/signed", "headers": {"secret": "token"}}


class Response(io.BytesIO):
    status = 206
    headers = {"Content-Range": f"bytes 0-{len(PAYLOAD) - 1}/{len(PAYLOAD)}"}


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"MEDIA_DIR": self.directory.name}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def prepare(self, payload=PAYLOAD):
        with patch.object(youtube, "audio_source", return_value=SOURCE), patch.object(youtube, "open_media", return_value=Response(payload)), patch.object(storage, "save_artwork", return_value=False):
            return storage.prepare_episode(IDENTIFIER)

    def test_complete_download_and_reuse_without_signed_urls(self):
        self.prepare()
        self.assertEqual(storage.media_path(IDENTIFIER).read_bytes(), PAYLOAD)
        metadata = storage.media_path(IDENTIFIER, ".json").read_text(encoding="utf-8")
        self.assertNotIn("signed", metadata)
        self.assertNotIn("token", metadata)
        with patch.object(youtube, "audio_source", side_effect=AssertionError("再取得は禁止")), patch.object(storage, "save_artwork", return_value=False):
            self.assertEqual(storage.prepare_episode(IDENTIFIER)["size"], len(PAYLOAD))

    def test_truncated_download_is_not_published(self):
        with self.assertRaises(core.AppError) as error:
            self.prepare(PAYLOAD[:-5])
        self.assertEqual(error.exception.code, "download_incomplete")
        self.assertIsNone(storage.read_episode(IDENTIFIER))
        self.assertFalse(storage.media_path(IDENTIFIER).exists())
        self.assertEqual(list(storage.root().glob("*.part")), [])

    def test_capacity_limit_preserves_existing_files(self):
        storage.media_path("abcdefghijk").write_bytes(b"existing")
        with patch.dict(os.environ, {"MEDIA_MAX_BYTES": "100"}), self.assertRaises(core.AppError) as error:
            self.prepare()
        self.assertEqual(error.exception.code, "storage_full")
        self.assertEqual(storage.media_path("abcdefghijk").read_bytes(), b"existing")

    def test_multiple_ranges_are_joined_in_order(self):
        payload = PAYLOAD + b"x" * (2 * 1024 * 1024)
        requested = []

        def fetch(source, method, byte_range):
            first, last = map(int, byte_range[6:].split("-"))
            requested.append((first, last))
            response = Response(payload[first:last + 1])
            response.headers = {"Content-Range": f"bytes {first}-{last}/{len(payload)}"}
            return response

        with patch.object(youtube, "audio_source", return_value={**SOURCE, "size": len(payload)}), patch.object(youtube, "open_media", side_effect=fetch), patch.object(storage, "save_artwork", return_value=False):
            storage.prepare_episode(IDENTIFIER)
        self.assertEqual(storage.media_path(IDENTIFIER).read_bytes(), payload)
        self.assertEqual(requested, [(0, 1048575), (1048576, 2097151), (2097152, len(payload) - 1)])

    def test_wrong_range_response_is_not_published(self):
        response = Response(PAYLOAD)
        response.headers = {"Content-Range": "bytes 1-2/3"}
        with patch.object(youtube, "audio_source", return_value=SOURCE), patch.object(youtube, "open_media", return_value=response), self.assertRaises(core.AppError) as error:
            storage.prepare_episode(IDENTIFIER)
        self.assertEqual(error.exception.code, "invalid_range_response")
        self.assertIsNone(storage.read_episode(IDENTIFIER))

    def test_concurrent_requests_download_once(self):
        with patch.object(youtube, "audio_source", return_value=SOURCE), patch.object(youtube, "open_media", side_effect=lambda *args: Response(PAYLOAD)) as fetch, patch.object(storage, "save_artwork", return_value=False):
            with ThreadPoolExecutor(3) as pool:
                results = list(pool.map(storage.prepare_episode, [IDENTIFIER] * 3))
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual([result["size"] for result in results], [len(PAYLOAD)] * 3)

    def test_thumbnail_is_square_rgb_and_added_to_rss(self):
        raw = io.BytesIO()
        Image.new("RGB", (640, 360), (200, 80, 20)).save(raw, "JPEG")
        with patch.object(storage, "build_opener") as opener:
            opener.return_value.open.return_value = Response(raw.getvalue())
            self.assertTrue(storage.save_artwork(IDENTIFIER))
        with Image.open(storage.media_path(IDENTIFIER, ".jpg")) as artwork:
            self.assertEqual((artwork.size, artwork.mode), ((1400, 1400), "RGB"))
        feed = {"id": "PLF119azDj_Og", "title": "番組", "description": "", "author": "作者",
                "episodes": [{**SOURCE, "artwork": True}]}
        rss = ET.fromstring(core.rss_document(feed, "http://192.168.1.4:3000"))
        for parent in ["channel", "channel/item"]:
            self.assertEqual(rss.find(parent + "/{" + core.ITUNES + "}image").get("href"),
                             "http://192.168.1.4:3000/artwork/TbalaZ5EhYA.jpg")

    def test_saved_feed_survives_youtube_failure_and_process_cache_reset(self):
        episode = self.prepare()
        feed = {"id": "PLF119azDj_Og", "title": "番組", "description": "", "author": "作者",
                "episodes": [episode], "issues": [], "limit": 10, "scannedCount": 1, "totalCount": 1}
        storage.save_feed(feed)
        with patch.object(youtube, "cache", youtube.MetadataCache()), patch.object(youtube, "extract", side_effect=core.AppError("取得失敗")):
            fallback = youtube.build_feed(feed["id"])
            self.assertEqual(fallback["episodes"][0]["id"], IDENTIFIER)
            self.assertIn("保存済み", fallback["issues"][0]["message"])
        self.assertIsNone(storage.load_feed("PLnotexisting123"))


if __name__ == "__main__":
    unittest.main()
