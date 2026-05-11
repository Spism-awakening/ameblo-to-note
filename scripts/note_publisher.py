import base64
import json
import os
import re
import tempfile
import time
import urllib.request
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
_HEADING_RE = re.compile(r'\x06(.*?)\x07', re.DOTALL)
_IMAGE_RE = re.compile(r'\x08(.*?)\x0e', re.DOTALL)
_IMAGE_SPLIT_RE = re.compile(r'(\x08.*?\x0e)', re.DOTALL)
_OGP_MARKER = "\x04"
_HR_MARKER = "\x05"


def _type_text(page, text: str):
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line:
            page.keyboard.type(line, delay=5)
        if i < len(lines) - 1:
            page.keyboard.press("Enter")


def _insert_html(page, text: str) -> bool:
    """太字・見出しマーカーを HTML タグに変換して execCommand で挿入する。成功したら True"""
    # 見出しマーカー(\x06...\x07) → <h2> タグ（前後の改行も吸収）
    html = re.sub(
        r"\n?\x06(.*?)\x07\n?",
        lambda m: "<h2>" + m.group(1) + "</h2>",
        text,
        flags=re.DOTALL,
    )
    # 太字マーカー(\x02...\x03) → <strong> タグ
    html = _BOLD_RE.sub(
        lambda m: "<strong>" + m.group(1).replace("\n", "<br>") + "</strong>",
        html,
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
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.keyboard.type(url.strip(), delay=5)
    page.keyboard.press("Enter")
    print(f"  OGPカード変換待機中: {url.strip()}")
    time.sleep(4)


def _download_image(url: str) -> str:
    """画像URLをダウンロードして一時ファイルパスを返す。失敗時は空文字"""
    try:
        ext = os.path.splitext(url.split("?")[0])[-1]
        if ext.lower() not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            ext = ".jpg"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            tmp.write(resp.read())
        tmp.close()
        print(f"  画像ダウンロード完了: {tmp.name} ({url})")
        return tmp.name
    except Exception as e:
        print(f"  画像ダウンロード失敗: {e} ({url})")
        return ""


def _close_crop_modal(page):
    """クロップモーダルをJavaScript直接クリックで閉じる（Playwrightのオーバーレイ検出を回避）"""
    try:
        overlay = page.locator('.CropModal__overlay, [class*="CropModal"]').first
        if not overlay.is_visible(timeout=2000):
            return
        print("  クロップモーダルを検出・閉じます")

        # モーダル内ボタンをデバッグ出力
        try:
            btns_info = page.evaluate("""() => {
                const modal = document.querySelector('.ReactModal__Content');
                if (!modal) return 'no modal';
                return JSON.stringify(
                    Array.from(modal.querySelectorAll('button')).map(b =>
                        (b.innerText || b.textContent || '').trim().substring(0, 30)
                    )
                );
            }""")
            print(f"  [DEBUG] モーダル内ボタン: {btns_info}")
        except Exception:
            pass

        # JavaScriptでボタンを直接クリック（オーバーレイがあってもクリックできる）
        result = page.evaluate("""() => {
            const modal = document.querySelector('.ReactModal__Content');
            if (!modal) return 'no-modal';
            const btns = Array.from(modal.querySelectorAll('button'));
            const confirmTexts = ['完了', '確定', 'OK', '保存', 'Done', 'Confirm'];
            const cancelTexts = ['キャンセル', '閉じる', '戻る', 'Cancel'];
            for (const btn of btns) {
                const text = (btn.innerText || btn.textContent || '').trim();
                if (confirmTexts.includes(text)) {
                    btn.click();
                    return 'clicked:' + text;
                }
            }
            for (let i = btns.length - 1; i >= 0; i--) {
                const text = (btns[i].innerText || '').trim();
                if (!cancelTexts.some(t => text.includes(t))) {
                    btns[i].click();
                    return 'fallback:' + text.substring(0, 20);
                }
            }
            return 'no-confirm:count=' + btns.length;
        }""")
        print(f"  クロップ確定: {result}")
        time.sleep(2)

        # まだ表示されている場合はEnterで再試行
        if page.locator('.CropModal__overlay').is_visible(timeout=1000):
            print("  クロップモーダルがまだ表示中、再試行")
            page.keyboard.press("Enter")
            time.sleep(1)
    except Exception as e:
        print(f"  クロップモーダル処理エラー: {e}")


def _input_image(page, url: str):
    """画像をダウンロードしてnoteエディタにアップロード挿入する"""
    print(f"  画像挿入開始: {url}")

    # 残留クロップモーダルを先に閉じる
    _close_crop_modal(page)

    path = _download_image(url)
    if not path:
        return

    inserted = False
    try:
        # エディタにフォーカスし、カーソルをドキュメント末尾に移動してから画像を挿入
        # (画像ボタンクリック前に末尾移動しないと先頭に挿入されてしまう)
        page.evaluate("() => { const ed = document.querySelector('.ProseMirror'); if (ed) ed.focus(); }")
        page.keyboard.press("Control+End")
        time.sleep(0.2)
        page.keyboard.press("Enter")
        time.sleep(0.3)

        # --- 方法1: ボタンクリック → サブメニュー「画像をアップロード」→ ファイル選択 → クロップ確定 ---
        try:
            img_btn = page.locator('button[aria-label*="画像"]').first
            img_btn.wait_for(state="visible", timeout=5000)
            img_btn.click()
            time.sleep(0.8)

            submenu_selectors = [
                'button:has-text("画像をアップロード")',
                'button:has-text("アップロード")',
                'button:has-text("PCから")',
                'button:has-text("ファイル")',
                'button:has-text("ローカル")',
                '[role="menuitem"]:has-text("アップロード")',
                '[role="menuitem"]:has-text("ファイル")',
            ]
            for sel in submenu_selectors:
                try:
                    elem = page.locator(sel).first
                    if elem.is_visible(timeout=500):
                        with page.expect_file_chooser(timeout=6000) as fc_info:
                            elem.click()
                        fc_info.value.set_files(path)
                        time.sleep(2)
                        # クロップモーダルを閉じる
                        _close_crop_modal(page)
                        time.sleep(1)
                        inserted = True
                        print(f"  画像挿入完了（{sel}）")
                        break
                except Exception:
                    continue

            if not inserted:
                page.keyboard.press("Escape")
                time.sleep(0.3)
        except Exception as e1:
            print(f"  方法1（ボタン+メニュー）失敗: {e1}")
            _close_crop_modal(page)

        if not inserted:
            print(f"  画像挿入失敗: {url}")

    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def _input_segment_with_images(page, text: str):
    """テキストを画像マーカー(\x08...\x0e)で分割し、画像はアップロード、それ以外は通常挿入"""
    parts = _IMAGE_SPLIT_RE.split(text)
    for part in parts:
        if part.startswith("\x08") and part.endswith("\x0e"):
            _input_image(page, part[1:-1])
        elif part:
            _input_segment(page, part)


def _input_to_editor(page, text: str):
    editor = page.locator(".ProseMirror").first
    editor.click()
    time.sleep(0.5)

    # HR マーカー(\x05) → OGP マーカー(\x04) の順で分割して処理
    hr_segments = text.split(_HR_MARKER)
    for k, hr_seg in enumerate(hr_segments):
        if k > 0:
            # 区切り線の前に残留クロップモーダルを必ず閉じる（モーダルが開いていると---がモーダルに入力される）
            _close_crop_modal(page)
            _input_hr(page)

        # OGP URL マーカー(\x04)でさらに分割
        ogp_segments = hr_seg.split(_OGP_MARKER)
        for j, seg in enumerate(ogp_segments):
            if not seg:
                continue
            if j == 0:
                if k == 0:
                    # 本文（HR前）は画像マーカーを除去してテキストのみ挿入
                    _input_segment(page, _IMAGE_RE.sub("", seg))
                else:
                    # 定型文（HR以降）は画像を挿入
                    _input_segment_with_images(page, seg)
            else:
                # \x04 以降：1行目が OGP URL、残りは通常テキスト（画像含む）
                first_newline = seg.find("\n")
                if first_newline == -1:
                    _input_ogp_url(page, seg)
                else:
                    _input_ogp_url(page, seg[:first_newline])
                    if k == 0:
                        _input_segment(page, _IMAGE_RE.sub("", seg[first_newline:]))
                    else:
                        _input_segment_with_images(page, seg[first_newline:])


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

            # 残留モーダルを閉じてから保存
            _close_crop_modal(page)
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
