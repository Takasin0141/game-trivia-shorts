# ゲーム雑学ショート 自動投稿パイプライン

毎日1本、ゲーム雑学の縦型ショート動画を**自動生成してYouTubeにアップロード**する仕組み。
エンジンは **GitHub Actions**（ネット制限がないので画像取得・TTS・YouTube投稿ができる）。

## 仕組み

```
GitHub Actions (毎日 cron で起動)
  └─ build_video.py
       ├─ content/topics.json から「今日のネタ」を日付で選択
       ├─ 各シーンの写真を Wikimedia Commons(PD/CC) から取得  … 鍵不要
       ├─ edge-tts で日本語ナレーション合成               … 鍵不要・無料
       └─ ffmpeg で「写真をKen Burns + 字幕」を合成 + ナレ/BGM
  └─ upload_youtube.py
       └─ YouTube Data API で投稿（OAuthリフレッシュトークン）
```

- **著作権**：映像は写真(PD/CC)＋自作グラフィック＋オリジナル原稿のみ。特定ゲームのスクショ/キャラ/BGMは使わない。
- **秘密情報は YouTube OAuth の3つだけ**（GitHub Secretsに保管）。パスワードは渡さない。

## 一度だけの初期設定

### 1. このリポジトリを用意
Claude が GitHub 連携後に自動で push します（または自分でこの中身をリポジトリに入れる）。

### 2. YouTube チャンネルを作成
投稿先の YouTube チャンネルを用意（Googleアカウントが必要）。

### 3. Google Cloud で YouTube Data API を有効化
1. https://console.cloud.google.com/ でプロジェクト作成
2. 「YouTube Data API v3」を有効化
3. OAuth 同意画面を設定 → **テストユーザー**に自分のGoogleアカウントを追加
4. 認証情報 → **OAuthクライアントID（種類: デスクトップアプリ）** を作成 → `client_secret.json` をダウンロード

### 4. リフレッシュトークンを取得（自分のPCで1回）
```bash
pip install google-auth-oauthlib
# client_secret.json を scripts/ に置いてから:
cd scripts && python get_token.py
```
ブラウザでログイン＆許可 → 表示された3つの値を控える。

### 5. GitHub Secrets に登録
リポジトリ → Settings → Secrets and variables → Actions → New repository secret
- `YT_CLIENT_ID`
- `YT_CLIENT_SECRET`
- `YT_REFRESH_TOKEN`

### 6. まずは非公開でテスト
`content/topics.json` の `"privacy": "private"` のまま、Actions タブ →
`daily-short` → **Run workflow**（手動実行）で1本作ってみる。
- 生成だけ見たいときは入力 `upload` を false に → `out/video.mp4` が artifact に出る。
- アップロードまで試すなら true → 非公開で自分のチャンネルに上がる。
確認して問題なければ `"privacy": "public"` に変更。

## 日々の運用
- 放置で毎日 cron 実行（デフォルト 06:30 JST）。時刻は `.github/workflows/daily-short.yml` の cron で変更。
- **ネタの追加**：`content/topics.json` の `topics` に項目を足すだけ。日付で順番に消費される。尽きる前に補充。

## 注意（重要）
- **トークンの寿命**：OAuth同意画面が「テスト」状態だと、リフレッシュトークンが約7日で失効する。毎週再取得を避けたいなら同意画面を「公開」にする（機微スコープのため審査が入る場合あり）。
- **APIクォータ**：既定1万/日、アップロード1回≈1600。1日1本なら余裕。
- **ポリシー**：新規チャンネルで毎日AI自動投稿は「反復的・自動生成」判定のリスクがある。初速は少量＆手入れ推奨。弾かれると全部止まる。
- **品質**：自動取得の写真がトピックに合わない場合がある。`image_query` を具体化するほど精度が上がる。重要トピックは生成物を一度目視推奨。

## ローカル確認について
この開発環境（Claudeのサンドボックス）は外部通信がブロックされているため、Wikimedia/TTS/YouTube に接続できず**最終テストは不可**。テストは必ず GitHub Actions 上で行う（`Run workflow`）。
