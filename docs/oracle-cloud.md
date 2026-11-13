# Oracle Cloudへの移行

既存のLinux環境から、保存済み音声・画像・フィードと管理パスワード設定をOracle Cloud VMへ引き継ぎます。アプリと `cloudflared` はDocker Composeで動かします。

**2026-11-13に公開配信をOCIへ切り替えました。** YouTubeへの直接取得は解決しなかったため、自宅プロキシとSSH逆方向トンネルを使います。現在の接続先・起動方法・停止時の挙動は[自宅プロキシ＋OCI配信](home-proxy.md)を参照してください。以下の直接取得の失敗と基本構成は、切替前の検証・移行準備の記録です。

公開ドメイン、ユーザー名、パス、SSH接続先は例示に置き換えています。秘密鍵、実際の `.env`、Tunnelトークン、保存データはGitに追加しません。

## 移行準備の検証結果（2026-11-13）

Oracle Linux 9.8 / ARM64へDocker Engine 29.9.3とCompose 5.7.1を導入し、アプリとcloudflared 2026.11.0の起動を確認しました。DockerはOS起動時に自動起動し、アプリのホスト側ポートは公開していません。

- 保存データ4ファイルは、旧サーバーで停止中に取得したバックアップとSHA-256が一致しました。
- Oracleのコンテナで38件の回帰テストが成功しました。
- 内部HTTPのRSS、音声HEAD、先頭・中間・末尾の206応答、JPEG配信を確認しました。
- 新規のプレイリスト一覧取得は成功しましたが、音声取得はYouTubeのbot判定で拒否されました。同じ動画は旧サーバーの一時保存先で取得・M4A補正できています。
- その後VMにグローバルIPv6を割り当て、IPv6のデフォルトルートとYouTubeへのHTTPS接続（HTTP 200）を確認しました。ホストのIPv6経路を使う一時コンテナで `yt-dlp --force-ipv6` を実行しましたが、同じ動画の音声取得は引き続きbot判定で拒否されました。このVMではIPv6への変更だけでは解消していません。
- YouTubeのログインCookieを一時コンテナへ渡す検証では、bot判定を通過して音声情報を取得できました。しかし音声本体は、アプリのRange取得とyt-dlp標準取得の両方で失敗し、標準取得ではIPv4・IPv6ともHTTP 403でした。Cookie失効の警告は出ていません。CookieとPO Tokenプロバイダー（bgutil 2.0.2、mweb）を組み合わせた試行も403でした。追加の `--verbose` 検証（yt-dlp 2026.10.26）では、HTTPプロバイダーの読み込み、mweb用gvsトークンの生成要求と応答、音声リクエストの `pot` パラメーターへの付与を確認しましたが、ダウンロードはHTTP 403で失敗しました。プラグインの未動作ではなく、トークン付与後も拒否される状態であり、拒否理由の特定には至っていません。検証後は一時コンテナ・ネットワークと移行先のCookieコピーを削除しました。HLS形式の追加検証は未実施です。Cookie対応・追加プロバイダーは本番構成に組み込んでいません。
- 同じCookie・IPv4・動画で `tv` クライアントも検証しました。YouTubeが `The page needs to be reloaded.` を返し、音声リクエスト前に停止しました。POトークンの生成・付与はありませんでしたが、`tv` は通常POトークン不要であり、生成されないことを異常とは判断していません。停止理由の詳細は未特定です。検証用コンテナ・ネットワーク・移行先のCookieコピーは削除済みです。
- 移行準備時点で新しいTunnelは4接続とも確立しました。その後、対象の公開ルートとDNSをOCIへ切り替えました。

自宅経由ではCookieなしの新規取得・M4A補正に成功しました。旧配信アプリを停止した状態で、公開HTTPSのRSS、音声の全体ハッシュとHEAD・Range、画像、管理ログイン・一覧・既存プレイリスト再登録を確認しました。自宅のプロキシと共有Tunnelは継続しています。

## 配信構成

```text
Podcast / ブラウザ → Cloudflare → cloudflared → http://yp2pc:3000
                                               ↓
                                         ホストの data/
```

`compose.cloud.yaml` を既存の `compose.yaml` に重ねます。アプリのホスト側ポートを削除し、同じDockerネットワークの `cloudflared` から接続します。Cloudflare側のサービスURLは `http://yp2pc:3000` です。コンテナ内の `localhost` は使用しません。

移行元と同じ `APP_BASE_URL` とフィードデータを使えば、購読URL・エピソードGUIDを維持できます。管理画面・管理APIは従来どおりパスワード必須、RSS・音声・画像は認証不要です。

## 移行先の準備

1. OS、CPUアーキテクチャ、空き容量を確認し、そのOSに対応するDocker EngineとComposeプラグインを導入します。`!reset` に対応するComposeを使い、以下の構成検証が成功することを確認します。
2. SSHは管理端末から接続できるようにします。アプリ用の80・443・3000・3001番の受信許可は不要です。TunnelにはCloudflareへ向けた7844番の送信接続が必要です。YouTube取得・イメージ取得用のHTTPS通信とDNSも許可します。
3. ソースを `~/yp2pc` に配置し、作業ユーザーで次を実行します。

```bash
cd ~/yp2pc
mkdir -p data .local
chmod 700 .local
cp .env.cloud.example .env
chmod 600 .env
id -u
id -g
```

`.env` の `APP_BASE_URL`、`ADMIN_PASSWORD_HASH`、保存上限・対象件数は移行元から引き継ぎ、`APP_UID` と `APP_GID` は移行先の作業ユーザーに合わせます。`COMPOSE_FILE` は両ファイルを指定したままにします。`data/` の所有者もこのUID/GIDに合わせてください。SELinux対応のため、この構成ではデータとトークンの専用パスに `Z` ラベルを使用します。

アーカイブでソースを配置する場合、ソースファイルは644、ソースディレクトリは755など、コンテナの非rootユーザーが読み取れる権限にします。`.env` とトークンは600のまま保持します。厳しいumaskで展開したソースをそのままCOPYすると、コンテナ内で権限不足になる場合があります。

```bash
docker compose config --quiet
docker compose up -d --build --wait yp2pc
```

この段階では `cloudflared` を起動せず、公開経路は旧サーバーのままにします。既存トンネルが他サービスにも使われている場合、Oracle VM用の専用トンネルを作ります。同じトークンで別ホストを接続するとレプリカとなり、旧トンネル全体の配信先に影響するためです。

## データのコピーと検証

旧サーバーの `data/` を別途バックアップし、全ファイルを移行先へコピーします。最終コピーの間は旧アプリを停止して書き込みを止めます。旧ホストの共有 `cloudflared` は停止しません。移行先も復元中はアプリを停止してください。

データにはM4A、JPEG、エピソード情報JSON、登録済みフィードのスナップショットが含まれます。復元後に相対パス・サイズ・SHA-256を照合し、移行先のUID/GIDで読み書きできることを確認します。最終切替まで旧環境を再開した場合は、切替直前にもう一度更新分を同期します。

```bash
docker compose up -d --wait yp2pc
docker compose exec -T yp2pc python -m unittest discover -s tests -v
docker compose exec -T yp2pc python scripts/smoke.py --base http://127.0.0.1:3000
```

保存済みファイルの配信成功だけでは、新規動画を取得できることは確認できません。切替前に、Oracle VMの送信元IPからYouTubeの一覧取得・音声取得・M4A補正を、検証用の別保存先で試します。クラウドのIPがYouTube側に拒否される場合があるため、ここで失敗したら公開先を切り替えず原因を確認します。

## Tunnelと公開先の切替

CloudflareでOracle VM用トンネルを作成し、そのトークンをVMの `.local/cloudflared-token` に保存します。以下はBashで実行します。貼り付けるのはトークンだけです。

```bash
umask 077
read -r -s -p 'Tunnelトークン: ' tunnel_token
printf '\n'
printf '%s' "$tunnel_token" > .local/cloudflared-token
unset tunnel_token
chmod 600 .local/cloudflared-token
docker compose up -d
docker compose ps
```

トークンファイルの所有者は `APP_UID` / `APP_GID` と合わせます。トークンはコマンド引数や環境変数としてコンテナへ渡さず、読み取り専用ファイルで渡します。

Cloudflareで新コネクターの接続を確認し、既存の公開ホスト名の配信先をこのトンネルへ移します。サービスはHTTP、URLは `yp2pc:3000`、パスは空欄です。同名のDNSレコードを重複作成せず、既存レコードとルートを新トンネルへ切り替えます。変更前のルート・DNS設定はGit管理外に控えます。

切替後は公開HTTPSで管理画面ログイン、RSS、音声のHEAD・Range・シーク、画像を確認します。iPadでは既存の購読をそのまま使って更新・再生を確認します。新しいURLでの再登録は不要です。

公開経路の確認後、旧アプリを停止します。旧データとバックアップは動作が安定するまで保持します。旧ホストの共有Tunnelと他サービスはそのまま動かします。

## 切り戻し・運用

新規動画の取得失敗、音声・RSS配信失敗、管理画面にログインできないなどの場合は、旧アプリを再開して公開ホスト名のルート・DNSを控えた旧設定へ戻します。切替後にOracle側でフィードを追加・削除していた場合は、両環境を停止して最新データを退避・同期してから戻してください。

更新・再起動は、`.env` の `COMPOSE_FILE` が両構成を指定している状態で行います。`docker compose -f compose.yaml` だけで起動するとクラウド用の設定が外れるため使用しません。

```bash
docker compose up -d --build --wait
docker compose ps
docker compose stop
```

Docker EngineはOS起動時に自動起動させます。両コンテナは `unless-stopped` で再開します。バックアップには `data/`、`.env`、Tunnel設定を含め、秘密を含むバックアップは公開しません。

## 参考

- [Docker Composeの設定統合とポートの削除](https://docs.docker.com/reference/compose-file/merge/)
- [Cloudflare Tunnelの接続とレプリカ](https://developers.cloudflare.com/tunnel/configuration/)
- [cloudflaredの実行パラメーター](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/)
