#!/usr/bin/env python3
"""
毎日のゲーム雑学ショートを1本生成(プレミアム・ポップ版)。
- 各シーン: 写真(Commonsキュレーション→Openverse→Wikimedia検索) をKen Burnsで動かし、
  暗めグレーディング+グレインを乗せた上に、ポップイン文字+キーワード蛍光ピルを重ねる。
  写真が取れないシーンはネオン・グラデ背景にフォールバック。絵文字は使わない。
- ナレーションは edge-tts。字幕(=画面テキスト)はPILで描画(drawtextの□不具合を回避)。
出力: out/video.mp4 と out/meta.json
GitHub Actions(ネット制限なし)での実行を想定。
"""
import os, sys, json, subprocess, datetime, asyncio, glob, math, io
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out"); TMP = os.path.join(OUT, "tmp")
W, H, FPS = 1080, 1920, 30
CY = int(H * 0.60)
VOICE = os.environ.get("TTS_VOICE", "ja-JP-NanamiNeural")
UA = "GameTriviaShortsBot/1.0 (youtube automation; contact via github)"
OK_LIC = ("public domain", "cc0", "cc by", "cc-by", "pdm", "attribution")
TXT = (253, 251, 255)

def font(sz):
    for p in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
              "/usr/share/fonts/truetype/noto/NotoSansCJK-Black.ttc"]:
        if os.path.exists(p): return ImageFont.truetype(p, sz)
    hits = glob.glob("/usr/share/fonts/**/NotoSansCJK-*.*", recursive=True)
    return ImageFont.truetype(hits[0], sz)

rng = np.random.default_rng(5)
GRAIN = rng.integers(-7, 8, (H, W, 1)).astype(np.int16)

def eob(t): t=min(1,max(0,t)); c1=1.7; c3=c1+1; return 1+c3*(t-1)**3+c1*(t-1)**2
def eo(t): t=min(1,max(0,t)); return 1-(1-t)**3

# ---------- backgrounds ----------
def _glow(cx, cy, r, color, al):
    g = Image.new("RGBA", (W, H), (0,0,0,0)); ImageDraw.Draw(g).ellipse([cx-r,cy-r,cx+r,cy+r], fill=color+(al,))
    return g.filter(ImageFilter.GaussianBlur(int(r*0.6)))

def gradient_bg(base, glows):
    yy = np.linspace(0,1,H)[:,None,None]; a=np.array(base); b=(np.array(base)*0.5).astype(int)
    arr = np.repeat((a*(1-yy)+b*yy).astype(np.uint8), W, axis=1)
    img = Image.fromarray(arr,"RGB").convert("RGBA")
    for (cx,cy,r,col,al) in glows: img = Image.alpha_composite(img, _glow(cx,cy,r,col,al))
    a2 = np.clip(np.asarray(img.convert("RGB")).astype(np.int16)+GRAIN,0,255).astype(np.uint8)
    img = Image.fromarray(a2,"RGB").convert("RGBA")
    return _vignette(img)

def _vignette(img):
    vg=Image.new("L",(W,H),0); ImageDraw.Draw(vg).ellipse([-W*0.3,-H*0.15,W*1.3,H*1.15],fill=255)
    vg=vg.filter(ImageFilter.GaussianBlur(240))
    vig=Image.new("RGBA",(W,H),(0,0,0,255)); vig.putalpha(Image.eval(vg,lambda a:205-int(a*0.8)))
    return Image.alpha_composite(img,vig)

def graded_image(path):
    """写真をcover配置+暗めグレーディング+下スクリム+グレイン。Ken Burns用に1.18倍で返す。"""
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return None
    tw, th = int(W*1.18), int(H*1.18)
    sr = max(tw/im.width, th/im.height)
    im = im.resize((int(im.width*sr), int(im.height*sr)), Image.LANCZOS)
    x=(im.width-tw)//2; y=(im.height-th)//2
    im = im.crop((x,y,x+tw,y+th)).convert("RGBA")
    # 軽いグレーディング(写真は見せる。全体はうっすらだけ暗く)
    ov = Image.new("RGBA",(tw,th),(14,10,30,55)); im=Image.alpha_composite(im,ov)
    # 下側スクリム(テキスト帯だけ濃く。写真は上半分を活かす)
    sc=Image.new("L",(tw,th),0); sd=ImageDraw.Draw(sc)
    for i in range(th):
        r=i/th
        if r>0.48:
            sd.line([(0,i),(tw,i)], fill=int(215*((r-0.48)/0.52)))
    scrim=Image.new("RGBA",(tw,th),(8,6,20,255)); scrim.putalpha(sc)
    im=Image.alpha_composite(im,scrim)
    # グレイン
    g=rng.integers(-7,8,(th,tw,1)).astype(np.int16)
    a=np.clip(np.asarray(im.convert("RGB")).astype(np.int16)+g,0,255).astype(np.uint8)
    return Image.fromarray(a,"RGB").convert("RGBA")

def ken_burns(base, p):
    """graded_image(1.18x) から (W,H) を p(0..1)で緩くパン&ズーム。"""
    tw,th=base.size
    z=1.0+0.06*p
    cw,ch=int(W/ (1.18/ (1.18)) ),0  # placeholder
    vw,vh=int(W*(1.0)/1.0),int(H)
    # window moves from top-left-ish to bottom-right-ish
    maxx,maxy=tw-W, th-H
    x=int(maxx*(0.15+0.7*p)); y=int(maxy*(0.15+0.7*p))
    win=base.crop((x,y,x+W,y+H))
    if z!=1.0:
        nw,nh=int(W*z),int(H*z); win=win.resize((nw,nh),Image.LANCZOS).crop(((nw-W)//2,(nh-H)//2,(nw-W)//2+W,(nh-H)//2+H))
    return win.copy()

# ---------- text ----------
def make_text_layer(lines, scale, kw, kwcol):
    layer=Image.new("RGBA",(W,H),(0,0,0,0)); d=ImageDraw.Draw(layer)
    fonts=[font(max(10,int(sz*scale))) for (t,sz) in lines]
    dims=[]
    for (t,sz),ft in zip(lines,fonts):
        b=d.textbbox((0,0),t,font=ft); dims.append((b[2]-b[0],b[3]-b[1],b[1]))
    gap=int(26*scale); tot=sum(h for _,h,_ in dims)+gap*(len(lines)-1)
    y=CY-tot/2; pills=[]
    for (t,sz),ft,(tw,th,oy) in zip(lines,fonts,dims):
        x=W//2-tw/2
        if kw and t==kw:
            pad=int(34*scale); pills.append((int(x-pad),int(y-10*scale),int(x+tw+pad),int(y+th+20*scale),ft,t,int(x),int(y-oy)))
        else:
            d.text((x,y-oy),t,font=ft,fill=TXT)
        y+=th+gap
    # soft shadow of the plain text
    sh=layer.filter(ImageFilter.GaussianBlur(16)); sh.putalpha(sh.split()[3].point(lambda v:int(v*0.6)))
    out=Image.new("RGBA",(W,H),(0,0,0,0)); out.alpha_composite(sh,(0,10)); out.alpha_composite(layer)
    # pills on top
    for (x0,y0,x1,y1,ft,t,tx,ty) in pills:
        pw,ph=max(1,x1-x0),max(1,y1-y0)
        grad=Image.new("RGBA",(pw,ph),(0,0,0,0)); gd=ImageDraw.Draw(grad)
        for i in range(ph):
            r=i/max(1,ph); c=tuple(int(kwcol[0][k]*(1-r)+kwcol[1][k]*r) for k in range(3)); gd.line([(0,i),(pw,i)],fill=c+(255,))
        mask=Image.new("L",(pw,ph),0); ImageDraw.Draw(mask).rounded_rectangle([0,0,pw-1,ph-1],radius=int(ph*0.32),fill=255)
        pill=Image.new("RGBA",(pw,ph),(0,0,0,0)); pill.paste(grad,(0,0),mask)
        ps=pill.filter(ImageFilter.GaussianBlur(16)); psh=Image.new("RGBA",(W,H),(0,0,0,0)); psh.alpha_composite(ps,(x0,y0+16))
        psh.putalpha(psh.split()[3].point(lambda v:int(v*0.5))); out.alpha_composite(psh); out.alpha_composite(pill,(x0,y0))
        ImageDraw.Draw(out).text((tx,ty),t,font=ft,fill=(22,16,38))
    return out

# ---------- images ----------
def _download(url, outpath):
    try:
        r=requests.get(url, headers={"User-Agent":UA}, timeout=45); r.raise_for_status()
        open(outpath,"wb").write(r.content);
        Image.open(outpath).verify(); return outpath
    except Exception: return None

def from_commons_file(title, outpath):
    try:
        r=requests.get("https://commons.wikimedia.org/w/api.php", headers={"User-Agent":UA}, timeout=30,
            params={"action":"query","format":"json","titles":title,"prop":"imageinfo","iiprop":"url","iiurlwidth":"1400"})
        pages=(r.json().get("query") or {}).get("pages") or {}
        for p in pages.values():
            ii=(p.get("imageinfo") or [{}])[0]
            url=ii.get("thumburl") or ii.get("url")
            if url: return _download(url, outpath)
    except Exception: return None
    return None

def from_openverse(query, outpath):
    try:
        r=requests.get("https://api.openverse.org/v1/images/", headers={"User-Agent":UA}, timeout=30,
            params={"q":query,"page_size":"8","mature":"false"})
        for res in r.json().get("results",[]):
            url=res.get("url")
            if url and not url.lower().endswith((".svg",".gif")):
                if _download(url, outpath): return outpath
    except Exception: return None
    return None

def from_wikimedia_search(query, outpath):
    try:
        r=requests.get("https://commons.wikimedia.org/w/api.php", headers={"User-Agent":UA}, timeout=30,
            params={"action":"query","format":"json","prop":"imageinfo","generator":"search","gsrsearch":query,
                    "gsrnamespace":"6","gsrlimit":"12","iiprop":"url|extmetadata","iiurlwidth":"1400"})
        pages=(r.json().get("query") or {}).get("pages") or {}
        for p in pages.values():
            ii=(p.get("imageinfo") or [{}])[0]; meta=ii.get("extmetadata") or {}
            lic=(meta.get("LicenseShortName",{}).get("value","")+" "+meta.get("License",{}).get("value","")).lower()
            if not any(k in lic for k in OK_LIC): continue
            url=ii.get("thumburl") or ii.get("url")
            if url and not url.lower().endswith((".svg",".gif")):
                if _download(url, outpath): return outpath
    except Exception: return None
    return None

def resolve_image(scene, idx):
    # 著作権安全のため、キュレーション済みの Commons ファイル(image_file)のみ使用。
    # 自動検索(Openverse/Wikimedia全文検索)はファンアート等を拾うため使わない。
    out=os.path.join(TMP,f"img_{idx:02d}.jpg")
    if scene.get("image_file"):
        if from_commons_file(scene["image_file"], out): return out
    return None  # 無ければプレミアム・グラデ背景にフォールバック

# ---------- tts ----------
async def _tts(text,outpath):
    import edge_tts; await edge_tts.Communicate(text,VOICE,rate="+8%").save(outpath)
def tts(text,outpath): asyncio.run(_tts(text,outpath)); return outpath
def probe(path):
    return float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",path]).decode().strip())
def ff(args): subprocess.run(["ffmpeg","-y","-loglevel","error",*args],check=True)

# ---------- main ----------
def pick_topic(data):
    tid=os.environ.get("TOPIC_ID","").strip()
    if tid:
        for t in data["topics"]:
            if t["id"]==tid: return t
    start=datetime.date.fromisoformat(data["start_date"]); idx=(datetime.date.today()-start).days%len(data["topics"])
    return data["topics"][idx%len(data["topics"])]

def main():
    os.makedirs(TMP,exist_ok=True)
    data=json.load(open(os.path.join(ROOT,"content","topics.json"),encoding="utf-8"))
    topic=pick_topic(data); print(f"[topic] {topic['id']}")
    scenes=topic["scenes"]
    # TTS + durations + images
    durs=[]; narr=[]; imgs=[]; bases=[]
    for i,sc in enumerate(scenes):
        n=os.path.join(TMP,f"narr_{i:02d}.mp3"); tts(sc["narration"],n)
        d=max(1.8,probe(n)+0.45); durs.append(d); narr.append(n)
        ip=resolve_image(sc,i); imgs.append(ip)
        print(f"  scene{i}: {d:.1f}s image={'OK' if ip else 'gradient'}")
        if ip:
            bases.append(graded_image(ip))
        else:
            bases.append(None)
    # per-scene gradient fallback + cached settled text layer
    FALL=[(20,10,46),(16,12,40),(24,10,40),(14,14,44),(26,10,38),(18,12,46)]
    GLOW=[(300,560,520,(255,61,129),150),(820,980,440,(138,92,255),120)]
    KW=((255,61,129),(255,150,70))
    grad_cache={}; settled={}
    os.makedirs(os.path.join(TMP,"frames"),exist_ok=True)
    fi=0
    for i,sc in enumerate(scenes):
        lines=[[seg[0],seg[1]] for seg in sc["lines"]]
        kw=sc.get("kw")
        settled[i]=make_text_layer(lines,1.0,kw,KW)
        if bases[i] is None:
            base=FALL[i%len(FALL)]; grad_cache[i]=gradient_bg(base,GLOW)
        nf=int(durs[i]*FPS)
        for k in range(nf):
            t=k/FPS; p=t/durs[i]
            if bases[i] is not None:
                frame=ken_burns(bases[i],p)
            else:
                frame=grad_cache[i].copy()
            pop=min(1.0,t/0.5)
            if pop<1.0:
                tl=make_text_layer(lines,max(0.1,eob(pop)),kw,KW)
            else:
                tl=settled[i]
            frame.alpha_composite(tl)
            frame.convert("RGB").save(os.path.join(TMP,"frames",f"f_{fi:05d}.png")); fi+=1
    total=sum(durs)
    # narration concat (padded per scene)
    parts=[]
    for i in range(len(scenes)):
        pad=os.path.join(TMP,f"np_{i:02d}.m4a"); ff(["-i",narr[i],"-af",f"apad=pad_dur={durs[i]}","-t",f"{durs[i]}","-c:a","aac",pad]); parts.append(pad)
    al=os.path.join(TMP,"al.txt"); open(al,"w").write("".join(f"file '{p}'\n" for p in parts))
    narr_all=os.path.join(TMP,"narr.m4a"); ff(["-f","concat","-safe","0","-i",al,"-c","copy",narr_all])
    # upbeat bed
    bed=os.path.join(TMP,"bed.m4a")
    expr="0.14*sin(2*PI*55*t)*lt(mod(t,0.5),0.14)+0.045*sin(2*PI*660*t)*lt(mod(t,0.5),0.06)+0.035*sin(2*PI*880*t)*lt(mod(t,0.5),0.04)"
    ff(["-f","lavfi","-i",f"aevalsrc='{expr}':s=44100:d={total}","-af","highpass=f=40,alimiter=limit=0.9",bed])
    final=os.path.join(OUT,"video.mp4")
    ff(["-framerate",str(FPS),"-i",os.path.join(TMP,"frames","f_%05d.png"),
        "-i",narr_all,"-i",bed,
        "-filter_complex","[1:a]volume=1.0[n];[2:a]volume=0.5[b];[n][b]amix=inputs=2:duration=first[a]",
        "-map","0:v","-map","[a]","-c:v","libx264","-preset","medium","-crf","20",
        "-pix_fmt","yuv420p","-r",str(FPS),"-c:a","aac","-b:a","160k","-shortest","-movflags","+faststart",final])
    meta={"title":topic["youtube_title"],"description":topic.get("description",""),
          "tags":topic.get("tags",[]),"privacy":data.get("privacy","private"),"categoryId":"20"}
    json.dump(meta,open(os.path.join(OUT,"meta.json"),"w",encoding="utf-8"),ensure_ascii=False,indent=2)
    print(f"[done] {final} ({total:.1f}s, {fi} frames)")

if __name__=="__main__":
    main()
