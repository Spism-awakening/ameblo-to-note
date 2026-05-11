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
    return text.strip(" 　 \t\n\r") == ""


def _is_short_hr(tag: Tag) -> bool:
    """「───」などの装飾的な短い全角ダッシュ区切り線をスキップ"""
    text = tag.get_text().strip(" 　 \t\n\r")
    return 1 <= len(text) <= 8 and bool(re.match(r"^[─━ー\-]+$", text))


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
        if "user_images" in src:
            return ""
        return _get_ameblo_emoji(src)

    elif name == "br":
        return "\n"

    elif name == "a":
        href = node.get("href", "")
        if node.find("img") and "user_images" in href:
            return ""
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
    items = raw.split("・")
    result = []
    for item in items:
        parts = [s.strip(" 　 \t") for s in item.split("\n")]
        text = "".join(s for s in parts if s)
        if text:
            result.append(f"・{text}")
    return result


def _is_voice_section(tag: Tag) -> bool:
    return tag.name == "p" and "体験者のリアルな声" in tag.get_text()


def _apply_arrow_before_ogp(lines: list[str]) -> None:
    """OGP カード直前の行が「↓テキスト」形式の場合、矢印を削除して「↓　↓　↓」を追加"""
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip():
            last = lines[i]
            # 既に3矢印ならそのまま
            if "↓　↓" in last or "↓ ↓" in last:
                break
            # 先頭が↓で始まるテキスト行の矢印を除去して3矢印を挿入
            if last.startswith("↓"):
                lines[i] = re.sub(r"^↓\s*", "", last).strip()
                lines.append("↓　↓　↓")
            break


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
                lines.append("\x05")  # HR マーカー（note_publisher.py がキーボードで --- を入力）
                footer_inserted = True
            content_span = el.find("span", attrs={"data-entrydesign-content": True})
            src = content_span if content_span else el
            raw_text = "".join(_process_inline(c) for c in src.children).strip()
            text = re.sub(r"\x02|\x03", "", raw_text)
            lines.append(f"【{text}】")
            continue

        # ── p タグ ──
        if el.name == "p":
            iframe = el.find("iframe")
            if iframe:
                src = iframe.get("src", "")
                lines.append("")
                lines.append(f"[YouTube動画]({src})")
                lines.append("")
                continue

            if _is_empty_p(el):
                lines.append("")
                continue

            # 短い装飾ダッシュ（「───」等）をスキップ
            if _is_short_hr(el):
                continue

            if footer_inserted and not voice_inserted and _is_voice_section(el):
                lines.append("\x05")  # HR マーカー
                voice_inserted = True

            if _is_bullet_p(el):
                lines.extend(_process_bullet_p(el))
                continue

            content = "".join(_process_inline(c) for c in el.children)
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
                # 直前の「↓テキスト」行を「↓　↓　↓」に変換
                _apply_arrow_before_ogp(lines)
                # \x04 マーカー付きで出力 → note_publisher.py が OGP 変換を待機する
                lines.append(f"\x04{href}")
            continue

    # 連続する空行を最大 3 行に制限（アメブロの段落間空行を保持）
    result: list[str] = []
    blank_count = 0
    for line in lines:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 3:
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
    plain_for_tags = re.sub(r"\x02|\x03", "", content)
    hashtags = select_hashtags(title + " " + plain_for_tags)
    return {
        "title": title,
        "content": content,
        "hashtags": hashtags,
    }
