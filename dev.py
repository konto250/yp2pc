"""ローカル開発用。python dev.py で起動します。"""

import argparse
from http.server import ThreadingHTTPServer

from api.index import handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YP2PCのローカルサーバー")
    parser.add_argument("--port", type=int, default=3000)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"YP2PC: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
