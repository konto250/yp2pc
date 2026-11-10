"""VercelのビルドでDeno公式バイナリーを検証して同梱します。"""

import hashlib
import io
import platform
import subprocess
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

VERSION = "2.9.8"


def main():
    architecture = "aarch64" if platform.machine() in {"aarch64", "arm64"} else "x86_64"
    archive = f"deno-{architecture}-unknown-linux-gnu.zip"
    base = f"https://github.com/denoland/deno/releases/download/v{VERSION}/{archive}"
    with urlopen(base + ".sha256sum", timeout=60) as response:
        expected = response.read(4096).decode("ascii").split()[0].lower()
    with urlopen(base, timeout=120) as response:
        content = response.read(100 * 1024 * 1024)
    if len(expected) != 64 or hashlib.sha256(content).hexdigest() != expected:
        raise RuntimeError("Denoバイナリーのチェックサムが一致しません。")
    destination = Path(__file__).resolve().parents[1] / "vendor" / "deno"
    destination.parent.mkdir(exist_ok=True)
    with ZipFile(io.BytesIO(content)) as zipped:
        # 書き出すファイル名を固定し、ZIP内のパスを信用しません。
        destination.write_bytes(zipped.read("deno"))
    destination.chmod(0o755)
    subprocess.run([str(destination), "--version"], check=True)
    print("Denoの同梱が完了しました。")


if __name__ == "__main__":
    main()
