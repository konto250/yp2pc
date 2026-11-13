"""保存済み音声から、Podcastで配信できるAMラジオ風音声を作ります。"""
from yp2pc.media import executable, normalize, run

RADIO_VERSION = 1
# 帯域制限、滑らかなクリッピング、控えめなヒスノイズを組み合わせます。
# ノイズを無限生成しても、元音声の終了で必ずミックスを止めます。
FILTER = (
    '[0:a:0]aformat=channel_layouts=mono,aresample=22050,'
    'highpass=f=250:p=2,lowpass=f=3500:p=2,volume=2,'
    'asoftclip=type=tanh:threshold=0.35:output=0.8,lowpass=f=3500:p=2[voice];'
    'anoisesrc=r=22050:a=0.008:color=white:seed=1979,'
    'highpass=f=800:p=2,lowpass=f=4000:p=2[noise];'
    '[voice][noise]amix=inputs=2:duration=first:normalize=0,volume=0.9[out]'
)


def convert(source, target, duration):
    encoded = target.with_suffix('.encode.part')
    try:
        run([executable('ffmpeg'), '-hide_banner', '-v', 'error', '-nostdin', '-y',
             '-i', str(source), '-filter_complex_threads', '1', '-filter_complex', FILTER,
             '-map', '[out]', '-c:a', 'aac', '-b:a', '48k', '-ac', '1', '-ar', '22050',
             '-threads', '1', '-movflags', '+faststart', '-f', 'mp4', str(encoded)], timeout=600)
        return {**normalize(encoded, target, duration), 'radio_version': RADIO_VERSION}
    finally:
        encoded.unlink(missing_ok=True)
