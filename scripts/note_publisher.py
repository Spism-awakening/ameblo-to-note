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


def _input_to_editor(page, text: str):
    editor = page.locator(".ProseMirror").first
    editor.click()
    time.sleep(0.5)

    paragraphs = text.split("\n")
    for i, para in enumerate(paragraphs):
        if para:
            page.keyboard.type(para, delay=5)
        if i < len(paragraphs) - 1:
            page.keyboard.press("Enter")


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
