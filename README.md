# YP2PC

YouTubeプレイリストのURLから、Apple Podcastsなどで直接購読するRSSフィードを発行するWebサービスです。VercelまたはローカルPCで動作し、音声ファイル・データベース・Blobストレージを使いません。

**実験的な音声中継方式です。** YouTubeがVercelの送信元IPを拒否する場合や、M4A音声を取得できない動画では再生に失敗します。ローカルで取得できてもVercelで取得できる保証はありません。Apple Podcastsアプリ内での購読・再生は本番デプロイ後に確認してください。

2026-11-10の実測では、Vercelの本番環境で指定プレイリストの音声取得が「ログインして bot ではないことを確認してください」で拒否されました。同じ動画はWindows PCからRSS生成・音声の部分取得・FFmpegによる15秒のデコードに成功しています。iPadアプリでの購読・再生は別途実機確認が必要です。

## 使い方

1. 公開YouTubeプレイリストのURLを入力し、「RSSを作成」を押します。
2. 表示されたRSS URLをコピーします。画面からエピソードを試聴することもできます。
3. Apple Podcastsで「ライブラリ」のメニューから「URLで番組を追加」を選びます。Macでは「ファイル」→「URLで番組を追加」です。

RSSのURLは `/feed/<プレイリストID>.xml` で固定です。アプリがRSSを更新するとプレイリストを再確認します。先頭から最大10件が対象なので、YouTube側で新しい動画を先頭に並べてください。削除された動画の音声は保持しません。

カタログへの番組申請ではなく、アプリへのURLによる直接購読が対象です。RSSには `itunes:block=Yes` を設定しています。内容の明示的判定は行わず、`itunes:explicit=true` としています。

## 構成

```text
ブラウザ ── プレイリストURL ──→ Vercel Python Function
                                  │ yt-dlpで一覧・音声情報を取得
         ←── 固定RSS URL ─────────┘

Podcastアプリ ── RSS取得 ─────→ Vercel → YouTubeの最新一覧
              ── 音声再生 ────→ Vercel → YouTubeのM4A音声
              ←── 音声バイト列 ──────┘   （保存せず中継）
```

- `public/`：日本語UI。ビルド不要のHTML・CSS・JavaScript。
- `api/index.py`：Vercel Python Function。POST `/api/feeds`、GET/HEAD `/feed/*.xml`、GET/HEAD `/audio/*.m4a`。
- `yp2pc/youtube.py`：yt-dlpを期限付き子プロセスで実行。YouTubeのM4A音声を選択し、再エンコードしません。FFmpegは不要です。
- `yp2pc/core.py`：URL検証とRSS生成。固定GUID、実ファイルサイズ、音声形式、公開日、番組画像を付与します。
- 音声は64KiBずつ中継し、HEAD・単一Range・206・416に対応します。署名URLが拒否された場合は1回再取得します。
- キャッシュはインスタンス内のメタデータのみです。フィードは5分、音声情報は有効期限を考慮して最大10分。コールドスタートでは再取得します。
- エピソードの一部に失敗した場合は取得できたものだけ掲載し、画面に失敗件数を表示します。全件失敗時はエラーにし、空のRSSを成功扱いしません。

## ローカル起動

Python 3.12を使用します。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python dev.py
```

`http://127.0.0.1:3000` を開きます。既存のyt-dlp実行ファイルとNode.js/Denoがある場合は、標準ライブラリだけでローカル起動できます。

```powershell
$env:YTDLP_BIN = 'C:/ffmpeg/bin/yt-dlp.exe'
python dev.py
```

`.env.example` は設定の説明用です。`dev.py` は `.env` を自動では読みません。PowerShellの環境変数か、VercelのEnvironment Variablesで設定してください。

## Windows PCからiPadへのLAN内配信（実験用）

PCとiPadを同じ家庭内ネットワークに接続します。PCは有線でも構いません。ゲストWi-Fiなどで端末間通信が禁止されている場合は接続できません。

1. `ipconfig` でPCのLAN用IPv4アドレスを確認します。
2. 以下のアドレスを実際の値に置き換え、PowerShellで起動します。必要なPython・yt-dlp・Node.js/Denoは前述のローカル起動と同じです。

```powershell
./scripts/start-lan.ps1 -Address 192.168.1.4
```

3. WindowsファイアウォールでTCP 3000への接続が遮断される場合は、管理者PowerShellで次の限定的な規則を追加します。PCのアドレス、Pythonのパス、インターフェース名は環境に合わせて変更してください。ネットワーク全体のプロファイルは変更しません。

```powershell
New-NetFirewallRule -Name 'YP2PC-LAN-3000' -DisplayName 'YP2PC LAN 実験 TCP 3000' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3000 -LocalAddress 192.168.1.4 -RemoteAddress LocalSubnet -InterfaceAlias 'イーサネット' -Program 'D:\Python\Python312\python.exe' -Profile Any
```

4. iPadのSafariで `http://192.168.1.4:3000/` を開き、プレイリストからRSSを作成します。HTTP環境ではコピーAPIに制約があるため、ボタンでコピーできなければURL欄を長押ししてコピーしてください。
5. iPadのPodcast →「ライブラリ」→「…」→「番組をURLで追加」にRSS URLを貼り付けてフォローします。指定プレイリストなら `http://192.168.1.4:3000/feed/PLF119azDj_Og.xml` です。

RSSと音声のURLは `--base-url` で固定されます。HTTPは明示設定したプライベートIPv4・ループバックのみ許可し、Vercel上ではHTTPSに限定します。LAN用URLを外出先から利用することはできません。PCの停止・スリープ中も取得できませんが、Podcastアプリにダウンロード済みの音声は端末で再生できます。IPアドレスが変わると購読先も変わるため、継続利用時はルーターでDHCP予約を設定してください。

サーバーは起動したPowerShellでCtrl+Cを押して停止します。実験後に追加規則を削除する場合は、管理者PowerShellで実行します。

```powershell
Remove-NetFirewallRule -Name 'YP2PC-LAN-3000'
```

`dev.py` は家庭内実験用の簡易HTTPサーバーです。インターネットへ公開する運用には適しません。

## Vercelへのデプロイ

1. このリポジトリをGitHubの `konto250/yp2pc` にpushし、VercelでそのリポジトリをImportします。
2. Framework Presetは **Other**、Root Directoryはリポジトリ直下、Output Directoryは **public**。`vercel.json` のビルドコマンドを使用します。
3. Python 3.12、Fluid computeを使用します。`requirements.txt` によりyt-dlpを導入します。Denoはビルド時に公式GitHubリリースから取得し、SHA-256を照合して同梱します。APIキー、Blob、外部サーバーは不要です。
4. 本番URLを `APP_BASE_URL=https://your-project.vercel.app` に設定し、再デプロイします。未設定時は `VERCEL_PROJECT_PRODUCTION_URL`、次に `VERCEL_URL` を使います。購読URLの継続性のため固定の本番URL設定を推奨します。
5. 本番ページを開き、プレイリストを入力して、RSS取得と試聴を確認します。本番フィードと音声URLはPodcastアプリから認証なしでアクセスできる必要があります。Deployment Protectionが有効なら本番公開範囲を確認してください。

`vercel.json` は1リクエスト最大300秒です。先頭10件・最大3並列のメタデータ取得、音声中継は約265秒を上限にしています。遅い通信では音声転送が途中で終了することがあります。音声を保存しない場合もVercelの実行時間・転送量は消費します。公開サービスとしての大量利用には向きません。

| 環境変数 | 用途 |
| --- | --- |
| `APP_BASE_URL` | RSSと音声URLに使う固定HTTPSオリジン。LAN実験ではHTTPのプライベートIPv4も可。パスは含めません。 |
| `MAX_EPISODES` | 先頭から取得する件数。既定10、1～10。 |
| `YTDLP_BIN` | ローカルのyt-dlp実行ファイル。Vercelでは通常不要。 |

## 検証

外部通信なしのテスト：

```powershell
python -m unittest discover -s tests -v
node --check public/app.js
```

サーバー起動後、実プレイリストでRSSと音声の先頭・末尾の部分取得を検証します。音声全体は保存しません。

```powershell
python scripts/smoke.py
python scripts/smoke.py --base https://your-project.vercel.app
```

既定の検証対象は `https://www.youtube.com/playlist?list=PLF119azDj_Og` です。別の対象は `--playlist` で指定します。

## 制約

- 非公開、ログイン必須、年齢制限、ライブ配信中などの動画には対応しません。Cookieの収集やアクセス制限回避は実装していません。
- 対応するHTTPS M4A音声がない場合は、その動画を掲載しません。推測したファイルサイズやYouTubeの視聴ページURLを音声URLとして返しません。
- 元動画の変更・削除やYouTubeの仕様変更の影響を受けます。取得が壊れた場合はyt-dlpを更新して再デプロイします。依存定義は2026年版の範囲で更新を許可しています。
- 複数Rangeの同時要求には対応しません。音声配信リクエストはVercelを通ります。
- 本サービスにはログイン・永続的なユーザー別制限がありません。運用規模に応じてVercel側でアクセス・費用を管理してください。
- 利用できる権利・許可のあるコンテンツを対象にしてください。

## 参考資料

- [Apple PodcastsのRSS要件](https://podcasters.apple.com/support/823-podcast-requirements)
- [Vercel Python Functions](https://vercel.com/docs/functions/runtimes/python/api-directory)
- [Vercel Functionsの実行時間](https://vercel.com/docs/functions/configuring-functions/duration)
- [yt-dlpのJavaScript実行環境](https://github.com/yt-dlp/yt-dlp/wiki/EJS)
- [yt-dlpのYouTube取得制限](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)

PigeonPodの方式も調査しました。PigeonPodはYouTube Data APIで動画一覧を同期し、yt-dlpで音声を事前ダウンロードして、ローカルディスクまたはS3互換ストレージから配信する構成です。本プロジェクトは保存せず都度中継する実験的な実装で、PigeonPodのコードは取り込んでいません。
