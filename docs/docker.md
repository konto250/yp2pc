# Linux Dockerでの運用

## 構成

Python 3.12・Node.js 22・yt-dlp・Pillow・FFmpeg・FFprobeをイメージに含めます。アプリは非rootユーザーで動作し、音声と画像はホストの `data/` に永続化します。Docker起動時に自動再開し、コンテナを作り直しても保存ファイルは残ります。

## 初回起動

Linux PCにDocker EngineとComposeを導入済みであることを前提にします。

```bash
git clone https://github.com/konto250/yp2pc.git
cd yp2pc
mkdir -p data
cp .env.docker.example .env
python3 scripts/set_password.py
```

出力された `ADMIN_PASSWORD_HASH=...` を `.env` に設定します。`APP_BASE_URL` と `BIND_ADDRESS` はLinux PCのアドレスに変更し、`APP_UID` / `APP_GID` は `id -u` / `id -g` の結果に合わせます。`data/` はそのユーザーが書き込めるディレクトリを指定してください。

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=50 yp2pc
```

例の設定では `http://192.168.1.121:3001/` を開きます。コンテナ内部は3000番ですが、ホストの既存サービスと衝突しないよう外側を3001番にしています。

## Cloudflare Tunnelを使う

ホスト上で既存のcloudflaredが稼働している場合、そのトンネルに公開ホスト名を追加します。

以下の公開ホスト名は例です。実際に使用するドメインに置き換えてください。

| 設定 | 設定例 |
| --- | --- |
| 公開ホスト名 | `podcast.example.com` |
| サービス種別 | HTTP |
| 接続先 | `192.168.1.121:3001` |
| パス | 空欄 |
| `.env` の `APP_BASE_URL` | `https://podcast.example.com` |
| `.env` の `BIND_ADDRESS` | `192.168.1.121` |

Cloudflare One → Networking → Tunnels（画面によっては Networks → Connectors）から既存トンネルを編集し、Published application routes / Public Hostnamesで登録します。トークンはこのアプリやComposeには渡しません。

ホスト側を `127.0.0.1` だけで待ち受けたい場合は、`BIND_ADDRESS=127.0.0.1` として接続先も `http://127.0.0.1:3001` に合わせます。LANアドレスにだけバインドした状態ではlocalhostからは接続できません。cloudflared自体をDockerで動かしている場合も、そのコンテナのlocalhostを指定しないでください。

設定変更を反映します。

```bash
docker compose up -d
```

公開後の購読URLは `https://podcast.example.com/feed/<プレイリストID>.xml` の形式です。実際のURLは管理画面からコピーしてください。Windows PCの旧URLからホスト名が変わるため、iPadでは新しいURLで番組を追加します。エピソードのGUIDは維持します。

PodcastアプリがRSS・音声・画像を直接取得するため、Cloudflare Accessでサイト全体にログインを要求しないでください。管理画面と追加・削除APIはアプリ自身がパスワードで保護します。

## 保存データの移行

Windows側の `.local/media/` にある `.m4a`・`.jpg`・`.json` をまとめてLinux側の `data/` にコピーします。新規の空ディレクトリへ移すか、既存データをバックアップしてから行ってください。音声を再ダウンロードせず、そのまま再利用します。

サーバー停止中に `data/` をディレクトリごとバックアップすると、音声とメタデータを一致した状態で保存できます。

```bash
docker compose stop
tar -czf "yp2pc-data-$(date +%Y%m%d-%H%M%S).tar.gz" data
docker compose start
```

## 検証・更新・停止

```bash
# コンテナ内で回帰テスト（外部YouTube通信なし）
docker compose exec -T yp2pc python -m unittest discover -s tests -v

# 実際のRSS・音声・画像配信
docker compose exec -T yp2pc python scripts/smoke.py --base http://127.0.0.1:3000

# Gitで配置した場合の更新
git pull --ff-only
docker compose build --pull
docker compose up -d

# 停止（data/のファイルは残る）
docker compose down
```

yt-dlp更新が必要な場合は `docker compose build --pull --no-cache` で依存パッケージを再取得します。

## 今回の実験機

ユーザー名とホームディレクトリは `user` を使った例です。実際の環境に合わせて読み替えてください。

- 接続先：`user@192.168.1.121`（`konto-hdl2`、x86_64）
- 配置先：`/home/user/yp2pc`
- データ：`/home/user/yp2pc/data`
- コンテナ：Composeプロジェクト `yp2pc` のサービス `yp2pc`
- 既存のMisskeyが3000番を使用しているため、ホスト側は3001番
- 初回はWindowsからソースをアーカイブ転送して配置。Git clone配置ではないため、このディレクトリでは現時点で `git pull` は使用しません。
- Windowsの旧実験サーバーは移行確認後に停止。Linux版の起動はWindows PCの稼働に依存しません。

保存データの引継ぎ、LAN内のRSS・音声Range・画像配信、Linuxコンテナからの新規YouTube取得とM4A補正を確認済みです。公開HTTPS経由でも、RSS作成・音声の先頭/中間/末尾の206応答・JPEG配信に成功しました。利用者のiPadで、新しいURLによる登録・再生も確認済みです。

管理画面のパスワード保護とフィード削除機能を反映済みです。38件の回帰テストに加えて、公開HTTPSで未認証の一覧・追加・削除の401、ログイン・ログアウト、認証なしのRSS・音声・画像配信を確認しました。フィード削除時は、ほかのフィードで使っていない保存音声・画像を削除する設定が標準です。

パスワードを変更する場合は `python3 scripts/set_password.py` で新しいハッシュを作り、`.env` の `ADMIN_PASSWORD_HASH` を置き換えて `docker compose up -d` を実行してください。

参考：[Docker Composeの環境変数](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)、[Cloudflare Tunnelの設定](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)
