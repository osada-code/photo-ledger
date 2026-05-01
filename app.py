"""
写真台帳 作成ツール v2 - Streamlit Web App
"""

import io
import os
import unicodedata
from datetime import datetime, timezone, timedelta

import streamlit as st
from PIL import Image, ExifTags
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# -------------------------------------------------------
# ページ設定
# -------------------------------------------------------
st.set_page_config(
    page_title="写真台帳 作成ツール",
    page_icon="📋",
    layout="centered",
)

# -------------------------------------------------------
# スタイル
# -------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&family=DM+Mono:wght@400;500&display=swap');
html, body, [class*="css"] { font-family: 'Noto Sans JP', sans-serif; }

.app-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    border-radius: 16px; padding: 36px 40px 32px;
    margin-bottom: 32px; position: relative; overflow: hidden;
}
.app-header::before {
    content: ''; position: absolute; top: -40px; right: -40px;
    width: 200px; height: 200px;
    background: radial-gradient(circle, rgba(229,160,13,0.15) 0%, transparent 70%);
    border-radius: 50%;
}
.app-header h1 { color: #fff; font-size: 26px; font-weight: 700; margin: 0 0 6px 0; }
.app-header p  { color: rgba(255,255,255,0.6); font-size: 13px; margin: 0; font-family: 'DM Mono', monospace; }
.accent-dot {
    display: inline-block; width: 8px; height: 8px;
    background: #e5a00d; border-radius: 50%; margin-right: 10px; vertical-align: middle;
}
.section-label {
    font-size: 11px; font-weight: 700; letter-spacing: 0.12em;
    color: #888; margin-bottom: 8px; margin-top: 24px;
}
.complete-card {
    background: linear-gradient(135deg, #0f5132, #155724);
    border-radius: 12px; padding: 28px 32px; color: white; margin-top: 24px;
}
.complete-card h2 { font-size: 22px; margin: 0 0 12px 0; }
.complete-card .meta { font-size: 13px; opacity: 0.85; font-family: 'DM Mono', monospace; line-height: 2; }

/* ファイル名編集テーブル */
.caption-table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }
.caption-table th {
    background: #f0f2f6; padding: 6px 10px; text-align: left;
    border-bottom: 2px solid #ddd; color: #555; font-weight: 600;
}
.caption-table td { padding: 4px 6px; border-bottom: 1px solid #eee; vertical-align: middle; }

[data-testid="stFileUploader"] { border: 2px dashed #d0d0d0; border-radius: 12px; padding: 8px; }
[data-testid="stButton"] > button {
    background: linear-gradient(135deg, #0f3460, #1a5276);
    color: white; border: none; border-radius: 10px;
    padding: 14px 32px; font-size: 16px; font-weight: 700;
    font-family: 'Noto Sans JP', sans-serif; width: 100%;
    letter-spacing: 0.05em;
}
hr { border-color: #f0f0f0; margin: 24px 0; }
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------
# ヘッダー
# -------------------------------------------------------
st.markdown("""
<div class="app-header">
    <h1><span class="accent-dot"></span>写真台帳(A4,9枚)作成ツール</h1>
    <p>写真をアップロード → 設定 → PDF生成 → ダウンロード</p>
</div>
""", unsafe_allow_html=True)

# -------------------------------------------------------
# 日本語フォント
# -------------------------------------------------------
@st.cache_resource
def load_font():
    path = '/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf'
    if os.path.exists(path):
        try:
            pdfmetrics.registerFont(TTFont('IPAGothic', path))
            return 'IPAGothic'
        except Exception:
            pass
    return 'Helvetica'

FONT_NAME = load_font()

# -------------------------------------------------------
# EXIF補正
# -------------------------------------------------------
def open_corrected(img: Image.Image) -> Image.Image:
    try:
        exif = img._getexif()
        if exif:
            orient_tag = next(k for k, v in ExifTags.TAGS.items() if v == 'Orientation')
            orientation = exif.get(orient_tag, 1)
            for tag, deg in {3: 180, 6: 270, 8: 90}.items():
                if orientation == tag:
                    img = img.rotate(deg, expand=True)
    except Exception:
        pass
    return img

# -------------------------------------------------------
# PDF生成
# -------------------------------------------------------
def build_pdf(photo_list_arg, rotate_portrait, quality,
              orientation, title_text, title_pos, title_size):
    """
    items: list of {"img": PIL.Image, "caption": str}
    orientation: "横（A4 landscape）" or "縦（A4 portrait）"
    title_pos: "なし" / "各ページ上部" / "各ページ下部" / "1ページ目上部のみ"
    """
    MARGIN  = 20
    SPACING = 8
    CAPTION_SIZE = 10
    CAPTION_H    = 16
    TITLE_H      = title_size + 8 if title_text and title_pos != "なし" else 0

    if orientation == "縦（A4 portrait）":
        PAGE_W, PAGE_H = portrait(A4)
        COLUMNS, ROWS  = 2, 3          # 縦A4は2列3行
    else:
        PAGE_W, PAGE_H = landscape(A4)
        COLUMNS, ROWS  = 3, 3

    IMAGES_PER_PAGE = COLUMNS * ROWS

    # タイトルが上部にある場合、上マージンを増やす
    top_title    = title_pos in ("各ページ上部", "1ページ目上部のみ")
    bottom_title = title_pos == "各ページ下部"
    margin_top    = MARGIN + (TITLE_H if top_title else 0)
    margin_bottom = MARGIN + (TITLE_H if bottom_title else 0)

    cell_w = (PAGE_W - MARGIN * 2 - SPACING * (COLUMNS - 1)) / COLUMNS
    cell_h = (PAGE_H - margin_top - margin_bottom - SPACING * (ROWS - 1)) / ROWS
    img_h  = cell_h - CAPTION_H

    buf = io.BytesIO()
    c   = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))

    def draw_title(page_num):
        if not title_text or title_pos == "なし":
            return
        if title_pos == "1ページ目上部のみ" and page_num > 0:
            return
        c.setFont(FONT_NAME, title_size)
        c.setFillColor(colors.black)
        if top_title:
            y = PAGE_H - MARGIN - title_size
        else:  # 下部
            y = MARGIN + 4
        c.drawCentredString(PAGE_W / 2, y, title_text)

    page_num = 0
    draw_title(page_num)

    for i, item in enumerate(photo_list_arg):
        page_idx = i % IMAGES_PER_PAGE
        if page_idx == 0 and i > 0:
            c.showPage()
            page_num += 1
            draw_title(page_num)

        col = page_idx % COLUMNS
        row = page_idx // COLUMNS
        cell_left = MARGIN + col * (cell_w + SPACING)
        cell_top  = PAGE_H - margin_top - row * (cell_h + SPACING)

        img = item["img"]
        w, h = img.size

        if h > w * 1.1 and rotate_portrait:
            img = img.rotate(90, expand=True)
            w, h = img.size

        ratio  = min(cell_w / w, img_h / h)
        draw_w = w * ratio
        draw_h = h * ratio

        out_w = max(int(draw_w * 3), 100)
        out_h = max(int(draw_h * 3), 100)
        img_small = img.resize((out_w, out_h), Image.LANCZOS)
        tmp_buf = io.BytesIO()
        img_small.convert('RGB').save(tmp_buf, 'JPEG', quality=quality)
        tmp_buf.seek(0)

        img_x = cell_left + (cell_w - draw_w) / 2
        img_y = cell_top - img_h + (img_h - draw_h) / 2
        c.drawImage(ImageReader(tmp_buf), img_x, img_y, width=draw_w, height=draw_h)

        # キャプション
        caption = unicodedata.normalize('NFC', item["caption"])
        max_chars = int(cell_w / (CAPTION_SIZE * 0.58))
        if len(caption) > max_chars:
            caption = caption[:max_chars - 1] + '...'
        c.setFont(FONT_NAME, CAPTION_SIZE)
        c.setFillColor(colors.black)
        c.drawCentredString(cell_left + cell_w / 2, cell_top - cell_h + 4, caption)

        yield i + 1, len(photo_list_arg), None

    c.save()
    buf.seek(0)
    yield len(photo_list_arg), len(photo_list_arg), buf.getvalue()


# ═══════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════

# -------------------------------------------------------
# STEP 1: 写真アップロード
# -------------------------------------------------------
st.markdown('<div class="section-label">📁 STEP 1 ｜ 写真ファイルを選択</div>', unsafe_allow_html=True)
uploaded_files = st.file_uploader(
    "JPG / PNG ファイルを選択（複数可）",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

# セッションステートでキャプションリストを管理
if "photo_list" not in st.session_state or not isinstance(st.session_state.photo_list, list):
    st.session_state.photo_list = []

if uploaded_files:
    uploaded_files_sorted = sorted(
        uploaded_files, key=lambda f: unicodedata.normalize('NFC', f.name)
    )

    # アップロード内容が変わったらリセット
    current_names = [f.name for f in uploaded_files_sorted]
    stored_names  = [it["orig_name"] for it in st.session_state.photo_list if isinstance(it, dict) and "orig_name" in it]
    if current_names != stored_names:
        st.session_state.photo_list = []
        for uf in uploaded_files_sorted:
            img = open_corrected(Image.open(uf))
            st.session_state.photo_list.append({
                "orig_name": uf.name,
                "caption":   unicodedata.normalize('NFC', uf.name),
                "img":       img,
            })

    # -------------------------------------------------------
    # STEP 2: キャプション編集・並び順変更
    # -------------------------------------------------------
    st.markdown('<div class="section-label">✏️ STEP 2 ｜ キャプション編集・並び順変更</div>', unsafe_allow_html=True)
    st.caption("ファイル名を編集できます。▲▼ で並び順を変更できます。")

    photo_list = st.session_state.photo_list
    for idx, item in enumerate(photo_list):
        cols = st.columns([0.5, 0.5, 6, 1, 1])
        cols[0].write(f"**{idx+1}**")

        # サムネイル
        thumb = item["img"].copy()
        thumb.thumbnail((48, 48))
        cols[1].image(thumb, use_container_width=False, width=48)

        # キャプション編集
        new_cap = cols[2].text_input(
            f"caption_{idx}", value=item["caption"],
            label_visibility="collapsed", key=f"cap_{idx}"
        )
        item["caption"] = new_cap

        # 上へ
        if cols[3].button("▲", key=f"up_{idx}", disabled=(idx == 0)):
            lst = st.session_state.photo_list
            lst.insert(idx - 1, lst.pop(idx))
            st.session_state.photo_list = lst
            st.rerun()

        # 下へ
        if cols[4].button("▼", key=f"dn_{idx}", disabled=(idx == len(st.session_state.photo_list) - 1)):
            lst = st.session_state.photo_list
            lst.insert(idx + 1, lst.pop(idx))
            st.session_state.photo_list = lst
            st.rerun()

    st.markdown("---")

    # -------------------------------------------------------
    # STEP 3: オプション設定
    # -------------------------------------------------------
    st.markdown('<div class="section-label">⚙️ STEP 3 ｜ オプション設定</div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        orientation = st.radio(
            "用紙の向き",
            ["横（A4 landscape）", "縦（A4 portrait）"],
            horizontal=True,
        )
    with col2:
        rotate = st.toggle("縦写真を横向きに回転", value=True)

    col3, col4 = st.columns(2)
    with col3:
        quality = st.select_slider(
            "画質",
            options=[60, 70, 75, 80, 85, 90, 95],
            value=75,
            format_func=lambda x: {60:"軽量", 75:"標準", 90:"高画質"}.get(x, str(x)),
        )

    st.markdown("---")

    # -------------------------------------------------------
    # STEP 4: 台帳タイトル
    # -------------------------------------------------------
    st.markdown('<div class="section-label">📝 STEP 4 ｜ 台帳タイトル（任意）</div>', unsafe_allow_html=True)

    col_t1, col_t2, col_t3 = st.columns([3, 2, 1])
    with col_t1:
        title_text = st.text_input("タイトル文字", placeholder="例：〇〇工事 現場写真台帳")
    with col_t2:
        title_pos = st.selectbox(
            "表示位置",
            ["なし", "各ページ上部", "各ページ下部", "1ページ目上部のみ"],
            disabled=not title_text,
        )
    with col_t3:
        title_size = st.number_input("文字サイズ", min_value=8, max_value=24, value=14, step=1)

    st.markdown("<br>", unsafe_allow_html=True)

    # -------------------------------------------------------
    # 実行ボタン
    # -------------------------------------------------------
    if st.button("📄　PDF を作成する"):
        progress_bar = st.progress(0, text="準備中...")
        pdf_bytes = None

        for current, total, result in build_pdf(
            list(st.session_state.photo_list), rotate, quality,
            orientation, title_text, title_pos, title_size
        ):
            pct = int(current / total * 100)
            progress_bar.progress(pct, text=f"{current} / {total} 枚処理中...")
            if result is not None:
                pdf_bytes = result

        progress_bar.empty()

        if pdf_bytes:
            JST       = timezone(timedelta(hours=9))
            timestamp = datetime.now(JST).strftime('%Y%m%d_%H%M')
            orient_str = "縦" if "portrait" in orientation else "横"
            n = len(st.session_state.photo_list)
            filename  = f"写真{n}枚A4{orient_str}_{timestamp}.pdf"
            size_mb   = len(pdf_bytes) / 1024 / 1024

            st.markdown(f"""
            <div class="complete-card">
                <h2>🎉 完成！</h2>
                <div class="meta">
                    {n}枚の写真を処理しました<br>
                    ファイル名：{filename}<br>
                    サイズ：{size_mb:.1f} MB
                </div>
            </div>
            """, unsafe_allow_html=True)

            st.download_button(
                label="⬇️　PDFをダウンロード",
                data=pdf_bytes,
                file_name=filename,
                mime="application/pdf",
                use_container_width=True,
            )
