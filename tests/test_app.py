"""外部サービスなしでRSS、入力制限、音声中継の契約を検証します。"""

import io
import json
import os
import threading
import subprocess
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from xml.etree import ElementTree as ET

from api.index import handler
from yp2pc import core, youtube

FEED = {
    "id": "PLF119azDj_Og", "title": '日本語 & <番組> "テスト"\x00', "description": "説明\nテスト",
    "author": "作者", "episodes": [{"id": "TbalaZ5EhYA", "title": "第1回 & 第2回",
                                      "size": 100, "duration": 60, "published": 1700000000}],
    "issues": [], "scannedCount": 1, "totalCount": 1, "limit": 10,
}


class ValidationTests(unittest.TestCase):
    def test_shared_playlist_and_watch_urls(self):
        for url in ["https://youtube.com/playlist?list=PLF119azDj_Og&si=example",
                    "https://www.youtube.com/watch?v=TbalaZ5EhYA&list=PLF119azDj_Og",
                    "https://music.youtube.com/playlist?list=PLF119azDj_Og", "PLF119azDj_Og"]:
            with self.subTest(url=url):
                self.assertEqual(core.playlist_id(url), "PLF119azDj_Og")

    def test_untrusted_urls_are_rejected(self):
        for url in [None, [], "", "file:///etc/passwd", "https://youtube.com.evil.test/?list=PLF119azDj_Og",
                    "https://youtube.com@127.0.0.1/?list=PLF119azDj_Og",
                    "https://youtube.com:9000/?list=PLF119azDj_Og", "https://youtube.com/watch?v=TbalaZ5EhYA",
                    "https://youtube.com/?list=PLF119azDj_Og&list=PLXXXXXXXXXX"]:
            with self.subTest(url=url), self.assertRaises(core.AppError):
                core.playlist_id(url)

    def test_media_target_cannot_be_arbitrary(self):
        for url in ["http://r1.googlevideo.com/media", "https://googlevideo.com.evil.test/",
                    "https://127.0.0.1/", "https://user:password@r1.googlevideo.com/a",
                    "https://r1.googlevideo.com:8080/a"]:
            with self.subTest(url=url), self.assertRaises(core.AppError):
                youtube.trusted_media_url(url)
        self.assertEqual(youtube.trusted_media_url("https://r1.googlevideo.com/a"), "https://r1.googlevideo.com/a")

    def test_redirect_target_is_checked(self):
        with self.assertRaises(core.AppError):
            youtube.MediaRedirects().redirect_request(None, None, 302, "", {}, "https://127.0.0.1/secrets")

    def test_base_url_does_not_trust_host_header(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(core.base_url("localhost:3000"), "http://localhost:3000")
            with self.assertRaises(core.AppError):
                core.base_url("attacker.example")
        with patch.dict(os.environ, {"APP_BASE_URL": "https://pod.example/"}, clear=True):
            self.assertEqual(core.base_url("attacker.example"), "https://pod.example")

    def test_rss_has_stable_urls_exact_lengths_and_escaped_text(self):
        xml = core.rss_document(FEED, "https://pod.example")
        root = ET.fromstring(xml)
        self.assertEqual(root.findtext("channel/title"), FEED["title"].replace("\x00", ""))
        enclosure = root.find("channel/item/enclosure")
        self.assertEqual(enclosure.attrib, {"url": "https://pod.example/audio/TbalaZ5EhYA.m4a",
                                          "length": "100", "type": "audio/x-m4a"})
        self.assertEqual(root.findtext("channel/item/guid"), "youtube:video:TbalaZ5EhYA")
        self.assertIn("+0000", root.findtext("channel/item/pubDate"))
        self.assertNotIn(b"googlevideo", xml)

    def test_cache_is_bounded_and_expires(self):
        cache = youtube.MetadataCache(2)
        cache.put("old", 1, -1)
        self.assertIsNone(cache.get("old"))
        cache.put("one", 1, 100)
        cache.put("two", 2, 100)
        cache.put("three", 3, 100)
        self.assertIsNone(cache.get("one"))
        self.assertEqual(cache.get("three"), 3)

    def test_feed_handles_partial_failure_without_empty_success(self):
        playlist = {"title": "番組", "entries": [{"id": "TbalaZ5EhYA"}, {"id": "abcdefghijk"}]}
        episode = {**FEED["episodes"][0], "url": "https://r1.googlevideo.com/signed", "headers": {}}
        with patch.object(youtube, "cache", youtube.MetadataCache()), patch.object(youtube, "extract", return_value=playlist), patch.object(youtube, "audio_source", side_effect=[episode, core.AppError("取得不可")]):
            feed = youtube.build_feed(FEED["id"])
            self.assertEqual(len(feed["episodes"]), 1)
            self.assertEqual(len(feed["issues"]), 1)
            self.assertNotIn("url", feed["episodes"][0])
        with patch.object(youtube, "cache", youtube.MetadataCache()), patch.object(youtube, "extract", return_value=playlist), patch.object(youtube, "audio_source", side_effect=core.AppError("取得不可")):
            with self.assertRaises(core.AppError) as error:
                youtube.build_feed(FEED["id"])
            self.assertEqual(error.exception.code, "no_playable_episodes")

    def test_unknown_length_is_not_replaced_with_estimate(self):
        info = {"ext": "m4a", "url": "https://r1.googlevideo.com/media", "filesize_approx": 99}
        with patch.object(youtube, "cache", youtube.MetadataCache()), patch.object(youtube, "extract", return_value=info), patch.object(youtube, "open_media", return_value=Upstream(b"", {"Content-Length": "100"})):
            self.assertEqual(youtube.audio_source("TbalaZ5EhYA")["size"], 100)

    def test_bot_rejection_is_distinguished_from_missing_dependency(self):
        cases = [("Sign in to confirm you're not a bot", "youtube_blocked", 502),
                 ("No module named yt_dlp", "configuration_error", 503)]
        for stderr, code, status in cases:
            with self.subTest(code=code), patch.object(youtube, "command_prefix", return_value=["yt-dlp"]), patch.object(youtube.importlib.util, "find_spec", return_value=None), patch.object(youtube.shutil, "which", return_value=None), patch.object(youtube.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", stderr)):
                with self.assertRaises(core.AppError) as error:
                    youtube.extract("https://www.youtube.com/watch?v=TbalaZ5EhYA", [])
                self.assertEqual(error.exception.code, code)
                self.assertEqual(error.exception.status, status)


class Upstream(io.BytesIO):
    def __init__(self, body=b"audio", headers=None, status=200):
        super().__init__(body)
        self.headers = headers or {"Content-Length": str(len(body))}
        self.status = status


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_create_feed_and_read_xml(self):
        with patch("api.index.build_feed", return_value=FEED):
            status, _, body = self.request("POST", "/api/feeds", json.dumps({"url": FEED["id"]}), {"Content-Type": "application/json"})
            self.assertEqual(status, 200)
            result = json.loads(body)
            self.assertTrue(result["feedUrl"].endswith("/feed/PLF119azDj_Og.xml"))
            self.assertTrue(result["local"])
            status, headers, body = self.request("GET", "/feed/PLF119azDj_Og.xml")
            self.assertEqual(status, 200)
            self.assertEqual(ET.fromstring(body).tag, "rss")
            status, _, body = self.request("GET", "/feed/PLF119azDj_Og.xml", headers={"If-None-Match": headers["ETag"]})
            self.assertEqual(status, 304)
            self.assertEqual(body, b"")

    def test_failed_feed_does_not_return_success_or_cache_error(self):
        with patch("api.index.build_feed", side_effect=core.AppError("取得できません。", 502)):
            status, headers, _ = self.request("GET", "/feed/PLF119azDj_Og.xml")
            self.assertEqual(status, 502)
            self.assertEqual(headers["Cache-Control"], "no-store")

    def test_wrong_method_json_and_large_request(self):
        self.assertEqual(self.request("GET", "/api/feeds")[0], 405)
        self.assertEqual(self.request("POST", "/api/feeds", "{}")[0], 415)
        headers = {"Content-Type": "application/json"}
        self.assertEqual(self.request("POST", "/api/feeds", "[]", headers)[0], 400)
        self.assertEqual(self.request("POST", "/api/feeds", "!", headers)[0], 400)
        self.assertEqual(self.request("POST", "/api/feeds", "a" * 4097, headers)[0], 413)

    def test_cross_origin_submission_is_rejected(self):
        self.assertEqual(self.request("POST", "/api/feeds", "{}", {"Content-Type": "application/json", "Origin": "https://evil.example"})[0], 403)

    def test_audio_full_response_and_cleanup(self):
        upstream = Upstream(b"12345678")
        with patch("api.index.audio_source", return_value={}), patch("api.index.open_media", return_value=upstream):
            status, headers, body = self.request("GET", "/audio/TbalaZ5EhYA.m4a")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"12345678")
        self.assertEqual(headers["Content-Length"], "8")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertTrue(upstream.closed)

    def test_audio_range_and_head(self):
        with patch("api.index.audio_source", return_value={}), patch("api.index.open_media", return_value=Upstream(b"234", {"Content-Length": "3", "Content-Range": "bytes 1-3/8"}, 206)) as media:
            status, headers, body = self.request("GET", "/audio/TbalaZ5EhYA.m4a", headers={"Range": "bytes=1-3"})
            self.assertEqual((status, body), (206, b"234"))
            self.assertEqual(headers["Content-Range"], "bytes 1-3/8")
            media.assert_called_once_with({}, "GET", "bytes=1-3")
        with patch("api.index.audio_source", return_value={}), patch("api.index.open_media", return_value=Upstream(b"", {"Content-Length": "100"})):
            status, headers, body = self.request("HEAD", "/audio/TbalaZ5EhYA.m4a")
            self.assertEqual(status, 200)
            self.assertEqual(body, b"")
            self.assertEqual(headers["Content-Length"], "100")

    def test_audio_refreshes_expired_url_once(self):
        failure = HTTPError("", 403, "期限切れ", {}, None)
        with patch("api.index.audio_source", return_value={}) as source, patch("api.index.open_media", side_effect=[failure, Upstream()]):
            self.assertEqual(self.request("GET", "/audio/TbalaZ5EhYA.m4a")[0], 200)
            self.assertEqual(source.call_count, 2)
            source.assert_called_with("TbalaZ5EhYA", refresh=True)

    def test_head_uses_small_get_probe_and_reports_full_size(self):
        with patch("api.index.audio_source", return_value={}), patch("api.index.open_media", return_value=Upstream(b"a", {"Content-Length": "1", "Content-Range": "bytes 0-0/12345"}, 206)) as media:
            status, headers, body = self.request("HEAD", "/audio/TbalaZ5EhYA.m4a")
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Length"], "12345")
            self.assertNotIn("Content-Range", headers)
            self.assertEqual(body, b"")
            media.assert_called_once_with({}, "GET", "bytes=0-0")

    def test_invalid_ranges_and_invalid_video_ids(self):
        self.assertEqual(self.request("GET", "/audio/TbalaZ5EhYA.m4a", headers={"Range": "bytes=1-2,3-4"})[0], 416)
        self.assertEqual(self.request("GET", "/audio/short.m4a")[0], 404)
        self.assertEqual(self.request("GET", "/audio/../../secrets.m4a")[0], 404)


if __name__ == "__main__":
    unittest.main()
