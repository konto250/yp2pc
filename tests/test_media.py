"""実際のFFmpegでDASH音声の構造・長さ・音声データ保持を検証します。"""

import shutil
import tempfile
import unittest
from pathlib import Path

from yp2pc.core import AppError
from yp2pc.media import normalize, progressive_layout, run


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpegとFFprobeが必要です。")
class MediaTests(unittest.TestCase):
    def test_fragmented_audio_is_normalized_without_changing_aac(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fragmented.m4a"
            target = Path(directory) / "normalized.m4a"
            run([shutil.which("ffmpeg"), "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                 "sine=frequency=440:duration=2", "-c:a", "aac", "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                 "-f", "mp4", str(source)])
            self.assertFalse(progressive_layout(source))
            metadata = normalize(source, target, 2)
            self.assertTrue(progressive_layout(target))
            self.assertAlmostEqual(metadata["duration"], 2, delta=0.1)
            self.assertEqual(metadata["size"], target.stat().st_size)
            self.assertEqual(metadata["media_version"], 1)

            def audio_hash(path):
                return run([shutil.which("ffmpeg"), "-v", "error", "-i", str(path),
                            "-map", "0:a:0", "-c:a", "copy", "-f", "hash", "-hash", "sha256", "-"])

            self.assertEqual(audio_hash(source), audio_hash(target))
            with self.assertRaises(AppError) as error:
                normalize(source, target, 200)
            self.assertEqual(error.exception.code, "invalid_normalized_audio")
            self.assertFalse(target.exists())
            self.assertTrue(source.exists())
