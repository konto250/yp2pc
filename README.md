# YP2PC

YouTubeプレイリストをApple Podcastで購読できるRSSに変換する、セルフホスト用Webサービスです。ブラウザでプレイリストURLを入力すると、コピー可能なRSS URLを表示します。

音声と動画サムネイルをサーバーのディスクに保存します。初回の準備後は、音声の再生・シーク時にYouTubeへ再接続しません。現在はWindows PCと同じLAN内のiPadで使う実験用の構成です。

## 起動

Python 3.12、yt-dlp用のNode.jsまたはDeno、およびFFmpeg・FFprobeを使用します。FFmpeg・FFprobeはPATHに追加してください。

```powershell
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt
./.venv/Scripts/python dev.py
```

`http://127.0.0.1:3000/` を開きます。既存のyt-dlp実行ファイルを使う場合は、`YTDLP_BIN`で指定するかPATHに追加してください。画像生成にはPillowが必要です。FFmpegはDASH形式の音声を通常のM4Aに組み直すために使用し、音声の再エンコードは行いません。

## iPadから利用する

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

検証用プレイリストは `https://www.youtube.com/playlist?list=PLF119azDj_Og`、購読URLは `http://192.168.1.4:3000/feed/PLF119azDj_Og.xml` です。RSS URLとエピソードGUIDは維持します。音声URLにはファイルのハッシュによる版指定を付け、補正前のキャッシュと区別します。

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

`.env.example` は説明用です。`.env`を自動読み込みしないため、PowerShellの環境変数か起動引数で指定します。

| 環境変数 | 用途 |
| --- | --- |
| `APP_BASE_URL` | iPadから接続する固定オリジン。例：`http://192.168.1.4:3000`。HTTPSも使用可。パスは含めません。 |
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

スモーク検証は実プレイリストを取得し、RSS、音声HEAD、先頭・中間・末尾の部分取得、画像を確認します。初回は音声と画像がサーバーに保存されます。

2026-11-10に旧中継型でiPadのRSS登録・再生を利用者が確認済みです。保存型では同じ音声26,592,765バイトと1400×1400のJPEGを保存し、RSS画像タグ・画像配信・音声HEAD・先頭/中間/末尾のRange取得を確認しました。PC上から測定した1024バイトのRange応答は約2～15msで、FFmpegで20分位置へシークしてから10秒デコードする検証にも成功しています。保存型への切替後のiPad上の操作感・画像表示は別途確認します。

同日のiPad実機確認で、DASH形式をそのまま保存した音声に「長さが約2倍・後半が無音」の報告がありました。保存後のコンテナー補正を追加し、既存ファイルも無劣化で移行しました。修正対象は165個の断片を持つM4Aから通常のM4Aになり、長さ1643.113651秒、サイズ26,573,969バイトです。補正前後のAAC音声データのSHA-256は一致しています。DASH形式の生成・補正・長さ・音声データ同一性の回帰テストを追加しました。iPadでの症状解消は再確認待ちです。

## 制約

- 公開動画のうちHTTPS M4Aを取得できるものが対象です。非公開・ログイン必須・年齢制限・ライブ配信中には対応しません。
- 初回のYouTube取得は送信元IPの制限や仕様変更の影響を受けます。yt-dlpの更新が必要になる場合があります。
- 初回は音声全体を保存するため時間がかかります。個人向けの単一プロセスとしてダウンロードは直列化しています。複数プロセスや多数利用者向けのキュー・認証・容量管理UIはありません。
- `dev.py`は家庭内実験用の簡易HTTPサーバーです。インターネット公開・本番運用の構成は未確定です。
- PC再起動時の自動起動は未設定です。
- カタログ申請ではなく、アプリへのURL直接登録用です。`itunes:block=Yes`、`itunes:explicit=true`を設定します。
- 利用できる権利・許可のあるコンテンツを対象にしてください。

## 参考資料

- [Apple PodcastのRSS要件](https://podcasters.apple.com/support/823-podcast-requirements)
- [Apple Podcastのエピソード画像仕様](https://podcasters.apple.com/support/5516-episode-art-template)
- [yt-dlpのJavaScript実行環境](https://github.com/yt-dlp/yt-dlp/wiki/EJS)
- [yt-dlpのM4A DASH補正処理](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/postprocessor/ffmpeg.py#L785-L790)
