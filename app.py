"""
現場写真台帳 作成ツール - Streamlit Web App
"""

import io
import os
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path

import streamlit as st
from PIL import Image, ExifTags
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# -------------------------------------------------------
# ページ設定
# -------------------------------------------------------
st.set_page_config(
    page_title="現場写真台帳 作成ツール",
    page_icon="📋",
    layout="centered",
)

# -------------------------------------------------------
# スタイル
# -------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&family=DM+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'Noto Sans JP', sans-serif;
}

/* ヘッダー */
.app-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    border-radius: 16px;
    padding: 36px 40px 32px;
    margin-bottom: 32px;
    position: relative;
    overflow: hidden;
}
.app-header::before {
    content: '';
    position: absolute;
    top: -40px; right: -40px;
    width: 200px; height: 200px;
    background: radial-gradient(circle, rgba(229,160,13,0.15) 0%, transparent 70%);
    border-radius: 50%;
}
.app-header h1 {
    color: #ffffff;
    font-size: 26px;
    font-weight: 700;
    margin: 0 0 6px 0;
    letter-spacing: 0.02em;
}
.app-header p {
    color: rgba(255,255,255,0.6);
    font-size: 13px;
    margin: 0;
    font-family: 'DM Mono', monospace;
}
.accent-dot {
    display: inline-block;
    width: 8px; height: 8px;
    background: #e5a00d;
    border-radius: 50%;
    margin-right: 10px;
    vertical-align: middle;
}

/* セクションラベル */
.section-label {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #888;
    margin-bottom: 8px;
    margin-top: 24px;
}

/* 完了カード */
.complete-card {
    background: linear-gradient(135deg, #0f5132, #155724);
    border-radius: 12px;
    padding: 28px 32px;
    color: white;
    margin-top: 24px;
}
.complete-card h2 {
    font-size: 22px;
    margin: 0 0 12px 0;
}
.complete-card .meta {
    font-size: 13px;
    opacity: 0.85;
    font-family: 'DM Mono', monospace;
    line-height: 2;
}

/* アップロードエリア */
[data-testid="stFileUploader"] {
    border: 2px dashed #d0d0d0;
    border-radius: 12px;
    padding: 8px;
    transition: border-color 0.2s;
}
[data-testid="stFileUploader"]:hover {
    border-color: #0f3460;
}

/* ボタン */
[data-testid="stButton"] > button {
    background: linear-gradient(135deg, #0f3460, #1a5276);
    color: white;
    border: none;
    border-radius: 10px;
    padding: 14px 32px;
    font-size: 16px;
    font-weight: 700;
    font-family: 'Noto Sans JP', sans-serif;
    width: 100%;
    cursor: pointer;
    transition: opacity 0.2s, transform 0.1s;
    letter-spacing: 0.05em;
}
[data-testid="stButton"] > button:hover {
    opacity: 0.9;
    transform: translateY(-1px);
}

/* 区切り線 */
hr { border-color: #f0f0f0; margin: 24px 0; }
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------
# ヘッダー
# -------------------------------------------------------
st.markdown("""
<div class="app-header">
    <h1><span class="accent-dot"></span>現場写真台帳 作成ツール</h1>
    <p>写真をアップロード → PDF生成 → ダウンロード</p>
</div>
""", unsafe_allow_html=True)

# -------------------------------------------------------
# 日本語フォント登録
# -------------------------------------------------------
@st.cache_resource
def load_font():
    FONT_PATH = '/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf'
    if os.path.exists(FONT_PATH):
        try:
            pdfmetrics.registerFont(TTFont('IPAGothic', FONT_PATH))
            return 'IPAGothic'
        except Exception:
            pass
    return 'Helvetica'

FONT_NAME = load_font()

# -------------------------------------------------------
# レイアウト定数
# -------------------------------------------------------
PAGE_W, PAGE_H  = landscape(A4)
COLUMNS, ROWS   = 3, 3
IMAGES_PER_PAGE = COLUMNS * ROWS
MARGIN, SPACING = 20, 8

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
def build_pdf(uploaded_files, rotate_portrait: bool, quality: int) -> bytes:
    caption_size = 10
    caption_h    = 16
    cell_w = (PAGE_W - MARGIN * 2 - SPACING * (COLUMNS - 1)) / COLUMNS
    cell_h = (PAGE_H - MARGIN * 2 - SPACING * (ROWS    - 1)) / ROWS
    img_h  = cell_h - caption_h

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))

    for i, uf in enumerate(uploaded_files):
        page_idx = i % IMAGES_PER_PAGE
        if page_idx == 0 and i > 0:
            c.showPage()

        col = page_idx % COLUMNS
        row = page_idx // COLUMNS
        cell_left = MARGIN + col * (cell_w + SPACING)
        cell_top  = PAGE_H - MARGIN - row * (cell_h + SPACING)

        # 画像読み込み・補正
        img = Image.open(uf)
        img = open_corrected(img)
        w, h = img.size

        if h > w * 1.1 and rotate_portrait:
            img = img.rotate(90, expand=True)
            w, h = img.size

        ratio  = min(cell_w / w, img_h / h)
        draw_w = w * ratio
        draw_h = h * ratio

        # リサイズ→JPEG→BytesIO
        out_w = max(int(draw_w * 3), 100)
        out_h = max(int(draw_h * 3), 100)
        img_small = img.resize((out_w, out_h), Image.LANCZOS)
        tmp_buf = io.BytesIO()
        img_small.convert('RGB').save(tmp_buf, 'JPEG', quality=quality)
        tmp_buf.seek(0)

        # 画像描画（上）
        img_x = cell_left + (cell_w - draw_w) / 2
        img_y = cell_top - img_h + (img_h - draw_h) / 2
        from reportlab.lib.utils import ImageReader
        c.drawImage(ImageReader(tmp_buf), img_x, img_y, width=draw_w, height=draw_h)

        # キャプション（下）
        c.setFont(FONT_NAME, caption_size)
        c.setFillColor(colors.black)
        name = unicodedata.normalize('NFC', uf.name)
        max_chars = int(cell_w / (caption_size * 0.58))
        if len(name) > max_chars:
            name = name[:max_chars - 1] + '...'
        c.drawCentredString(cell_left + cell_w / 2, cell_top - cell_h + 4, name)

        # 進捗更新
        yield i + 1, len(uploaded_files), None

    c.save()
    buf.seek(0)
    yield len(uploaded_files), len(uploaded_files), buf.getvalue()


# -------------------------------------------------------
# UI
# -------------------------------------------------------
st.markdown('<div class="section-label">📁 写真ファイル</div>', unsafe_allow_html=True)
uploaded_files = st.file_uploader(
    "JPG / PNG ファイルを選択（複数可）",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if uploaded_files:
    # ファイル名順にソート
    uploaded_files = sorted(uploaded_files, key=lambda f: unicodedata.normalize('NFC', f.name))
    st.caption(f"✅ {len(uploaded_files)}枚 選択中")

st.markdown('<div class="section-label">⚙️ オプション</div>', unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1:
    rotate = st.toggle("縦写真を横向きに回転", value=True)
with col2:
    quality = st.select_slider(
        "画質",
        options=[60, 70, 75, 80, 85, 90, 95],
        value=75,
        format_func=lambda x: {60:"軽量", 75:"標準", 90:"高画質"}.get(x, str(x)),
    )

st.markdown("<br>", unsafe_allow_html=True)

# -------------------------------------------------------
# 実行ボタン
# -------------------------------------------------------
if st.button("📄　PDF を作成する", disabled=not uploaded_files):
    progress_bar  = st.progress(0, text="準備中...")
    status_text   = st.empty()

    pdf_bytes = None
    for current, total, result in build_pdf(uploaded_files, rotate, quality):
        pct = int(current / total * 100)
        progress_bar.progress(pct, text=f"{current} / {total} 枚処理中...")
        if result is not None:
            pdf_bytes = result

    progress_bar.empty()
    status_text.empty()

    if pdf_bytes:
        JST = timezone(timedelta(hours=9))
        timestamp = datetime.now(JST).strftime('%Y%m%d_%H%M')
        filename  = f"写真{len(uploaded_files)}枚A4_{timestamp}.pdf"
        size_mb   = len(pdf_bytes) / 1024 / 1024

        st.markdown(f"""
        <div class="complete-card">
            <h2>🎉 完成！</h2>
            <div class="meta">
                {len(uploaded_files)}枚の写真を処理しました<br>
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
