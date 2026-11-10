"""管理パスワードから設定用ハッシュを作ります。平文は表示しません。"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from yp2pc.auth import password_hash

if __name__ == "__main__":
    password = getpass.getpass("新しい管理パスワード（12文字以上）: ")
    if len(password) < 12 or len(password.encode("utf-8")) > 1024:
        raise SystemExit("12文字以上、UTF-8で1024バイト以内で指定してください。")
    if password != getpass.getpass("確認のため再入力: "):
        raise SystemExit("パスワードが一致しません。")
    print("ADMIN_PASSWORD_HASH=" + password_hash(password))
