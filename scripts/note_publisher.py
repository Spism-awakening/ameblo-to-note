import json
import os
import re
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

NOTE_COOKIES = os.getenv("NOTE_COOKIES", "")
DRAFT_MODE = os.getenv("DRAFT_MODE", "false").lower() == "true"


def _setup_session(context) -> bool:
    """全CookieをセットしてログインをスキップするJSON形式"""
    raw_value = os.environ.get("NOTE_COOKIES", "")
    print(f"  [DEBUG] NOTE_COOKIES 長さ: {len(raw_value)} 文字")
    print(f"  [DEBUG] 環境変数一覧（NOTE_*）: {[k for k in os.environ if k.startswith('NOTE')]}")
    if not raw_value:
        print("  NOTE_COOKIES が設定されていません")
        return False
    try:
        raw = json.loads(raw_value)
        cookies = []
        for c in raw:
            cookie = {
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c.get("path", "/"),
            }
            if c.get("secure"):
                cookie["secure"] = True
            if c.get("httpOnly"):
                cookie["httpOnly"] = True
            if c.get("expirationDate"):
                cookie["expires"] = c["expirationDate"]
            if c.get("sameSite") in ("Strict", "Lax", "None"):
                cookie["sameSite"] = c["sameSite"]
            cookies.append(cookie)
        context.add_cookies(cookies)
        print(f"  Cookie {len(cookies)}件をセット")
        return True
    except Exception as e:
        print(f"  Cookie解析エラー: {e}")
        return False


def _verify_login(page) -> bool:
    """ログイン状態を確認する"""
    page.goto("https://note.com/notes/new")
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    if "login" in page.url:
        print(f"  セッション切れ（ログインページにリダイレクト）: {page.url}")
        return False

    print(f"  セッション確認OK: {page.url}")
    return True


_BOLD_RE = re.compile(r'\x02(.*?)\x03', re.DOTALL)
_OGP_MARKER = "\x04"  # OGP URL マーカー（content_transformer.py と対応）
_HR_MARKER = "\x05"   # 区切り線マーカー（content_transformer.py と対応）


def _type_text(page, text: str):
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line:
            page.keyboard.type(line, delay=5)
        if i < len(lines) - 1:
            page.keyboard.press("Enter")


def _insert_html(page, text: str) -> bool:
    """太字マーカーを <strong> に変換して execCommand で挿入する。成功したら True"""
    html = _BOLD_RE.sub(
        lambda m: "<strong>" + m.group(1).replace("\n", "<br>") + "</strong>",
        text,
    )
    html = re.sub(r"\n", "<br>", html)
    escaped = json.dumps(html)
    result = page.evaluate(
        f"""(() => {{
            const ed = document.querySelector('.ProseMirror');
            if (!ed) return 'no-editor';
            ed.focus();
            return document.execCommand('insertHTML', false, {escaped}) ? 'ok' : 'failed';
        }})()"""
    )
    print(f"  [DEBUG] insertHTML: {result}")
    return result == "ok"


def _type_with_bold(page, text: str):
    """フォールバック：Ctrl+B トグル方式で太字を入力"""
    parts = _BOLD_RE.split(text)
    for i, part in enumerate(parts):
        if not part:
            continue
        if i % 2 == 1:
            page.keyboard.down("Control")
            page.keyboard.press("b")
            page.keyboard.up("Control")
            time.sleep(0.05)
            _type_text(page, part)
            page.keyboard.down("Control")
            page.keyboard.press("b")
            page.keyboard.up("Control")
            time.sleep(0.05)
        else:
            _type_text(page, part)


def _input_segment(page, text: str):
    """通常テキスト（太字含む）のセグメントを挿入する"""
    if not text:
        return
    if not _insert_html(page, text):
        _type_with_bold(page, text)


def _input_hr(page):
    """区切り線を入力する（--- を入力して Enter でnoteが横線に変換）"""
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.keyboard.type("---", delay=5)
    page.keyboard.press("Enter")
    time.sleep(0.3)


def _input_ogp_url(page, url: str):
    """OGP カード用 URL を入力し、noteが OGP 変換するまで待機する"""
    # 確実に新しい行へ移動してから URL を入力
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.keyboard.type(url.strip(), delay=5)
    page.keyboard.press("Enter")
    print(f"  OGPカード変換待機中: {url.strip()}")
    time.sleep(4)


def _input_to_editor(page, text: str):
    editor = page.locator(".ProseMirror").first
    editor.click()
    time.sleep(0.5)

    # HR マーカー(\x05) → OGP マーカー(\x04) の順で分割して処理
    hr_segments = text.split(_HR_MARKER)
    for k, hr_seg in enumerate(hr_segments):
        if k > 0:
            _input_hr(page)

        # OGP URL マーカー(\x04)でさらに分割
        ogp_segments = hr_seg.split(_OGP_MARKER)
        for j, seg in enumerate(ogp_segments):
            if not seg:
                continue
            if j == 0:
                _input_segment(page, seg)
            else:
                # \x04 以降：1行目が OGP URL、残りは通常テキスト
                first_newline = seg.find("\n")
                if first_newline == -1:
                    _input_ogp_url(page, seg)
                else:
                    _input_ogp_url(page, seg[:first_newline])
                    _input_segment(page, seg[first_newline:])


def publish_to_note(title: str, content: str, hashtags: list[str]) -> bool:
    mode_label = "【下書き保存】" if DRAFT_MODE else "【公開】"
    print(f"{mode_label} noteへ投稿開始: {title}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            # Cookieでセッション復元
            if not _setup_session(context):
                return False

            # ログイン確認 & エディタページへ移動
            if not _verify_login(page):
                return False

            time.sleep(3)
            page.screenshot(path="/tmp/note_01_editor.png")

            # タイトル入力
            title_area = page.locator(
                'textarea[placeholder*="記事タイトル"], textarea[placeholder*="タイトル"]'
            ).first
            title_area.wait_for(state="visible", timeout=15000)
            title_area.fill(title)
            time.sleep(0.5)

            # 本文入力
            _input_to_editor(page, content)
            time.sleep(1)

            # ハッシュタグ設定
            tag_btn = page.locator('button[aria-label*="タグ"], button:has-text("タグ")').first
            if tag_btn.is_visible(timeout=3000):
                tag_btn.click()
                time.sleep(1)
                tag_input = page.locator('input[placeholder*="タグ"]').first
                for tag in hashtags:
                    tag_clean = tag.lstrip("#")
                    tag_input.fill(tag_clean)
                    time.sleep(0.3)
                    page.keyboard.press("Enter")
                    time.sleep(0.5)

            page.screenshot(path="/tmp/note_02_before_publish.png")

            if DRAFT_MODE:
                draft_btn = page.locator(
                    'button:has-text("下書き保存"), button:has-text("下書き")'
                ).first
                if draft_btn.is_visible(timeout=5000):
                    draft_btn.click()
                    time.sleep(2)
                else:
                    time.sleep(3)
                page.screenshot(path="/tmp/note_03_draft_saved.png")
                print(f"  下書き保存完了: {title}")
                return True
            else:
                publish_btn = page.locator(
                    'button:has-text("公開設定へ"), button:has-text("投稿")'
                ).first
                publish_btn.click(timeout=10000)
                time.sleep(2)

                confirm = page.locator(
                    'button:has-text("公開する"), button:has-text("投稿する")'
                ).first
                if confirm.is_visible(timeout=5000):
                    confirm.click()

                page.wait_for_url(re.compile(r"note\.com/[^/]+/n/"), timeout=20000)
                print(f"  公開完了: {title}\n  URL: {page.url}")
                return True

        except PlaywrightTimeout as e:
            page.screenshot(path="/tmp/note_error.png")
            print(f"タイムアウト: {e}")
            return False
        except Exception as e:
            page.screenshot(path="/tmp/note_error.png")
            print(f"投稿エラー: {e}")
            return False
        finally:
            browser.close()
