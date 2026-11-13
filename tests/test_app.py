"""外部サービスなしでRSS、入力制限、保存済み音声の配信を検証します。"""

import io
import hashlib
import tempfile
from pathlib import Path
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
from yp2pc import core, youtube, storage, auth

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

    def test_explicit_lan_origin_and_invalid_configurations(self):
        for origin in ["http://192.168.1.4:3000", "http://10.0.0.2:3000", "http://172.16.1.2:3000"]:
            with self.subTest(origin=origin), patch.dict(os.environ, {"APP_BASE_URL": origin}, clear=True):
                self.assertEqual(core.base_url("untrusted.test"), origin)
                enclosure = ET.fromstring(core.rss_document(FEED, origin)).find("channel/item/enclosure")
                self.assertTrue(enclosure.get("url").startswith(origin + "/audio/"))
        for origin in ["http://8.8.8.8:3000", "http://169.254.169.254", "http://0.0.0.0:3000",
                       "http://example.com", "http://192.168.1.4:99999", "http://192.168.1.4:0",
                       "http://192.168.1.4:3000/path", "https://example.com:invalid", "http://[broken"]:
            with self.subTest(origin=origin), patch.dict(os.environ, {"APP_BASE_URL": origin}, clear=True), self.assertRaises(core.AppError):
                core.base_url("localhost")

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
        with patch.object(youtube, "cache", youtube.MetadataCache()), patch.object(youtube, "extract", return_value=playlist), patch.object(storage, "prepare_episode", side_effect=[episode, core.AppError("取得不可")]), patch.object(storage, "save_feed"):
            feed = youtube.build_feed(FEED["id"])
            self.assertEqual(len(feed["episodes"]), 1)
            self.assertEqual(len(feed["issues"]), 1)
            self.assertNotIn("url", feed["episodes"][0])
        with patch.object(youtube, "cache", youtube.MetadataCache()), patch.object(youtube, "extract", return_value=playlist), patch.object(storage, "prepare_episode", side_effect=core.AppError("取得不可")):
            with self.assertRaises(core.AppError) as error:
                youtube.build_feed(FEED["id"])
            self.assertEqual(error.exception.code, "no_playable_episodes")

    def test_unknown_length_is_not_replaced_with_estimate(self):
        info = {"ext": "m4a", "url": "https://r1.googlevideo.com/media", "filesize_approx": 99}
        with patch.object(youtube, "cache", youtube.MetadataCache()), patch.object(youtube, "extract", return_value=info), patch.object(youtube, "open_media", return_value=Upstream(b"", {"Content-Length": "100"})):
            self.assertEqual(youtube.audio_source("TbalaZ5EhYA")["size"], 100)

    def test_bot_rejection_is_distinguished_from_missing_dependency(self):
        cases = [("Sign in to confirm you're not a bot", "youtube_blocked", 502),
                 ("ログインして bot ではないことを確認してください", "youtube_blocked", 502),
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
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"MEDIA_DIR": self.directory.name, "ADMIN_PASSWORD_HASH": auth.password_hash("test-password-123")}, clear=True)
        self.env.start()
        auth.sessions.clear()
        auth.attempts.clear()
        self.cookie = auth.COOKIE + "=" + auth.create_session()
        storage.save_feed(FEED)
        self.audio = b"12345678"
        storage.media_path("TbalaZ5EhYA").write_bytes(self.audio)
        storage.write_json(storage.media_path("TbalaZ5EhYA", ".json"), {
            "id": "TbalaZ5EhYA", "size": 8, "sha256": hashlib.sha256(self.audio).hexdigest(), "media_version": 1})

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def request(self, method, path, body=None, headers=None, authenticated=True):
        connection = HTTPConnection(*self.server.server_address, timeout=5)
        try:
            request_headers = {"Cookie": self.cookie} if authenticated else {}
            request_headers.update(headers or {})
            connection.request(method, path, body, request_headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_create_feed_and_read_xml(self):
        with patch("api.index.build_feed", return_value=FEED), patch.object(storage, "prepare_am_feed", return_value=[]) as am:
            status, _, body = self.request("POST", "/api/feeds", json.dumps({"url": FEED["id"]}), {"Content-Type": "application/json"})
            self.assertEqual(status, 200)
            result = json.loads(body)
            self.assertTrue(result["feedUrl"].endswith("/feed/PLF119azDj_Og.xml"))
            self.assertTrue(result["amFeedUrl"].endswith("/feed/PLF119azDj_Og.am.xml"))
            am.assert_called_once_with(FEED)
            self.assertTrue(result["local"])
            status, headers, body = self.request("GET", "/feed/PLF119azDj_Og.xml")
            self.assertEqual(status, 200)
            self.assertEqual(ET.fromstring(body).tag, "rss")
            self.assertEqual(headers["Content-Type"], "application/xml; charset=utf-8")
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertNotIn("ETag", headers)
            original = body
            previous_etag = '"' + hashlib.sha256(body).hexdigest() + '"'
            status, _, body = self.request("GET", "/feed/PLF119azDj_Og.xml", authenticated=False,
                                          headers={"If-None-Match": previous_etag})
            self.assertEqual(status, 200)
            self.assertEqual(body, original)
            status, headers, body = self.request("HEAD", "/feed/PLF119azDj_Og.xml", authenticated=False,
                                                headers={"If-None-Match": previous_etag})
            self.assertEqual(status, 200)
            self.assertEqual(int(headers["Content-Length"]), len(original))
            self.assertEqual(body, b"")

    def save_am(self):
        from yp2pc.radio import RADIO_VERSION
        original = storage.read_episode("TbalaZ5EhYA")
        storage.write_json(storage.media_path("TbalaZ5EhYA", ".json"), {**FEED["episodes"][0], **original})
        payload = b"am-radio-audio"
        storage.media_path("TbalaZ5EhYA", ".am.m4a").write_bytes(payload)
        storage.write_json(storage.media_path("TbalaZ5EhYA", ".am.json"), {
            "source_sha256": hashlib.sha256(self.audio).hexdigest(), "radio_version": RADIO_VERSION,
            "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload), "duration": 10})
        return payload

    def test_am_is_separate_public_feed_and_audio_without_live_conversion(self):
        payload = self.save_am()
        with patch("api.index.build_feed", side_effect=AssertionError("公開AMフィードでは取得しません")), \
                patch.object(storage, "prepare_am_episode", side_effect=AssertionError("公開配信で変換しません")):
            status, headers, body = self.request("GET", "/feed/PLF119azDj_Og.am.xml", authenticated=False)
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            feed = ET.fromstring(body)
            self.assertTrue(feed.findtext("channel/title").endswith("【AMラジオ音質】"))
            self.assertEqual(feed.findtext("channel/item/guid"), "youtube:video:TbalaZ5EhYA:am")
            enclosure = feed.find("channel/item/enclosure").attrib
            self.assertIn("/audio/TbalaZ5EhYA.am.m4a?v=", enclosure["url"])
            self.assertEqual(int(enclosure["length"]), len(payload))
            status, headers, body = self.request("GET", "/audio/TbalaZ5EhYA.am.m4a", authenticated=False, headers={"Range": "bytes=2-5"})
            self.assertEqual((status, body), (206, payload[2:6]))
            self.assertEqual(headers["Content-Range"], f"bytes 2-5/{len(payload)}")
            status, headers, body = self.request("HEAD", "/audio/TbalaZ5EhYA.am.m4a", authenticated=False)
            self.assertEqual((status, int(headers["Content-Length"]), body), (200, len(payload), b""))
        status, _, body = self.request("GET", "/api/feeds")
        self.assertIn("amFeedUrl", json.loads(body)["feeds"][0])

    def test_am_pending_and_deleted_feeds_never_trigger_conversion(self):
        with patch.object(storage, "prepare_am_episode", side_effect=AssertionError("公開配信で変換しません")):
            self.assertEqual(self.request("GET", "/feed/PLF119azDj_Og.am.xml", authenticated=False)[0], 503)
            self.save_am()
            status, _, body = self.request("DELETE", "/api/feeds/PLF119azDj_Og", "{}", {"Content-Type": "application/json"})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["removedFiles"], 4)
            for path in ("/feed/PLF119azDj_Og.am.xml", "/audio/TbalaZ5EhYA.am.m4a"):
                self.assertEqual(self.request("GET", path, authenticated=False)[0], 404)

    def test_failed_feed_does_not_return_success_or_cache_error(self):
        with patch("api.index.build_feed", side_effect=core.AppError("取得できません。", 502)):
            status, headers, _ = self.request("GET", "/feed/PLF119azDj_Og.xml")
            self.assertEqual(status, 502)
            self.assertEqual(headers["Cache-Control"], "no-store")

    def test_background_mode_serves_saved_rss_during_refresh_and_outage(self):
        saved = {**FEED["episodes"][0], "size": 8, "media_version": 1,
                 "sha256": hashlib.sha256(self.audio).hexdigest()}
        storage.write_json(storage.media_path("TbalaZ5EhYA", ".json"), saved)
        # 別スレッドの更新ロックを保持しても、RSS・音声配信は待ちません。
        with patch.dict(os.environ, {"FEED_REFRESH_SECONDS": "900", "https_proxy": "http://127.0.0.1:1"}), \
                patch("api.index.build_feed", side_effect=AssertionError("配信時の取得は禁止")), \
                patch.object(youtube, "extract", side_effect=AssertionError("外部接続は禁止")), \
                storage.feed_operation:
            status, _, body = self.request("GET", "/feed/PLF119azDj_Og.xml", authenticated=False)
            self.assertEqual(status, 200)
            self.assertEqual(ET.fromstring(body).findtext("channel/item/title"), saved["title"])
            self.assertEqual(self.request("GET", "/audio/TbalaZ5EhYA.m4a", authenticated=False)[0], 200)
            self.assertEqual(self.request("GET", "/feed/PLmissing123.xml", authenticated=False)[0], 404)

    def test_wrong_method_json_and_large_request(self):
        self.assertEqual(self.request("HEAD", "/api/feeds")[0], 405)
        self.assertEqual(self.request("POST", "/api/feeds", "{}")[0], 415)
        headers = {"Content-Type": "application/json"}
        self.assertEqual(self.request("POST", "/api/feeds", "[]", headers)[0], 400)
        self.assertEqual(self.request("POST", "/api/feeds", "!", headers)[0], 400)
        self.assertEqual(self.request("POST", "/api/feeds", "a" * 4097, headers)[0], 413)

    def test_cross_origin_submission_is_rejected(self):
        self.assertEqual(self.request("POST", "/api/feeds", "{}", {"Content-Type": "application/json", "Origin": "https://evil.example"})[0], 403)

    def test_stored_audio_never_calls_youtube(self):
        with patch.object(youtube, "audio_source", side_effect=AssertionError("外部取得は禁止")):
            status, headers, body = self.request("GET", "/audio/TbalaZ5EhYA.m4a")
            self.assertEqual((status, body), (200, self.audio))
            self.assertEqual(headers["Content-Length"], "8")
            self.assertEqual(headers["Accept-Ranges"], "bytes")
            status, head, body = self.request("HEAD", "/audio/TbalaZ5EhYA.m4a")
            self.assertEqual((status, body), (200, b""))
            self.assertEqual(head["Content-Length"], "8")

    def test_stored_audio_seek_ranges(self):
        for requested, content, expected in [("bytes=1-3", b"234", "bytes 1-3/8"),
                                             ("bytes=5-", b"678", "bytes 5-7/8"),
                                             ("bytes=-2", b"78", "bytes 6-7/8"),
                                             ("bytes=6-999", b"78", "bytes 6-7/8"),
                                             ("bytes=-999", self.audio, "bytes 0-7/8")]:
            with self.subTest(requested=requested):
                status, headers, body = self.request("GET", "/audio/TbalaZ5EhYA.m4a", headers={"Range": requested})
                self.assertEqual((status, body), (206, content))
                self.assertEqual(headers["Content-Range"], expected)
                self.assertEqual(int(headers["Content-Length"]), len(content))
        status, headers, body = self.request("HEAD", "/audio/TbalaZ5EhYA.m4a", headers={"Range": "bytes=1-3"})
        self.assertEqual((status, body, headers["Content-Length"]), (206, b"", "3"))

    def test_invalid_ranges_and_video_ids(self):
        for requested in ["bytes=9-", "bytes=4-3", "bytes=-0", "bytes=1-2,3-4", "invalid"]:
            status, headers, body = self.request("GET", "/audio/TbalaZ5EhYA.m4a", headers={"Range": requested})
            self.assertEqual((status, body), (416, b""))
            self.assertEqual(headers["Content-Range"], "bytes */8")
        self.assertEqual(self.request("GET", "/audio/short.m4a")[0], 404)
        self.assertEqual(self.request("GET", "/audio/../../secrets.m4a")[0], 404)

    def test_stored_conditional_requests(self):
        _, headers, _ = self.request("HEAD", "/audio/TbalaZ5EhYA.m4a")
        self.assertEqual(self.request("GET", "/audio/TbalaZ5EhYA.m4a", headers={"If-None-Match": headers["ETag"]})[0], 304)
        self.assertEqual(self.request("GET", "/audio/TbalaZ5EhYA.m4a", headers={"Range": "bytes=1-3", "If-Range": headers["ETag"]})[0], 206)
        status, _, body = self.request("GET", "/audio/TbalaZ5EhYA.m4a", headers={"Range": "bytes=1-3", "If-Range": '"old"'})
        self.assertEqual((status, body), (200, self.audio))

    def test_artwork_response_and_missing_art(self):
        path = "/artwork/TbalaZ5EhYA.jpg"
        self.assertEqual(self.request("GET", path)[0], 404)
        storage.media_path("TbalaZ5EhYA", ".jpg").write_bytes(b"jpeg-data")
        status, headers, body = self.request("GET", path)
        self.assertEqual((status, headers["Content-Type"], body), (200, "image/jpeg", b"jpeg-data"))

    def test_admin_screen_and_mutations_require_login(self):
        status, headers, _ = self.request("GET", "/", authenticated=False)
        self.assertEqual((status, headers["Location"]), (302, "/login"))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.request("GET", "/login", authenticated=False)[0], 200)
        for method, path in [("GET", "/api/feeds"), ("POST", "/api/feeds"), ("DELETE", "/api/feeds/PLF119azDj_Og")]:
            self.assertEqual(self.request(method, path, authenticated=False)[0], 401)
        self.assertEqual(self.request("GET", "/")[0], 200)

    def test_public_feed_audio_and_artwork_do_not_require_login(self):
        storage.media_path("TbalaZ5EhYA", ".jpg").write_bytes(b"jpeg-data")
        with patch("api.index.build_feed", return_value=FEED):
            self.assertEqual(self.request("GET", "/feed/PLF119azDj_Og.xml", authenticated=False)[0], 200)
        self.assertEqual(self.request("GET", "/audio/TbalaZ5EhYA.m4a", authenticated=False)[0], 200)
        self.assertEqual(self.request("GET", "/artwork/TbalaZ5EhYA.jpg", authenticated=False)[0], 200)

    def test_login_logout_and_forged_or_expired_cookie(self):
        headers = {"Content-Type": "application/json"}
        self.assertEqual(self.request("POST", "/api/login", json.dumps({"password": "wrong"}), headers, False)[0], 401)
        with patch.dict(os.environ, {"APP_BASE_URL": "https://podcast.example"}):
            status, reply, _ = self.request("POST", "/api/login", json.dumps({"password": "test-password-123"}), headers, False)
        self.assertEqual(status, 200)
        cookie = reply["Set-Cookie"]
        for flag in ["HttpOnly", "SameSite=Strict", "Secure", "Max-Age=43200"]:
            self.assertIn(flag, cookie)
        session = {"Cookie": cookie.split(";", 1)[0]}
        self.assertEqual(self.request("GET", "/api/feeds", headers=session, authenticated=False)[0], 200)
        self.assertEqual(self.request("POST", "/api/logout", headers=session, authenticated=False)[0], 200)
        self.assertEqual(self.request("GET", "/api/feeds", headers=session, authenticated=False)[0], 401)
        self.assertEqual(self.request("GET", "/api/feeds", headers={"Cookie": auth.COOKIE + "=" + "a" * 43}, authenticated=False)[0], 401)
        key = auth.session_key(self.cookie)
        auth.sessions[key] = (0, os.environ["ADMIN_PASSWORD_HASH"])
        self.assertEqual(self.request("GET", "/api/feeds")[0], 401)

    def test_login_configuration_and_rate_limit(self):
        headers = {"Content-Type": "application/json"}
        with patch.dict(os.environ, {"ADMIN_PASSWORD_HASH": ""}):
            self.assertEqual(self.request("POST", "/api/login", '{"password":"test"}', headers, False)[0], 503)
        for _ in range(10):
            self.assertEqual(self.request("POST", "/api/login", '{"password":"wrong"}', headers, False)[0], 401)
        self.assertEqual(self.request("POST", "/api/login", '{"password":"wrong"}', headers, False)[0], 429)

    def test_delete_feed_and_unused_media_cannot_be_regenerated_publicly(self):
        storage.media_path("TbalaZ5EhYA", ".jpg").write_bytes(b"jpeg-data")
        youtube.cache.put("feed:PLF119azDj_Og:10", FEED, 300)
        status, _, body = self.request("DELETE", "/api/feeds/PLF119azDj_Og", "{}", {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["removedFiles"], 3)
        self.assertIsNone(youtube.cache.get("feed:PLF119azDj_Og:10"))
        with patch("api.index.build_feed", side_effect=AssertionError("削除済みフィードは再生成禁止")), patch.object(storage, "prepare_episode", side_effect=AssertionError("未保存音声の取得は禁止")):
            for path in ["/feed/PLF119azDj_Og.xml", "/audio/TbalaZ5EhYA.m4a", "/feed/PLnotregistered.xml", "/audio/abcdefghijk.m4a"]:
                self.assertEqual(self.request("GET", path, authenticated=False)[0], 404)

    def test_delete_preserves_shared_media_and_can_keep_files(self):
        self.save_am()
        storage.save_feed({**FEED, "id": "PLshared12345"})
        status, _, body = self.request("DELETE", "/api/feeds/PLF119azDj_Og", "{}", {"Content-Type": "application/json"})
        self.assertEqual((status, json.loads(body)["removedFiles"]), (200, 0))
        self.assertTrue(storage.media_path("TbalaZ5EhYA").is_file())
        self.assertTrue(storage.media_path("TbalaZ5EhYA", ".am.m4a").is_file())
        status, _, _ = self.request("DELETE", "/api/feeds/PLshared12345", '{"removeMedia":false}', {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertTrue(storage.media_path("TbalaZ5EhYA").is_file())

    def test_cross_origin_delete_and_login_are_rejected(self):
        headers = {"Content-Type": "application/json", "Origin": "https://evil.example"}
        self.assertEqual(self.request("DELETE", "/api/feeds/PLF119azDj_Og", "{}", headers)[0], 403)
        self.assertEqual(self.request("POST", "/api/login", '{"password":"test-password-123"}', headers, False)[0], 403)
        self.assertTrue(storage.registered(FEED["id"]))


if __name__ == "__main__":
    unittest.main()
