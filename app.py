import os
import io
import time
import unicodedata
from typing import Optional, List, Tuple
from urllib.parse import unquote_plus

import requests
from fastapi import FastAPI, Query
from fastapi.responses import Response, JSONResponse
from PIL import Image as PILImage
from PIL import ImageDraw, ImageFont

try:
    from pilmoji import Pilmoji
    PILMOJI_OK = True
except Exception:
    PILMOJI_OK = False


app = FastAPI(title="shen-meme-api")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
CACHE_DIR = os.path.join(BASE_DIR, ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)

TOP_SENTENCE_BOX = (60, 30, 1695, 260)
AVATAR_BOX = (250, 260, 1504, 1245)

PADDING = 12
FONT_PATH = os.path.join(ASSETS_DIR, "font.ttf")

LINE_SPACING_RATIO = 0.24
TOP_TEXT_NUDGE_Y = 0


def find_template():
    for fn in ("template.png", "template.jpg", "template.jpeg", "template.webp"):
        p = os.path.join(ASSETS_DIR, fn)
        if os.path.exists(p):
            return p
    return None


TEMPLATE_PATH = find_template()


def blank_boxes(img: PILImage.Image, boxes: List[Tuple[int, int, int, int]]):
    draw = ImageDraw.Draw(img)
    for (x1, y1, x2, y2) in boxes:
        px1 = max(0, x1 - PADDING)
        py1 = max(0, y1 - PADDING)
        px2 = min(img.size[0], x2 + PADDING)
        py2 = min(img.size[1], y2 + PADDING)
        draw.rectangle([px1, py1, px2, py2], fill=(255, 255, 255, 255))
    return img


def fetch_avatar(qq: int) -> PILImage.Image:
    url = f"https://q.qlogo.cn/headimg_dl?dst_uin={qq}&spec=640"
    cache_path = os.path.join(CACHE_DIR, f"avatar_{qq}.png")

    # 头像缓存 1 天
    if os.path.exists(cache_path):
        try:
            if time.time() - os.path.getmtime(cache_path) < 86400:
                return PILImage.open(cache_path).convert("RGBA")
        except Exception:
            pass

    r = requests.get(url, timeout=8)
    r.raise_for_status()
    data = r.content
    with open(cache_path, "wb") as f:
        f.write(data)
    return PILImage.open(io.BytesIO(data)).convert("RGBA")


def paste_avatar(base: PILImage.Image, avatar: PILImage.Image, box):
    x1, y1, x2, y2 = box
    bx1 = x1 + PADDING * 2
    by1 = y1 + PADDING * 2
    bx2 = x2 - PADDING * 2
    by2 = y2 - PADDING * 2

    bw = max(1, bx2 - bx1)
    bh = max(1, by2 - by1)

    target = min(bw, bh)
    avatar_resized = avatar.resize((target, target), PILImage.LANCZOS)

    px = bx1 + (bw - target) // 2
    py = by1 + (bh - target) // 2
    base.alpha_composite(avatar_resized, (px, py))
    return base


def load_font(size: int):
    if os.path.exists(FONT_PATH):
        return ImageFont.truetype(FONT_PATH, size=size)
    return ImageFont.load_default()


def _looks_mojibake(s: str) -> bool:
    bad = sum(ch in "ÃÂ�" for ch in s)
    return bad >= 2 or "\ufffd" in s


def smart_decode_text(s: Optional[str]) -> str:
    if s is None:
        return ""
    s = str(s)

    # 处理 URL 二次编码（%F0%9F...）和 + 号空格
    if "%" in s or "+" in s:
        try:
            s2 = unquote_plus(s)
            if s2 != s:
                s = s2
        except Exception:
            pass

    # 修复典型 latin1 误解码导致的乱码
    if _looks_mojibake(s):
        for enc in ("utf-8", "gb18030", "big5"):
            try:
                cand = s.encode("latin1", errors="ignore").decode(enc, errors="strict")
                if not _looks_mojibake(cand):
                    return cand
            except Exception:
                continue

    return s



def is_likely_emoji_cluster(gr: str) -> bool:
    if "\u200d" in gr or "\ufe0f" in gr:
        return True
    return any(unicodedata.category(ch) == "So" for ch in gr)


def iter_graphemes(text: str) -> List[str]:

    res: List[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in ("\u200d", "\ufe0f"):
            continue

        # 如果当前缓冲里没有 ZWJ，就直接提交
        if "\u200d" not in buf:
            res.append(buf)
            buf = ""

    if buf:
        res.append(buf)
    return res if res else list(text)

def _textbbox(draw: ImageDraw.ImageDraw, xy, text: str, font: ImageFont.ImageFont):
    try:
        return draw.textbbox(xy, text, font=font, embedded_color=True)
    except TypeError:
        return draw.textbbox(xy, text, font=font)


def _draw_text(draw: ImageDraw.ImageDraw, xy, text: str, font: ImageFont.ImageFont, fill):
    try:
        draw.text(xy, text, font=font, fill=fill, embedded_color=True)
    except TypeError:
        draw.text(xy, text, font=font, fill=fill)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int):
    lines: List[str] = []
    cur = ""

    for gr in iter_graphemes(text):
        trial = cur + gr

        try:
            bb = _textbbox(draw, (0, 0), trial, font)
            w = bb[2] - bb[0]
        except Exception:
            w = len(trial) * max(1, getattr(font, "size", 16))

        if is_likely_emoji_cluster(gr) and w <= 1:
            w = len(trial) * max(1, getattr(font, "size", 16))

        if w <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = gr

    if cur:
        lines.append(cur)
    return lines


def draw_wrapped_text_fit(img: PILImage.Image, text: str, box, max_lines: int = 2):
    x1, y1, x2, y2 = box
    bx1 = x1 + PADDING
    by1 = y1 + PADDING
    bx2 = x2 - PADDING
    by2 = y2 - PADDING

    bw = max(1, bx2 - bx1)
    bh = max(1, by2 - by1)

    draw = ImageDraw.Draw(img)

    lo, hi = 14, 220
    best_font = load_font(40)
    best_lines = [text]

    # 二分找“能放进框里”的最大字号
    while lo <= hi:
        mid = (lo + hi) // 2
        font = load_font(mid)
        lines = wrap_text(draw, text, font, bw)

        if len(lines) > max_lines:
            hi = mid - 1
            continue

        line_bboxes = [_textbbox(draw, (0, 0), ln, font) for ln in lines]
        line_heights = [(bb[3] - bb[1]) for bb in line_bboxes]
        spacing = int(mid * LINE_SPACING_RATIO)
        total_h = sum(line_heights) + spacing * (len(lines) - 1)

        if total_h <= bh:
            best_font = font
            best_lines = lines
            lo = mid + 1
        else:
            hi = mid - 1

    spacing = int(getattr(best_font, "size", 16) * LINE_SPACING_RATIO)
    bbs = [_textbbox(draw, (0, 0), ln, best_font) for ln in best_lines]
    widths = [(bb[2] - bb[0]) for bb in bbs]
    heights = [(bb[3] - bb[1]) for bb in bbs]
    total_h = sum(heights) + spacing * (len(best_lines) - 1)

    # 垂直居中
    start_y = by1 + (bh - total_h) // 2 + TOP_TEXT_NUDGE_Y
    if start_y < by1:
        start_y = by1

    y = start_y

    if PILMOJI_OK:
        with Pilmoji(img) as pm:
            for ln, w, h in zip(best_lines, widths, heights):
                x = bx1 + (bw - w) // 2
                pm.text((x, y), ln, (0, 0, 0, 255), best_font)
                y += h + spacing
        return img

    # 否则走 Pillow 原生
    for ln, w, h in zip(best_lines, widths, heights):
        x = bx1 + (bw - w) // 2
        _draw_text(draw, (x, y), ln, font=best_font, fill=(0, 0, 0, 255))
        y += h + spacing

    return img


@app.get("/health")
def health():
    ok = TEMPLATE_PATH is not None
    return {
        "ok": ok,
        "template": os.path.basename(TEMPLATE_PATH) if TEMPLATE_PATH else None,
        "pilmoji": PILMOJI_OK,
    }


@app.get("/meme")
def meme(
    qq: int = Query(..., ge=10000, le=99999999999),
    name: Optional[str] = Query(None, max_length=128),
):

    if not TEMPLATE_PATH:
        return JSONResponse({"error": "template not found in assets/"}, status_code=500)

    nickname = smart_decode_text(name).strip() if name else ""
    nickname = nickname or str(qq)

    top_text = f"请问你看到{nickname}了吗"

    img = PILImage.open(TEMPLATE_PATH).convert("RGBA")
    img = blank_boxes(img, [TOP_SENTENCE_BOX, AVATAR_BOX])

    avatar = fetch_avatar(qq)
    img = paste_avatar(img, avatar, AVATAR_BOX)

    img = draw_wrapped_text_fit(img, top_text, TOP_SENTENCE_BOX, max_lines=2)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG")
    return Response(content=out.getvalue(), media_type="image/png")
