import os
import re
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

NOTE_EMAIL = os.getenv("NOTE_EMAIL", "")
NOTE_PASSWORD = os.getenv("NOTE_PASSWORD", "")
DRAFT_MODE = os.getenv("DRAFT_MODE", "false").lower() == "true"


def _login(page) -> bool:
    page.goto("https://note.com/login?redirectPath=%2F")
    page.wait_for_load_state("networkidle")

    try:
        page.fill('input[name="email"]', NOTE_EMAIL, timeout=10000)
        page.fill('input[name="password"]', NOTE_PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_url("https://note.com/", timeout=20000)
        return True
    except PlaywrightTimeout:
        print("ログインに失敗しました（タイムアウト）")
        return False


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
            if not _login(page):
                return False

            page.goto("https://note.com/notes/new")
            page.wait_for_load_state("networkidle")
            time.sleep(3)

            # タイトル入力
            title_area = page.locator(
                'textarea[placeholder*="記事タイトル"], textarea[placeholder*="タイトル"]'
            ).first
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

            if DRAFT_MODE:
                # ---- 下書き保存 ----
                # noteは自動下書き保存があるが、明示的に保存ボタンを探す
                draft_btn = page.locator(
                    'button:has-text("下書き保存"), button:has-text("下書き")'
                ).first
                if draft_btn.is_visible(timeout=5000):
                    draft_btn.click()
                    time.sleep(2)
                else:
                    # ボタンが見つからない場合はnoteの自動保存に任せて3秒待つ
                    time.sleep(3)
                print(f"下書き保存完了: {title}")
                return True
            else:
                # ---- 公開 ----
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
                print(f"note公開完了: {title}\n  URL: {page.url}")
                return True

        except PlaywrightTimeout as e:
            print(f"タイムアウト: {e}")
            page.screenshot(path="/tmp/note_error.png")
            return False
        except Exception as e:
            print(f"投稿エラー: {e}")
            page.screenshot(path="/tmp/note_error.png")
            return False
        finally:
            browser.close()
