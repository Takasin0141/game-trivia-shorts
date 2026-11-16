#!/usr/bin/env python3
"""
毎日のゲーム雑学ショートを1本生成する。
1) 日付からトピックを選ぶ
2) 各シーンの画像を Wikimedia Commons(PD/CC) から取得（なければ無地背景）
3) edge-tts で日本語ナレーションを合成
4) ffmpeg で「画像をKen Burns + 字幕」のシーンを並べ、ナレーション+BGMを乗せる
出力: out/video.mp4 と out/meta.json

※ GitHub Actions(ubuntu-latest, ネット制限なし)での実行を想定。
   ローカルのこのサンドボックスは外部がブロックされているので最終テストは不可。
"""
import os, sys, json, subprocess, tempfile, datetime, shutil, asyncio, glob, re
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
TMP = os.path.join(OUT, "tmp")
VOICE = os.environ.get("TTS_VOICE", "ja-JP-NanamiNeural")
W, H, FPS = 1080, 1920, 30
UA = "GameTriviaShortsBot/1.0 (contact: set-your-email)"
OK_LICENSES = ("public domain", "cc0", "cc by", "cc-by", "pd", "attribution")

def find_font():
    for p in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
              "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"]:
        if os.path.exists(p):
            return p
    hits = glob.glob("/usr/share/fonts/**/NotoSansCJK*.*", recursive=True)
    if hits:
        return hits[0]
    raise SystemExit("日本語フォントが見つかりません。ワークフローで fonts-noto-cjk を入れてください。")

FONT = None

def pick_topic(data):
    start = datetime.date.fromisoformat(data["start_date"])
    today = datetime.date.today()
    idx = (today - start).days % len(data["topics"])
    if idx < 0:
        idx += len(data["topics"])
    return data["topics"][idx]

def fetch_image(query, outpath):
    """Wikimedia Commons から PD/CC 画像を1枚。失敗で None。"""
    try:
        api = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query", "format": "json", "prop": "imageinfo",
            "generator": "search", "gsrsearch": query, "gsrnamespace": "6",
            "gsrlimit": "12", "iiprop": "url|extmetadata|size",
            "iiurlwidth": "1280",
        }
        r = requests.get(api, params=params, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages") or {}
        cands = []
        for p in pages.values():
            ii = (p.get("imageinfo") or [{}])[0]
            if not ii:
                continue
            meta = ii.get("extmetadata") or {}
            lic = (meta.get("LicenseShortName", {}).get("value", "")
                   + " " + meta.get("License", {}).get("value", "")).lower()
            if not any(k in lic for k in OK_LICENSES):
                continue
            url = ii.get("thumburl") or ii.get("url")
            w = ii.get("thumbwidth") or ii.get("width") or 0
            if url and not url.lower().endswith((".svg", ".gif")) and w >= 700:
                cands.append(url)
        for url in cands:
            try:
                img = requests.get(url, headers={"User-Agent": UA}, timeout=40)
                img.raise_for_status()
                with open(outpath, "wb") as f:
                    f.write(img.content)
                return outpath
            except Exception:
                continue
    except Exception as e:
        print(f"  image fetch failed for '{query}': {e}")
    return None

async def _tts(text, outpath):
    import edge_tts
    await edge_tts.Communicate(text, VOICE, rate="+6%").save(outpath)

def tts(text, outpath):
    asyncio.run(_tts(text, outpath))
    return outpath

def probe_dur(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path]).decode().strip()
    return float(out)

def ff(args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)

def scene_clip(scene, dur, img, idx):
    """1シーンの動画(無音)を作る。画像ありはKen Burns、なしは無地。"""
    out = os.path.join(TMP, f"scene_{idx:02d}.mp4")
    cap_file = os.path.join(TMP, f"cap_{idx:02d}.txt")
    with open(cap_file, "w") as f:
        f.write(scene.get("caption", ""))
    nframes = max(1, int(dur * FPS))
    draw = (
        f"drawtext=textfile='{cap_file}':fontfile='{FONT}':fontsize=82:"
        f"fontcolor=white:line_spacing=18:text_align=C:x=(w-text_w)/2:y=(h-text_h)/2:"
        f"borderw=6:bordercolor=black@0.9:shadowcolor=black@0.7:shadowx=3:shadowy=4"
    )
    if img:
        vf = (
            f"scale={int(W*1.5)}:{int(H*1.5)}:force_original_aspect_ratio=increase,"
            f"crop={int(W*1.5)}:{int(H*1.5)},"
            f"zoompan=z='min(1.0+0.0007*on,1.14)':d={nframes}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
            f"eq=brightness=-0.06:saturation=1.05,"
            f"drawbox=x=0:y=h*0.62:w=w:h=h*0.38:color=black@0.45:t=fill,"
            f"{draw},format=yuv420p"
        )
        ff(["-loop", "1", "-t", f"{dur}", "-i", img, "-vf", vf, "-r", str(FPS), out])
    else:
        vf = (f"drawbox=x=0:y=h*0.60:w=w:h=h*0.40:color=black@0.35:t=fill,{draw},format=yuv420p")
        ff(["-f", "lavfi", "-i", f"color=c=0x0a0e1a:s={W}x{H}:d={dur}:r={FPS}",
            "-vf", vf, out])
    return out

def make_bgm(total, outpath):
    bundled = os.path.join(ROOT, "assets", "bgm.mp3")
    if os.path.exists(bundled):
        ff(["-stream_loop", "-1", "-i", bundled, "-t", f"{total}",
            "-af", "volume=0.18,afade=t=out:st=%.2f:d=1.2" % max(0, total-1.2), outpath])
    else:
        expr = ("(0.05*sin(2*PI*131*t)+0.04*sin(2*PI*196*t)+0.03*sin(2*PI*330*t))"
                "*(0.6+0.4*sin(2*PI*0.2*t))")
        ff(["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={total}",
            "-af", "lowpass=f=2200,volume=0.9", outpath])
    return outpath

def main():
    global FONT
    FONT = find_font()
    os.makedirs(TMP, exist_ok=True)
    data = json.load(open(os.path.join(ROOT, "content", "topics.json"), encoding="utf-8"))
    topic = pick_topic(data)
    print(f"[topic] {topic['id']}  ({topic['youtube_title']})")

    scene_videos, narr_parts, durs = [], [], []
    for i, sc in enumerate(topic["scenes"]):
        print(f"[scene {i}] {sc.get('caption','').replace(chr(10),' / ')}")
        narr = os.path.join(TMP, f"narr_{i:02d}.mp3")
        tts(sc["narration"], narr)
        d = max(2.0, probe_dur(narr) + 0.5)  # 少し余白
        img = None
        if sc.get("image_query"):
            img = fetch_image(sc["image_query"], os.path.join(TMP, f"img_{i:02d}.jpg"))
            print(f"    image: {'OK' if img else 'none (fallback)'}")
        scene_videos.append(scene_clip(sc, d, img, i))
        # ナレーションを d 秒に合わせてパディング
        narr_pad = os.path.join(TMP, f"narrpad_{i:02d}.m4a")
        ff(["-i", narr, "-af", f"apad=pad_dur={d}", "-t", f"{d}", "-c:a", "aac", narr_pad])
        narr_parts.append(narr_pad)
        durs.append(d)

    total = sum(durs)
    # concat video
    vlist = os.path.join(TMP, "vlist.txt")
    with open(vlist, "w") as f:
        for v in scene_videos:
            f.write(f"file '{v}'\n")
    silent = os.path.join(TMP, "silent.mp4")
    ff(["-f", "concat", "-safe", "0", "-i", vlist, "-c", "copy", silent])
    # concat narration
    alist = os.path.join(TMP, "alist.txt")
    with open(alist, "w") as f:
        for a in narr_parts:
            f.write(f"file '{a}'\n")
    narr_all = os.path.join(TMP, "narr_all.m4a")
    ff(["-f", "concat", "-safe", "0", "-i", alist, "-c", "copy", narr_all])
    # bgm
    bgm = make_bgm(total, os.path.join(TMP, "bgm.m4a"))
    # mix + mux
    final = os.path.join(OUT, "video.mp4")
    ff(["-i", silent, "-i", narr_all, "-i", bgm,
        "-filter_complex", "[1:a]volume=1.0[n];[2:a]volume=0.18[b];[n][b]amix=inputs=2:duration=first[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
        "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
        "-shortest", "-movflags", "+faststart", final])

    meta = {
        "title": topic["youtube_title"],
        "description": topic.get("description", ""),
        "tags": topic.get("tags", []),
        "privacy": data.get("privacy", "private"),
        "categoryId": "20",
    }
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"[done] {final}  ({total:.1f}s)")

if __name__ == "__main__":
    main()
