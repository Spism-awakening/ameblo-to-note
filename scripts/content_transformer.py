import re
from bs4 import BeautifulSoup, NavigableString, Tag

# note_publisher.py の _input_to_editor と対応した太字マーカー
BOLD_START = "\x02"
BOLD_END = "\x03"

# アメブロ絵文字img (src に含まれる文字列) → 置換テキスト
AMEBLO_EMOJI_MAP = {
    "char3/533.png": "・",   # 丸ブルー（箇条書き専用）
    "char3/526.png": "↓",    # 下差し
    "char3/529.png": "▼",    # 下三角
    "char3/090.png": "★",    # 流れ星
    "char3/473.png": "✨",   # 乙女のトキメキ
    "char3/083.png": "♡",    # ピンクハート
    "char3/092.png": "！",   # ！
    "char2/185.gif": "💌",   # ラブレター
    "char2/035.gif": "❤️",   # ラブラブ
    "char2/182.gif": "🔔",   # ベル
}

ALL_HASHTAGS = [
    "#スピリチュアル",
    "#性エネルギー",
    "#願望実現",
    "#奇跡講座",
    "#マインドフルネス",
    "#潜在意識",
    "#自己変容",
]

KEYWORDS_MAP = {
    "#スピリチュアル": ["スピリチュアル", "スピ", "宇宙", "エネルギー", "魂"],
    "#性エネルギー": ["性エネルギー", "セックス", "クンダリーニ", "性", "官能"],
    "#願望実現": ["願望実現", "引き寄せ", "マニフェスト", "叶う"],
    "#奇跡講座": ["奇跡講座", "ACIM", "赦し", "聖霊", "奇跡"],
    "#マインドフルネス": ["マインドフルネス", "瞑想", "気づき", "今ここ"],
    "#潜在意識": ["潜在意識", "無意識", "深層", "罪悪感", "投影"],
    "#自己変容": ["自己変容", "目覚め", "悟り", "変容", "覚醒", "解放"],
}


def _get_ameblo_emoji(src: str) -> str:
    for key, val in AMEBLO_EMOJI_MAP.items():
        if key in src:
            return val
    return ""


def _is_empty_p(tag: Tag) -> bool:
    """`&nbsp;` や全角スペースのみの実質的に空の p タグ"""
    text = tag.get_text()
    return text.strip(" 　 \t\n\r") == ""


def _is_bullet_p(tag: Tag) -> bool:
    """丸ブルー（char3/533.png）を含む箇条書き p タグ"""
    for img in tag.find_all("img"):
        if "char3/533.png" in img.get("src", ""):
            return True
    return False


def _has_large_font(tag: Tag) -> bool:
    style = tag.get("style", "").replace(" ", "")
    return "font-size:1.4em" in style


def _process_inline(node, in_bold: bool = False) -> str:
    """HTML ノードをインラインテキストに再帰変換。in_bold で二重マーカーを防ぐ"""
    if isinstance(node, NavigableString):
        return str(node)

    name = node.name

    if name in ("b", "strong"):
        content = "".join(_process_inline(c, in_bold=True) for c in node.children)
        if not in_bold and content.strip():
            return f"{BOLD_START}{content}{BOLD_END}"
        return content

    elif name == "span":
        large = _has_large_font(node)
        content = "".join(
            _process_inline(c, in_bold=in_bold or large) for c in node.children
        )
        if large and not in_bold and content.strip():
            return f"{BOLD_START}{content}{BOLD_END}"
        return content

    elif name == "img":
        src = node.get("src", "")
        # ユーザー画像（記事内の写真等）はスキップ
        if "user_images" in src:
            return ""
        return _get_ameblo_emoji(src)

    elif name == "br":
        return "\n"

    elif name == "a":
        href = node.get("href", "")
        # 記事画像へのリンクはスキップ
        if node.find("img") and "user_images" in href:
            return ""
        # テキストリンクは URL を展開
        if not node.find("img"):
            return href
        return ""

    elif name == "iframe":
        src = node.get("src", "")
        return f"\n[YouTube動画]({src})\n"

    else:
        return "".join(_process_inline(c, in_bold=in_bold) for c in node.children)


def _process_bullet_p(tag: Tag) -> list[str]:
    """丸ブルー箇条書き p タグを ・ リストに変換"""
    raw = "".join(_process_inline(c) for c in tag.children)
    # ・ で各項目を分割（_get_ameblo_emoji が char3/533.png を ・ に変換済み）
    items = raw.split("・")
    result = []
    for item in items:
        # 改行と &nbsp; を除去して一行にまとめる
        parts = [s.strip(" 　 \t") for s in item.split("\n")]
        text = "".join(s for s in parts if s)
        if text:
            result.append(f"・{text}")
    return result


def _is_voice_section(tag: Tag) -> bool:
    """お客様の声セクションの開始 p タグを判定"""
    return tag.name == "p" and "体験者のリアルな声" in tag.get_text()


def _get_top_elements(soup: BeautifulSoup):
    body = soup.body
    return list(body.children) if body else list(soup.children)


def html_to_plain(html: str) -> str:
    """アメブロ HTML を note エディタ用テキストに変換"""
    soup = BeautifulSoup(html, "html.parser")
    elements = _get_top_elements(soup)

    lines: list[str] = []
    footer_inserted = False
    voice_inserted = False

    for el in elements:
        if isinstance(el, NavigableString):
            text = str(el).strip()
            if text:
                lines.append(text)
            continue

        if not isinstance(el, Tag):
            continue

        # ── h3：フッター定型文の直前に区切り線を挿入 ──
        if el.name == "h3":
            if not footer_inserted:
                lines.append("")
                lines.append("---")
                lines.append("")
                footer_inserted = True
            content_span = el.find("span", attrs={"data-entrydesign-content": True})
            src = content_span if content_span else el
            raw_text = "".join(_process_inline(c) for c in src.children).strip()
            # h3 見出しは太字マーカー不要なので除去
            text = re.sub(r"\x02|\x03", "", raw_text)
            lines.append(f"【{text}】")
            lines.append("")
            continue

        # ── p タグ ──
        if el.name == "p":
            # YouTube iframe を含む場合
            iframe = el.find("iframe")
            if iframe:
                src = iframe.get("src", "")
                lines.append("")
                lines.append(f"[YouTube動画]({src})")
                lines.append("")
                continue

            # 空の p タグ → 空行を保持
            if _is_empty_p(el):
                lines.append("")
                continue

            # お客様の声セクション直前に区切り線を挿入（フッター後のみ）
            if footer_inserted and not voice_inserted and _is_voice_section(el):
                lines.append("")
                lines.append("---")
                lines.append("")
                voice_inserted = True

            # 丸ブルー箇条書き
            if _is_bullet_p(el):
                lines.extend(_process_bullet_p(el))
                continue

            # 通常の p タグ
            content = "".join(_process_inline(c) for c in el.children)
            # <br>\n のような HTML ソース改行との重複を 1 改行に正規化
            content = re.sub(r"\n{2,}", "\n", content)
            if content.strip():
                for sub in content.split("\n"):
                    lines.append(sub.rstrip())
            else:
                lines.append("")
            continue

        # ── OGP カード (div.ogpCard_root) ──
        if el.name == "div" and "ogpCard_root" in el.get("class", []):
            a_tag = el.find("a", class_="ogpCard_link")
            if a_tag:
                href = a_tag.get("href", "")
                title_span = a_tag.find("span", class_="ogpCard_title")
                title = title_span.get_text().strip() if title_span else href
                lines.append("")
                lines.append(f"《{title}》")
                lines.append(href)
                lines.append("")
            continue

    # 連続する空行を最大 2 行に制限
    result: list[str] = []
    blank_count = 0
    for line in lines:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                result.append("")
        else:
            blank_count = 0
            result.append(line)

    return "\n".join(result)


def select_hashtags(text: str, count: int = 5) -> list[str]:
    scores = {}
    for tag, keywords in KEYWORDS_MAP.items():
        scores[tag] = sum(text.count(kw) for kw in keywords)
    sorted_tags = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    selected = [tag for tag, score in sorted_tags if score > 0][:count]
    if len(selected) < count:
        remaining = [tag for tag, _ in sorted_tags if tag not in selected]
        selected.extend(remaining[: count - len(selected)])
    return selected[:count]


def transform_for_note(title: str, html_content: str) -> dict:
    content = html_to_plain(html_content)
    # 太字マーカーを除いたプレーンテキストでハッシュタグを選定
    plain_for_tags = re.sub(r"\x02|\x03", "", content)
    hashtags = select_hashtags(title + " " + plain_for_tags)
    return {
        "title": title,
        "content": content,
        "hashtags": hashtags,
    }
