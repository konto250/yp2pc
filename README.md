# YP2PC

YouTubeプレイリストのURLから、Apple Podcastsなどで直接購読するRSSフィードを発行するWebサービスです。Vercelのみで動かし、音声ファイル・データベース・Blobストレージを使いません。

**実験的な音声中継方式です。** YouTubeがVercelの送信元IPを拒否する場合や、M4A音声を取得できない動画では再生に失敗します。ローカルで取得できてもVercelで取得できる保証はありません。Apple Podcastsアプリ内での購読・再生は本番デプロイ後に確認してください。

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

## Vercelへのデプロイ

1. このリポジトリをGitHubの `konto250/yp2pc` にpushし、VercelでそのリポジトリをImportします。
2. Framework Presetは **Other**、Root Directoryはリポジトリ直下、Output Directoryは **public**。ビルドコマンドは不要です。
3. Python 3.12、Fluid computeを使用します。`requirements.txt` によりyt-dlpとDenoが導入されます。APIキー、Blob、外部サーバーは不要です。
4. 本番URLを `APP_BASE_URL=https://your-project.vercel.app` に設定し、再デプロイします。未設定時は `VERCEL_PROJECT_PRODUCTION_URL`、次に `VERCEL_URL` を使います。購読URLの継続性のため固定の本番URL設定を推奨します。
5. 本番ページを開き、プレイリストを入力して、RSS取得と試聴を確認します。本番フィードと音声URLはPodcastアプリから認証なしでアクセスできる必要があります。Deployment Protectionが有効なら本番公開範囲を確認してください。

`vercel.json` は1リクエスト最大300秒です。先頭10件・最大3並列のメタデータ取得、音声中継は約265秒を上限にしています。遅い通信では音声転送が途中で終了することがあります。音声を保存しない場合もVercelの実行時間・転送量は消費します。公開サービスとしての大量利用には向きません。

| 環境変数 | 用途 |
| --- | --- |
| `APP_BASE_URL` | RSSと音声URLに使う固定HTTPSオリジン。パスは含めません。 |
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
