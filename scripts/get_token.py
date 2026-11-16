#!/usr/bin/env python3
"""
【最初に一度だけ・自分のPCで実行】YouTube アップロード用のリフレッシュトークンを取得する。

事前準備:
  1. Google Cloud でプロジェクト作成 → 「YouTube Data API v3」を有効化
  2. OAuth同意画面を設定（テスト or 公開）、テストユーザーに自分のGoogleアカウントを追加
  3. 認証情報 → OAuthクライアントID(種類:デスクトップアプリ)を作成し client_secret.json をダウンロード
  4. このファイルと同じ場所に client_secret.json を置く
  5. pip install google-auth-oauthlib
  6. python get_token.py を実行 → ブラウザでログイン&許可
  7. 表示された REFRESH TOKEN / CLIENT ID / CLIENT SECRET を GitHub Secrets に登録:
       YT_REFRESH_TOKEN / YT_CLIENT_ID / YT_CLIENT_SECRET
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def main():
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    print("\n==== これらを GitHub Secrets に登録 ====")
    print("YT_CLIENT_ID     =", creds.client_id)
    print("YT_CLIENT_SECRET =", creds.client_secret)
    print("YT_REFRESH_TOKEN =", creds.refresh_token)
    print("======================================")
    if not creds.refresh_token:
        print("※ refresh_token が空の場合: 同意画面でこのアプリの許可を一度解除してから再実行してください。")

if __name__ == "__main__":
    main()
