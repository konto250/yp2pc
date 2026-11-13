"""実音声の帯域・ノイズ・長さ、および保存済みAM音声の再利用を検証します。"""
import array
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from yp2pc import radio, storage
from yp2pc.core import AppError
from yp2pc.media import run, progressive_layout


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpegが必要です。')
class RadioAudioTests(unittest.TestCase):
    def test_band_limit_noise_duration_and_original_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'original.wav', Path(folder) / 'am.m4a'
            signal = 'aevalsrc=if(lt(t\\,3)\\,0.12*(sin(2*PI*80*t)+sin(2*PI*1000*t)+sin(2*PI*8000*t))\\,0):s=44100:d=4'
            run([shutil.which('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i', signal, str(source)])
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            details = radio.convert(source, target, 4)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            self.assertAlmostEqual(details['duration'], 4, delta=0.1)
            self.assertTrue(progressive_layout(target))
            probe = json.loads(run([shutil.which('ffprobe'), '-v', 'error', '-show_entries',
                                    'stream=channels,sample_rate,codec_name', '-of', 'json', str(target)]))['streams'][0]
            self.assertEqual((probe['channels'], probe['sample_rate'], probe['codec_name']), (1, '22050', 'aac'))
            decoded = subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-i', str(target),
                                      '-f', 'f32le', '-acodec', 'pcm_f32le', '-'], capture_output=True, check=True, timeout=20).stdout
            samples = array.array('f', decoded)
            section = samples[22050:44100]
            def amplitude(frequency):
                return abs(sum(value * complex(math.cos(2*math.pi*frequency*n/22050),
                                               math.sin(2*math.pi*frequency*n/22050)) for n, value in enumerate(section)))
            self.assertLess(amplitude(80), amplitude(1000) * 0.15)
            self.assertLess(amplitude(8000), amplitude(1000) * 0.08)
            # 元の無音部分に小さなノイズがあり、終了後に長い無音・ノイズが追加されません。
            tail = samples[int(3.2*22050):int(3.8*22050)]
            rms = math.sqrt(sum(v*v for v in tail) / len(tail))
            self.assertGreater(rms, 0.0001)
            self.assertLess(rms, 0.01)
            self.assertLess(max(abs(v) for v in samples), 0.95)
            self.assertLess(len(samples)/22050, 4.15)


class RadioStorageTests(unittest.TestCase):
    def test_cache_invalidation_and_failed_conversion_preserves_original(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'MEDIA_DIR': folder}):
            identifier = 'TbalaZ5EhYA'
            source = storage.media_path(identifier)
            source.write_bytes(b'original')
            metadata = {'id': identifier, 'size': 8, 'duration': 10, 'sha256': 'first'}
            storage.write_json(storage.media_path(identifier, '.json'), metadata)
            def convert(source, target, duration):
                target.write_bytes(b'am-audio')
                return {'size': 8, 'sha256': 'am-first', 'duration': 10, 'radio_version': radio.RADIO_VERSION}
            with patch.object(radio, 'convert', side_effect=convert) as conversion:
                storage.prepare_am_episode(identifier)
                storage.prepare_am_episode(identifier)
                self.assertEqual(conversion.call_count, 1)
            metadata['sha256'] = 'changed'
            storage.write_json(storage.media_path(identifier, '.json'), metadata)
            self.assertIsNone(storage.read_am_episode(identifier))
            with patch.object(radio, 'convert', side_effect=AppError('変換失敗', 502)):
                with self.assertRaises(AppError):
                    storage.prepare_am_episode(identifier)
            self.assertEqual(source.read_bytes(), b'original')
            self.assertEqual(storage.media_path(identifier, '.am.m4a').read_bytes(), b'am-audio')
            self.assertFalse(storage.media_path(identifier, '.am.m4a').with_suffix('.m4a.part').exists())
