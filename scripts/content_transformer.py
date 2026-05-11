import re
from bs4 import BeautifulSoup, NavigableString

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027BF"
    "\U0001F926-\U0001F937"
    "\U0001F200-\U0001F251"
    "\U00010000-\U0010FFFF"
    "♀-♂"
    "☀-⭕"
    "‍"
    "⏏⏩⌚"
    "️"
    "]+",
    re.UNICODE,
)

# 太文字マーカー（ASCII制御文字なので絵文字除去の影響を受けない）
BOLD_START = "\x02"
BOLD_END = "\x03"

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

NOTE_TEMPLATE = """


# 今だけ無料・72時間限定公開

＼恋愛も収入も停滞中のスピ迷子さんへ／

10年悩んでたことが、
たった40分で書き換わった

愛・お金・美しさが波のように連鎖する
性エネルギー覚醒変容の法則

【性エネルギー覚醒ウェビナー】が

今すぐ受け取れます！

今すぐ無料で受け取る！
↓ ↓ ↓
https://bigbangawakenings.com/lp/webinar3/


# 体験者のリアルな声、続々と届いてます

「10年動かなかった現実が、一気に動き出した」
「スピを極めたつもりだった私が、本当の鍵に出会った」
「愛される感覚が、毎日の中に自然にあふれています」

他にも、涙なしでは読めない感想がいっぱい...

あなたの未来が重なる声が、
きっと見つかります。

こちらからご覧いただけます！
↓
https://spism.my.canva.site/

愛と祈りを込めて
Mako
"""


def _emoji_replacer(match: re.Match) -> str:
    pos = match.end()
    start = match.start()
    text = match.string
    char_after = text[pos] if pos < len(text) else "\n"
    char_before = text[start - 1] if start > 0 else "\n"
    # 行頭の絵文字（箇条書きマーカー） → ・に置換
    if char_before in "\n\r" or start == 0:
        return "・"
    # 行末の絵文字（句読点として使われている） → 。に置換
    if char_after in "\n\r" or pos >= len(text):
        if char_before not in "\n\r。、！？!?":
            return "。"
    return ""


def remove_emoji(text: str) -> str:
    return EMOJI_PATTERN.sub(_emoji_replacer, text).strip()


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


def html_to_plain(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for br in soup.find_all("br"):
        br.replace_with("\n")

    # 太文字をマーカーで保持（noteエディターでCtrl+Bを使って再現）
    for bold in soup.find_all(["b", "strong"]):
        bold_text = bold.get_text()
        bold.replace_with(NavigableString(f"{BOLD_START}{bold_text}{BOLD_END}"))

    for p in soup.find_all("p"):
        p.insert_after("\n\n")

    text = soup.get_text(separator="")
    lines = [line.strip() for line in text.splitlines()]
    clean = "\n".join(lines)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()


def transform_for_note(title: str, html_content: str) -> dict:
    plain_text = html_to_plain(html_content)
    clean_title = remove_emoji(title)
    clean_body = remove_emoji(plain_text)

    full_content = clean_body + NOTE_TEMPLATE
    hashtags = select_hashtags(clean_title + " " + clean_body)

    return {
        "title": clean_title,
        "content": full_content,
        "hashtags": hashtags,
    }
