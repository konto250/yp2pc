# 自宅経由で取得し、OCIから配信する

管理画面、RSS、音声・画像の保存と配信をOCIで動かします。YouTubeへの一覧・音声・画像取得だけを自宅のHTTPプロキシへ通します。ログインCookieとPO Tokenプラグインは使用しません。

```text
Podcast → Cloudflare → OCIのcloudflared → OCIアプリ → OCIのdata/
                                            ↓ 新規取得・更新
                                  127.0.0.1:18888
                                            ↓ SSH逆方向トンネル
                                     自宅のTinyproxy → YouTube
```

SSH接続は自宅からOCIへ開始します。自宅がMAP-E環境でも、自宅へのポート開放や外部からの着信接続は不要です。自宅のDocker構成はプロキシとSSHクライアントの2コンテナです。既存の共有cloudflaredには変更を加えません。

## 自宅Linux

ソースを配置し、転送専用鍵と設定を作成します。個人用のSSH秘密鍵をコピーする必要はありません。

```sh
mkdir -p .local
chmod 700 .local
ssh-keygen -t ed25519 -N '' -C yp2pc-home-proxy -f .local/home-proxy-key
cp deploy/home-proxy/env.example .local/home-proxy.env
chmod 600 .local/home-proxy-key .local/home-proxy.env
```

`.local/home-proxy.env` のOCI接続先・ユーザーを指定します。確認済みのOCIホスト公開鍵を `.local/oci-known-hosts` に保存し、ホスト鍵検証を有効にしたまま使います。秘密鍵は自宅に残し、`.pub` ファイルだけをOCIへ渡します。

OCIの接続ユーザーの `~/.ssh/authorized_keys` に、以下の制限を付けた公開鍵を追加します。既存の鍵を上書きしないでください。

```text
restrict,port-forwarding,permitlisten="127.0.0.1:18888",permitopen="invalid.invalid:1",command="/bin/false" ssh-ed25519 公開鍵 yp2pc-home-proxy
```

逆方向転送の待受はループバックの18888番だけです。シェル・コマンド実行は禁止し、通常方向の転送先は解決不能な `.invalid` 名に制限します。`permitopen` にポート0を指定すると鍵設定全体が拒否されるため使いません。OCIのSSHサーバーはTCP転送を許可する必要がありますが、`GatewayPorts no` のままで構いません。

```sh
docker compose --env-file .local/home-proxy.env -f compose.home-proxy.yaml up -d --build --wait
docker compose --env-file .local/home-proxy.env -f compose.home-proxy.yaml ps
```

プロキシのホスト側ポートは公開しません。許可先はYouTube・Google Video・動画画像のドメインとYouTube APIだけで、CONNECTは443番だけを許可します。設定は `deploy/home-proxy/` にあります。トンネルが切れた場合はSSHの生存確認とDockerの再起動設定で再接続します。

## OCI

既存の保存データ、管理パスワードのハッシュ、公開URL、専用Cloudflare Tunnelを引き継ぎます。`.env` の構成ファイル指定を変更します。

```dotenv
COMPOSE_FILE=compose.yaml:compose.cloud.yaml:compose.oci-proxy.yaml
FEED_REFRESH_SECONDS=900
```

```sh
docker compose config --quiet
docker compose up -d --build --wait
docker compose ps
```

この構成はLinuxのホストネットワークを使い、アプリは **127.0.0.1:3001** だけで待ち受けます。CloudflareのOCIトンネルに設定する公開アプリの接続先は **HTTP / 127.0.0.1:3001** です。従来のDocker内部名 `yp2pc:3000` はこの構成では使いません。公開ホスト名とDNSの向き先を、対象サービスに限ってOCIのトンネルへ変更します。

アプリの `http_proxy` / `https_proxy` は `http://127.0.0.1:18888` です。yt-dlpとPythonの音声・画像取得に適用されます。トンネル切断時は取得エラーとなり、OCIからの直接取得へフォールバックしません。Cloudflareへの接続にはこのプロキシを設定しません。

## 自宅が停止した場合

- OCIに保存済みのRSS・音声・画像は配信を継続します。Podcastの再生・シークに自宅は不要です。
- 新しいプレイリストの取得や未保存エピソードの追加は、自宅とトンネルの復旧までできません。
- 登録済みフィードは900秒間隔で更新します。RSSアクセスは更新の完了を待たず、保存済みの内容を返します。更新に失敗しても前の内容を保持します。
- `FEED_REFRESH_SECONDS=0` は従来のRSSアクセス時更新に戻す設定です。自宅停止中も待たずに配信する運用では正の値を使ってください。

管理画面と管理APIのパスワード保護、公開RSS・音声・画像、フィード削除時の共有ファイル保護は従来どおりです。

## 検証済み（2026-11-13）

- OCIから自宅プロキシ経由で、Cookieなしのプレイリスト・音声取得とM4A補正に成功しました（検証動画1件、約23秒）。
- OCI常駐アプリのRSS、画像、音声の先頭・中間・末尾のRange応答を確認しました。
- トンネルを実際に停止し、保存済みRSSの約0.05秒での応答、音声・画像の継続配信を確認しました。urllibとyt-dlpの新規取得は失敗し、直接取得への切替はありませんでした。トンネルは再開済みです。
- 許可対象外のドメインへのCONNECTは403で拒否されました。
- WindowsとOCIの両方で41件のテストが成功しました。
- 対象の公開アプリルートをOCIへ作成後、既存DNSレコードもOCIトンネルへ変更しました。ルート作成だけでは既存DNSの向き先は変更されませんでした。
- 自宅の旧配信アプリを停止した状態で、公開HTTPSのRSS、音声のHEAD・3箇所のRange・全体SHA-256一致、JPEG、管理APIのログイン・一覧・既存プレイリスト再登録・ログアウトを確認しました。購読URLと管理パスワードは引き継いでいます。
- CloudflareはPython標準User-Agentのリクエストをエラー1010で拒否したため、公開検証には用途を明示した `YP2PC-deployment-check/1.0` を使いました。Cloudflareのセキュリティ設定は変更していません。

## 停止・切り戻し

自宅プロキシだけの停止・再開は次のコマンドで行います。

```sh
docker compose --env-file .local/home-proxy.env -f compose.home-proxy.yaml stop
docker compose --env-file .local/home-proxy.env -f compose.home-proxy.yaml start
```

OCI側のバックアップ対象は `data/`、`.env` とCloudflare Tunnelの設定・秘密ファイルです。自宅側の専用SSH鍵も安全に保管します。公開経路を旧サーバーへ戻す場合、OCIで登録・削除した変更を失わないよう、両アプリを停止して最新データを同期してから、旧アプリの起動と対象ホスト名のルート・DNSの復元を行います。共有トンネル全体は停止しません。
