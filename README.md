# YP2PC

YouTubeプレイリストをApple Podcastで購読できるRSSに変換する、セルフホスト用Webサービスです。ブラウザでプレイリストURLを入力すると、コピー可能なRSS URLを表示します。

音声と動画サムネイルをサーバーのディスクに保存します。初回の準備後は、音声の再生・シーク時にYouTubeへ再接続しません。Linux DockerまたはWindows PCで動かす実験用の構成です。

## 現在の稼働構成（2026-11-10）

| 項目 | 現在の設定 |
| --- | --- |
| 実行環境 | Linux PC `user@192.168.1.121` のDocker Compose |
| 配置先 | `/home/user/yp2pc` |
| 永続データ | `/home/user/yp2pc/data` |
| 配信経路 | Cloudflare Tunnel → `192.168.1.121:3001` → コンテナ内3000番 |
| 認証 | 管理画面・一覧・追加・削除はパスワード必須。RSS・音声・画像は認証不要 |
| 起動 | Docker Engineの自動起動が有効。コンテナは `unless-stopped` で再開 |

Windowsの旧実験サーバーは停止済みです。現在の配信はWindows PCの稼働に依存しません。初期パスワードの控えはWindows作業ディレクトリの `.local/yp2pc-admin-password.txt`（Git管理外）にあります。変更方法は後述の管理画面設定を参照してください。

Linux側は初回にソースのアーカイブを転送して配置したため、現在の `/home/user/yp2pc` はGit cloneされたディレクトリではありません。更新・バックアップ・停止方法とCloudflare設定の詳細は[Docker運用手順](docs/docker.md)にまとめています。

## iPadから利用する（現行Linux版）

1. 設定した公開URLのWeb管理画面へログインし、YouTubeプレイリストのURLを入力します。
2. 音声の準備完了後、表示されたRSS URLをコピーします。
3. iPadのPodcast →「ライブラリ」→「…」→「番組をURLで追加」に貼り付けます。Podcastアプリへのパスワード設定は不要です。

公開HTTPS URLからの登録・再生はiPad実機で確認済みです。旧Windows版のLAN用URLを登録している場合は、管理画面からコピーしたHTTPS版RSS URLを追加してください。Linux PCとDocker・cloudflaredが動作している間は、配信元と同じLANに接続する必要はありません。

## Linux Dockerで起動

```bash
mkdir -p data
cp .env.docker.example .env
python3 scripts/set_password.py
# 出力されたADMIN_PASSWORD_HASHと、接続先URL・LANアドレス・UID/GIDを.envに設定
docker compose up -d --build
```

音声はホストの `data/` に保存し、コンテナ再作成後も保持します。必要なツールはイメージに同梱します。既存cloudflaredとの接続、Windowsからのデータ移行、実験機の配置先は[Docker運用手順](docs/docker.md)を参照してください。

## Windowsで直接起動する場合

Python 3.12、yt-dlp用のNode.jsまたはDeno、およびFFmpeg・FFprobeを使用します。FFmpeg・FFprobeはPATHに追加してください。

```powershell
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt
./.venv/Scripts/python scripts/set_password.py
# 出力されたハッシュを $env:ADMIN_PASSWORD_HASH に設定してから起動
./.venv/Scripts/python dev.py
```

`http://127.0.0.1:3000/` を開きます。既存のyt-dlp実行ファイルを使う場合は、`YTDLP_BIN`で指定するかPATHに追加してください。画像生成にはPillowが必要です。FFmpegはDASH形式の音声を通常のM4Aに組み直すために使用し、音声の再エンコードは行いません。

## 管理画面のログインとフィード削除

入力画面・登録済みフィード一覧・追加・削除には管理パスワードが必要です。RSS・保存済み音声・画像はパスワードなしで取得できます。既存のPodcast購読設定にパスワードを追加する必要はありません。

`python scripts/set_password.py` でパスワードを入力すると、設定用の `ADMIN_PASSWORD_HASH=...` が出力されます。Dockerでは `.env` に、直接起動では環境変数に設定してください。平文のパスワードはサーバーに保存しません。未設定の場合は管理操作を許可しません。

ログインは12時間有効です。セッションはサーバー側で管理し、ログアウト・コンテナ再起動・パスワード変更後は再ログインが必要です。HTTPSではSecure・HttpOnly・SameSite=StrictのCookieを使用します。

画面の「登録済みフィード」から削除できます。標準では、そのフィードと、ほかの登録済みフィードで使っていない保存音声・画像・エピソード情報を削除します。共有ファイルは残します。チェックを外せばフィードだけ削除できます。削除済みRSSへのアクセスは404になり、勝手に再登録・再取得しません。未登録のRSSや未保存の音声URLから新規取得を始めることもできません。

端末にダウンロード済みの音声や、配信経路に残るキャッシュまでは削除しません。

## WindowsのLAN内配信を試す場合（旧実験構成）

PCとiPadを同じ家庭内ネットワークに接続します。PCは有線でも構いません。ゲストWi-Fiなどで端末間通信が禁止されている場合は接続できません。

1. `ipconfig`でPCのLAN用IPv4アドレスを確認します。
2. アドレスを実際の値に置き換えて、PowerShellで起動します。

```powershell
./scripts/start-lan.ps1 -Address 192.168.1.4
```

3. Windowsファイアウォールに遮断される場合は、管理者PowerShellで限定的な規則を追加します。以下のアドレス、Pythonのパス、インターフェース名は環境に合わせて変更してください。

```powershell
New-NetFirewallRule -Name 'YP2PC-LAN-3000' -DisplayName 'YP2PC LAN 実験 TCP 3000' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3000 -LocalAddress 192.168.1.4 -RemoteAddress LocalSubnet -InterfaceAlias 'イーサネット' -Program 'D:\Python\Python312\python.exe' -Profile Any
```

4. iPadのSafariで `http://192.168.1.4:3000/` を開き、プレイリストからRSSを作成します。初回はダウンロード完了を待ちます。コピーできない場合はURL欄を長押ししてコピーしてください。
5. Podcast →「ライブラリ」→「…」→「番組をURLで追加」にRSS URLを貼り付けてフォローします。

検証用プレイリストは `https://www.youtube.com/playlist?list=PLF119azDj_Og`、このWindows構成での購読URLは `http://192.168.1.4:3000/feed/PLF119azDj_Og.xml` です。エピソードGUIDはLinux版と共通です。音声URLにはファイルのハッシュによる版指定を付け、補正前のキャッシュと区別します。

PCの停止・スリープ中や、外出先では取得できません。PCのIPアドレスが変わると購読先も変わるため、継続利用時はルーターでDHCP予約を設定してください。アプリにダウンロード済みの音声は端末から再生できます。

サーバーは起動したPowerShellでCtrl+Cを押して停止します。実験後に受信規則を削除する場合は、管理者PowerShellで実行します。

```powershell
Remove-NetFirewallRule -Name 'YP2PC-LAN-3000'
```

## 保存と配信

- 既定の保存先は `.local/media/` です。音声M4A、1400×1400のJPEG画像、エピソード情報JSON、フィードの最新スナップショットを保存します。Gitには含めません。
- 初回に音声全体を取得し、バイト数とM4Aヘッダーを確認します。その後FFmpegで音声を再圧縮せず通常のM4Aへ組み直し、FFprobeで長さ・形式を検証してから公開します。再生情報をファイル先頭に配置し、DASHの断片構造は取り除きます。途中の `.part` ファイルは配信しません。旧形式の保存ファイルも利用時に補正し、再ダウンロードしません。
- 音声のHEAD・単一Range・206・416・ETag・If-Rangeに対応します。シーク位置からローカルファイルを直接読み出します。
- サムネイルは動画IDに対応するYouTube画像を取得し、文字などを切り落とさないよう上下または左右に余白を付けて正方形にします。RSSの各エピソードに `itunes:image` を付け、番組画像には画像のある先頭エピソードを使います。画像取得が失敗しても音声は掲載します。
- プレイリストの先頭から最大10件を対象にし、フィード取得時に一覧を更新します（メモリキャッシュ5分）。新しい動画はYouTube側で先頭に並べてください。常駐の定期ダウンロード処理はありません。
- YouTubeの一覧取得に失敗した場合は、保存済みのフィードと音声を返します。正常に取得した一覧に含まれなくなった動画はRSSから外れますが、保存ファイルを自動削除しません。
- 既定の保存上限は5GiB、1件の音声上限は1GiBです。上限時は新規取得を止め、既存ファイルを保持します。容量確認にはファイルと画像用の余裕を含めます。
- ファイルを整理する場合はサーバーを停止し、不要な動画IDの `.m4a`・`.jpg`・`.json` をまとめて削除してください。次回の一覧取得に含まれる動画は再取得されます。

Apple Podcastは画像や音声をキャッシュする場合があります。更新後はフィードを再読み込みし、エピソード詳細や再生画面で確認してください。音声が補正前のままの場合は、対象エピソードのダウンロードを削除して再取得してください。番組のフォローを解除する必要はありません。

## 設定

`dev.py`の直接起動では`.env`を自動読み込みしないため、環境変数か起動引数で指定します。Docker Composeでは`.env.docker.example`を`.env`へコピーし、Composeが設定を読み込みます。

| 環境変数 | 用途 |
| --- | --- |
| `APP_BASE_URL` | iPadから接続する固定オリジン。例：`http://192.168.1.4:3000`。HTTPSも使用可。パスは含めません。 |
| `ADMIN_PASSWORD_HASH` | 管理パスワードのscryptハッシュ。`scripts/set_password.py`で生成。 |
| `MEDIA_DIR` | 保存ディレクトリ。既定はプロジェクトの `.local/media`。 |
| `MEDIA_MAX_BYTES` | 保存上限のバイト数。既定5368709120（5GiB）。 |
| `MAX_EPISODES` | 一覧の先頭から取得する件数。既定10、1～10。 |
| `YTDLP_BIN` | 既存のyt-dlp実行ファイルへのパス。未指定ならPythonパッケージ、次にPATH上のコマンドを使用。 |
| `FFMPEG_BIN` / `FFPROBE_BIN` | 音声補正用の実行ファイル。未指定ならPATHから検索。 |

起動時は `--host`、`--port`、`--base-url` を指定できます。LAN用HTTPは明示設定したプライベートIPv4・ループバックに限定します。

## 検証

```powershell
python -X utf8 -m unittest discover -s tests -v
node --check public/app.js
python -X utf8 scripts/smoke.py --base http://192.168.1.4:3000
```

スモーク検証は登録済みRSS、音声HEAD、先頭・中間・末尾の部分取得、画像を認証なしで確認します。新規登録も検証する場合は `--create` を付けて管理パスワードを入力します。

2026-11-10に旧中継型でiPadのRSS登録・再生を利用者が確認済みです。保存型では同じ音声26,592,765バイトと1400×1400のJPEGを保存し、RSS画像タグ・画像配信・音声HEAD・先頭/中間/末尾のRange取得を確認しました。PC上から測定した1024バイトのRange応答は約2～15msで、FFmpegで20分位置へシークしてから10秒デコードする検証にも成功しています。画像の配信成功は確認済みですが、iPadでのサムネイル表示については明示的な確認回答をまだ得ていません。

同日のiPad実機確認で、DASH形式をそのまま保存した音声に「長さが約2倍・後半が無音」の報告がありました。保存後のコンテナー補正を追加し、既存ファイルも無劣化で移行しました。修正対象は165個の断片を持つM4Aから通常のM4Aになり、長さ1643.113651秒、サイズ26,573,969バイトです。補正前後のAAC音声データのSHA-256は一致しています。DASH形式の生成・補正・長さ・音声データ同一性の回帰テストを追加しました。利用者のiPadで27分23秒になり、末尾の余分な無音が解消したことを確認済みです。

その後、Linux Dockerへのデータ移行、コンテナからの新規YouTube取得・M4A補正、コンテナ再作成後のデータ再利用、公開HTTPS経由の配信を検証しました。利用者のiPadでも、新しいHTTPS URLでの登録・再生を確認済みです。

現在の回帰テストは38件で、WindowsとLinuxコンテナの両方で成功しています。公開HTTPSでは未ログインの管理APIが401となること、ログイン・ログアウト、認証なしのRSS・音声・画像配信を確認しました。削除の回帰テストでは、共有ファイルの保持、未共有ファイルの削除、削除済みフィードが公開URLから復活しないことを確認しています。

## 構成変更の経緯

1. 当初はVercel上で音声を保存せず中継する構成を試しましたが、YouTube側のbot判定で音声取得が拒否されました。Vercel専用ファイルは削除し、Git連携による自動デプロイも解除済みです。
2. Windows PCでLAN内配信を実験し、シークの遅さを改善するため音声・画像の保存型へ変更しました。
3. M4Aの長さが2倍になる症状に対し、DASH形式を通常のM4Aへ無劣化で補正する処理を追加しました。
4. Linux Dockerと既存Cloudflare Tunnelへ移行し、管理画面の認証とフィード削除を追加しました。

## 制約

- 公開動画のうちHTTPS M4Aを取得できるものが対象です。非公開・ログイン必須・年齢制限・ライブ配信中には対応しません。
- 初回のYouTube取得は送信元IPの制限や仕様変更の影響を受けます。yt-dlpの更新が必要になる場合があります。
- 初回は音声全体を保存するため時間がかかります。個人向けの単一プロセスとしてダウンロード・フィード操作は直列化しています。複数プロセスや多数利用者向けのキュー・ユーザー別アカウント・容量管理UIはありません。
- 現在は簡易HTTPサーバーをDocker内で動かし、Cloudflare Tunnel経由で実験公開しています。多人数向けの本番運用構成は未整備です。
- Docker版はDocker Engine起動時に再開します。Windowsで直接起動する版の自動起動は未設定です。
- カタログ申請ではなく、アプリへのURL直接登録用です。`itunes:block=Yes`、`itunes:explicit=true`を設定します。
- 利用できる権利・許可のあるコンテンツを対象にしてください。

## 参考資料

- [Apple PodcastのRSS要件](https://podcasters.apple.com/support/823-podcast-requirements)
- [Apple Podcastのエピソード画像仕様](https://podcasters.apple.com/support/5516-episode-art-template)
- [yt-dlpのJavaScript実行環境](https://github.com/yt-dlp/yt-dlp/wiki/EJS)
- [yt-dlpのM4A DASH補正処理](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/postprocessor/ffmpeg.py#L785-L790)
