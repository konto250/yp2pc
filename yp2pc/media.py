"""YouTubeのDASH音声をPodcast向けの通常のM4Aへ無劣化で組み直します。"""

import hashlib
import json
import math
import os
import shutil
import struct
import subprocess

from yp2pc.core import AppError

MEDIA_VERSION = 1


def executable(name):
    path = os.environ.get(name.upper() + "_BIN") or shutil.which(name)
    if not path:
        raise AppError("音声の補正にはFFmpegとFFprobeが必要です。PATHまたは環境変数を確認してください。", 503, "configuration_error")
    return path


def run(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        raise AppError("音声の補正ツールを実行できませんでした。設定と保存先を確認してください。", 503, "normalization_failed") from None
    if result.returncode:
        raise AppError("音声ファイルを補正できませんでした。元のファイルは保持しています。", 502, "normalization_failed")
    return result.stdout


def progressive_layout(path):
    """音声断片がなく、再生情報がデータより先頭にあることを確認します。"""
    types = []
    length = path.stat().st_size
    with path.open("rb") as source:
        while source.tell() < length:
            start = source.tell()
            header = source.read(8)
            if len(header) != 8:
                return False
            size, kind = struct.unpack(">I4s", header)
            minimum = 8
            if size == 1:
                extra = source.read(8)
                if len(extra) != 8:
                    return False
                size = struct.unpack(">Q", extra)[0]
                minimum = 16
            elif size == 0:
                size = length - start
            if size < minimum or start + size > length:
                return False
            types.append(kind)
            source.seek(start + size)
    return (types.count(b"moov") == 1 and types.count(b"mdat") == 1
            and b"moof" not in types and b"sidx" not in types and b"ftyp" in types
            and types.index(b"moov") < types.index(b"mdat"))


def normalize(source, target, expected_duration=None):
    """完成・検証した一時ファイルと、配信用メタデータを生成します。"""
    ffmpeg, ffprobe = executable("ffmpeg"), executable("ffprobe")
    try:
        run([ffmpeg, "-hide_banner", "-v", "error", "-nostdin", "-y", "-i", str(source),
             "-map", "0:a:0", "-c:a", "copy", "-movflags", "+faststart", "-f", "mp4", str(target)])
        output = run([ffprobe, "-v", "error", "-show_entries",
                      "format=duration:stream=codec_name,codec_type,duration,start_time", "-of", "json", str(target)])
        try:
            probe = json.loads(output)
            streams = probe["streams"]
            duration = float(probe["format"]["duration"])
            track_duration = float(streams[0]["duration"])
            start = float(streams[0].get("start_time", 0))
            if (len(streams) != 1 or streams[0]["codec_name"] != "aac" or streams[0]["codec_type"] != "audio"
                    or not all(math.isfinite(value) for value in (duration, track_duration, start))
                    or duration <= 0 or abs(duration - track_duration) > 1 or abs(start) > 0.1
                    or (expected_duration and abs(duration - float(expected_duration)) > 2)
                    or not progressive_layout(target)):
                raise ValueError
        except (ValueError, TypeError, KeyError, IndexError):
            raise AppError("補正後の音声の長さ・形式を確認できませんでした。元のファイルは保持しています。", 502, "invalid_normalized_audio") from None
        with target.open("rb") as saved:
            digest = hashlib.file_digest(saved, "sha256").hexdigest()
        return {"size": target.stat().st_size, "duration": duration, "sha256": digest,
                "stored": True, "media_version": MEDIA_VERSION}
    except Exception:
        target.unlink(missing_ok=True)
        raise
