#!/usr/bin/env python3
"""
out/video.mp4 を out/meta.json のメタ情報で YouTube にアップロードする。
認証は OAuth リフレッシュトークン(環境変数)。パスワードは一切使わない。

必要な環境変数(GitHub Secrets):
  YT_CLIENT_ID      - Google Cloud の OAuth クライアントID
  YT_CLIENT_SECRET  - 同 クライアントシークレット
  YT_REFRESH_TOKEN  - scripts/get_token.py で一度だけ取得したリフレッシュトークン
"""
import os, json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def main():
    meta = json.load(open(os.path.join(OUT, "meta.json"), encoding="utf-8"))
    video = os.path.join(OUT, "video.mp4")
    if not os.path.exists(video):
        raise SystemExit("out/video.mp4 がありません。先に build_video.py を実行してください。")

    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri=TOKEN_URI,
        scopes=SCOPES,
    )
    yt = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": meta.get("description", ""),
            "tags": meta.get("tags", []),
            "categoryId": meta.get("categoryId", "20"),
        },
        "status": {
            "privacyStatus": meta.get("privacy", "private"),
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video, chunksize=-1, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"  uploading... {int(status.progress()*100)}%")
    print(f"[uploaded] https://youtu.be/{resp['id']}  (privacy={body['status']['privacyStatus']})")

if __name__ == "__main__":
    main()
