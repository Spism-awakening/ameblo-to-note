import os
import re
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

NOTE_EMAIL = os.getenv("NOTE_EMAIL", "")
NOTE_PASSWORD = os.getenv("NOTE_PASSWORD", "")
DRAFT_MODE = os.getenv("DRAFT_MODE", "false").lower() == "true"


def _debug_inputs(page):
    try:
        inputs = page.locator("input").all()
        print(f"  --- inputタグ一覧 ({len(inputs)}個) ---")
        for i, inp in enumerate(inputs):
            t = inp.get_attribute("type") or ""
            n = inp.get_attribute("name") or ""
            ph = inp.get_attribute("placeholder") or ""
            ac = inp.get_attribute("autocomplete") or ""
            print(f"  [{i}] type={t} name={n} placeholder={ph} autocomplete={ac}")
    except Exception as e:
        print(f"  input確認エラー: {e}")


def _debug_buttons(page):
    try:
        buttons = page.locator("button").all()
        print(f"  --- buttonタグ一覧 ({len(buttons)}個) ---")
        for i, btn in enumerate(buttons):
            try:
                t = btn.get_attribute("type") or ""
                text = (btn.inner_text() or "").replace("\n", " ")[:30]
                print(f"  [{i}] type={t} text={text}")
            except Exception:
                pass
    except Exception as e:
        print(f"  button確認エラー: {e}")


def _login(page) -> bool:
    page.goto("https://note.com/login?redirectPath=%2F")
    page.wait_for_load_state("networkidle")
    time.sleep(3)  # JSレンダリング待ち

    page.screenshot(path="/tmp/note_01_login_page.png")
    print(f"  ログインページURL: {page.url}")
    print(f"  タイトル: {page.title()}")
    _debug_inputs(page)

    try:
        # メールアドレス入力
        email_input = page.locator(
            'input[autocomplete="username"], '
            'input[type="email"], '
            'input[name="email"], '
            'input[placeholder*="メールアドレス"], '
            'input[placeholder*="mail@example.com"]'
        ).first
        email_input.wait_for(state="visible", timeout=15000)
        email_input.fill(NOTE_EMAIL)
        time.sleep(0.5)

        # 2ステップログイン対応（「次へ」ボタンがある場合）
        next_btn = page.locator(
            'button:has-text("次へ"), button:has-text("続ける"), button:has-text("Next")'
        ).first
        if next_btn.is_visible(timeout=2000):
            print("  「次へ」ボタンを検出 → クリック")
            next_btn.click()
            time.sleep(2)
            _debug_inputs(page)

        # パスワード入力
        password_input = page.locator('input[type="password"]').first
        password_input.wait_for(state="visible", timeout=10000)
        password_input.fill(NOTE_PASSWORD)
        time.sleep(0.5)

        page.screenshot(path="/tmp/note_02_login_filled.png")
        _debug_buttons(page)

        submit_btn = page.locator(
            'button[type="submit"], '
            'button:has-text("ログイン"), '
            'button:has-text("サインイン"), '
            'button:has-text("次へ"), '
            'input[type="submit"]'
        ).first
        submit_btn.click(timeout=15000)

        page.wait_for_url(re.compile(r"note\.com"), timeout=20000)
        page.screenshot(path="/tmp/note_03_after_login.png")
        print(f"  ログイン後URL: {page.url}")
        return True

    except PlaywrightTimeout as e:
        page.screenshot(path="/tmp/note_error_login.png")
        print(f"  ログインタイムアウト。現在URL: {page.url}")
        print(f"  エラー詳細: {e}")
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

            page.screenshot(path="/tmp/note_04_editor.png")

            title_area = page.locator(
                'textarea[placeholder*="記事タイトル"], textarea[placeholder*="タイトル"]'
            ).first
            title_area.fill(title)
            time.sleep(0.5)

            _input_to_editor(page, content)
            time.sleep(1)

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

            page.screenshot(path="/tmp/note_05_before_publish.png")

            if DRAFT_MODE:
                draft_btn = page.locator(
                    'button:has-text("下書き保存"), button:has-text("下書き")'
                ).first
                if draft_btn.is_visible(timeout=5000):
                    draft_btn.click()
                    time.sleep(2)
                else:
                    time.sleep(3)
                page.screenshot(path="/tmp/note_06_draft_saved.png")
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
