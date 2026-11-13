"""ローカル開発用。python dev.py で起動します。"""

import argparse
import os
from http.server import ThreadingHTTPServer

from api.index import handler
from yp2pc.core import AppError, base_url
from yp2pc import refresh


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YP2PCのローカルサーバー")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--host", default="127.0.0.1", help="待受アドレス。LAN実験ではPCのIPv4アドレス")
    parser.add_argument("--base-url", help="iPadから接続するURL。例: http://192.168.1.4:3000")
    args = parser.parse_args()
    if args.base_url:
        os.environ["APP_BASE_URL"] = args.base_url
    try:
        origin = base_url(f"{args.host}:{args.port}")
    except AppError as error:
        parser.error(str(error))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    refresh_stop = refresh.start()
    print(f"YP2PC: {origin}", flush=True)
    print("終了: Ctrl+C。PCの停止・スリープ中はRSSと音声を取得できません。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        refresh_stop.set()
        server.server_close()
