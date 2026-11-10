"""入力の正規化、公開URL、RSSの組み立て。"""

import os
import ipaddress
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

PLAYLIST_ID = re.compile(r"[A-Za-z0-9_-]{10,128}\Z")
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("itunes", ITUNES)
ET.register_namespace("atom", ATOM)


class AppError(Exception):
    def __init__(self, message, status=400, code="invalid_request"):
        super().__init__(message)
        self.status = status
        self.code = code


def playlist_id(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise AppError("YouTubeのプレイリストURLを入力してください。")
    value = value.strip()
    if PLAYLIST_ID.fullmatch(value):
        return value
    try:
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"}
                or url.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
                or url.username or url.password or url.port not in {None, 80, 443}):
            raise ValueError
        ids = parse_qs(url.query).get("list", [])
        if len(ids) != 1 or not PLAYLIST_ID.fullmatch(ids[0]):
            raise ValueError
        return ids[0]
    except ValueError:
        raise AppError("list= を含むYouTubeのプレイリストURLを入力してください。") from None


def video_id(value):
    if not isinstance(value, str) or not VIDEO_ID.fullmatch(value):
        raise AppError("動画IDが正しくありません。", 404, "not_found")
    return value


def max_episodes():
    try:
        return max(1, min(10, int(os.environ.get("MAX_EPISODES", "10"))))
    except ValueError:
        return 10


def base_url(host):
    configured = os.environ.get("APP_BASE_URL", "").rstrip("/")
    if configured:
        try:
            url = urlsplit(configured)
            # HTTPは明示設定した家庭内IPv4とループバックだけに限定します。
            lan_http = url.scheme == "http" and is_local_host(url.hostname)
            if ((url.scheme != "https" and not lan_http) or not url.hostname or url.username or url.password
                    or url.path or url.query or url.fragment or url.port == 0):
                raise ValueError
        except ValueError:
            raise AppError("APP_BASE_URLにHTTPS URL、またはLAN実験用のhttp://プライベートIPv4:ポートを設定してください。", 503, "configuration_error") from None
        return configured
    if re.fullmatch(r"(?:localhost|127\.0\.0\.1)(?::[0-9]{1,5})?", host or ""):
        return "http://" + host
    raise AppError("公開URLが未設定です。APP_BASE_URLを設定してください。", 503, "configuration_error")


def is_local_host(host):
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host or "")
        return address.is_loopback or any(address in network for network in (
            ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16")))
    except ValueError:
        return False


def xml_text(value):
    # XML 1.0で使えない制御文字とサロゲートを取り除きます。
    return "".join(c for c in str(value or "") if c in "\t\n\r" or
                   0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or
                   0x10000 <= ord(c) <= 0x10FFFF)


def rss_document(feed, origin):
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")

    def tag(parent, name, value):
        ET.SubElement(parent, name).text = xml_text(value)

    source = "https://www.youtube.com/playlist?list=" + feed["id"]
    tag(channel, "title", feed["title"])
    tag(channel, "link", source)
    tag(channel, "description", feed["description"] or feed["title"])
    tag(channel, "language", "ja")
    tag(channel, "ttl", "15")
    tag(channel, f"{{{ITUNES}}}author", feed["author"])
    # URLによる個人購読が用途です。カタログ公開は要求しません。
    tag(channel, f"{{{ITUNES}}}block", "Yes")
    tag(channel, f"{{{ITUNES}}}explicit", "true")
    ET.SubElement(channel, f"{{{ITUNES}}}category", {"text": "Leisure"})
    artwork = next((episode for episode in feed["episodes"] if episode.get("artwork")), None)
    cover = origin + "/artwork/" + artwork["id"] + ".jpg" if artwork else origin + "/cover.png"
    ET.SubElement(channel, f"{{{ITUNES}}}image", {"href": cover})
    ET.SubElement(channel, f"{{{ATOM}}}link", {
        "href": origin + "/feed/" + feed["id"] + ".xml", "rel": "self", "type": "application/rss+xml"
    })
    for episode in feed["episodes"]:
        item = ET.SubElement(channel, "item")
        tag(item, "title", episode["title"])
        tag(item, "description", episode.get("description", ""))
        if episode.get("artwork"):
            ET.SubElement(item, f"{{{ITUNES}}}image", {"href": origin + "/artwork/" + episode["id"] + ".jpg"})
        tag(item, "link", "https://www.youtube.com/watch?v=" + episode["id"])
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = "youtube:video:" + episode["id"]
        ET.SubElement(item, "enclosure", {
            "url": origin + "/audio/" + episode["id"] + ".m4a",
            "length": str(episode["size"]), "type": "audio/x-m4a"
        })
        if episode.get("published"):
            tag(item, "pubDate", format_datetime(datetime.fromtimestamp(episode["published"], timezone.utc)))
        if episode.get("duration"):
            tag(item, f"{{{ITUNES}}}duration", int(episode["duration"]))
        tag(item, f"{{{ITUNES}}}episodeType", "full")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
