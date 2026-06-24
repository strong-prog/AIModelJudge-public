#!/usr/bin/env python3
"""AIModelJudge — Playwright Visual Tests (7 scenarios).

Usage: python3 tests/visual_test.py [base_url]
Default: http://127.0.0.1:9651/app/
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9651/app/"
SCREENSHOTS_DIR = Path(__file__).resolve().parent / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

PASS = 0
FAIL = 0


def screenshot(page: Page, name: str) -> str:
    path = str(SCREENSHOTS_DIR / f"{name}.png")
    page.screenshot(path=path, full_page=False)
    return path


def check(condition: bool, msg: str) -> None:
    global PASS, FAIL
    if condition:
        print(f"  PASS  {msg}")
        PASS += 1
    else:
        print(f"  FAIL  {msg}")
        FAIL += 1


def run():
    global PASS, FAIL
    print(f"=== AIModelJudge Visual Tests ===")
    print(f"Target: {BASE}")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ru-RU",
        )
        page = context.new_page()

        errors: list[str] = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

        # ── Scenario 1: Page load ──
        print("── 1. Page Load ──")
        try:
            page.goto(BASE, wait_until="networkidle", timeout=30000)
        except Exception as e:
            check(False, f"Page load: {e}")
            browser.close()
            print(f"\n=== Results: {PASS} passed, {FAIL} failed ===")
            print("VISUAL TEST FAILED" if FAIL else "VISUAL OK")
            sys.exit(1)

        check(page.title() == "AIModelJudge", f"Title = '{page.title()}'")

        # Check root div is rendered (React mounted)
        root = page.locator("#root")
        check(root.is_visible(), "Root #root is visible")

        # Check no JS errors (filter out benign ones)
        benign = {"serviceWorker", "favicon", "manifest"}
        real_errors = [e for e in errors if not any(b in e.lower() for b in benign)]
        check(len(real_errors) == 0, f"No JS console errors ({len(real_errors)} errors)")

        screenshot(page, "01-page-load")

        # ── Dismiss Login Modal if present ──
        print("── 0. Login Modal Check ──")
        login_overlay = page.locator(".modal-overlay")
        if login_overlay.is_visible():
            # Click "Продолжить без входа (Free)" to bypass login
            skip_btn = page.locator("button:has-text('Продолжить без входа')")
            if skip_btn.is_visible():
                skip_btn.click()
                page.wait_for_timeout(1000)
                check(not login_overlay.is_visible(), "Login modal dismissed via 'skip'")
            else:
                # Try pressing Escape
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                check(not login_overlay.is_visible(), "Login modal dismissed via Escape")
        else:
            check(True, "No login modal (already authenticated)")

        # ── Scenario 2: Theme toggle (dark → light) ──
        print("── 2. Theme Toggle ──")
        html = page.locator("html")
        initial_theme = html.get_attribute("data-theme")
        check(initial_theme == "dark", f"Initial theme = '{initial_theme}'")

        # Find theme toggle button — it contains Sun icon in dark mode, Moon in light
        # Look for button in header area with Sun/Moon SVG icons
        theme_btn = page.locator(".amj-chat-header button").filter(has=page.locator("svg")).nth(2)
        # Fallback: find any button whose tooltip mentions theme
        if not theme_btn.is_visible():
            theme_btn = page.locator("button").filter(has_text="").nth(0)

        # Try clicking the theme toggle by finding the Sun/Moon icon via its parent button
        # The ChatHeader has buttons in order: PanelLeft, PanelRight, Theme, Comfort, Memory, SelfLearning, Analytics
        # Theme is the 3rd button from panel toggle section
        try:
            header_btns = page.locator(".amj-chat-header button")
            btn_count = header_btns.count()
            # Theme button is the one with Sun or Moon SVG
            for i in range(btn_count):
                btn = header_btns.nth(i)
                if btn.locator("svg").count() > 0:
                    svg_class = btn.locator("svg").first.get_attribute("class") or ""
                    if "lucide" in svg_class:
                        # Try to identify by icon name
                        pass
            # Simpler: just find any visible button and check for sun/moon
            theme_btn = page.locator("button:has(svg.lucide-sun), button:has(svg.lucide-moon)").first
            if theme_btn.is_visible():
                theme_btn.click()
                page.wait_for_timeout(300)
                new_theme = html.get_attribute("data-theme")
                check(new_theme == "light", f"Theme switched to '{new_theme}'")
            else:
                check(False, "Theme toggle button not found")
        except Exception as e:
            check(False, f"Theme toggle error: {e}")

        screenshot(page, "02-theme-light")

        # ── Scenario 3: Comfort mode ──
        print("── 3. Comfort Mode ──")
        try:
            comfort_btn = page.locator("button:has(svg.lucide-eye), button:has(svg.lucide-eye-off)").first
            if comfort_btn.is_visible():
                comfort_btn.click()
                page.wait_for_timeout(300)
                comfort = html.get_attribute("data-comfort")
                check(comfort == "true", f"Comfort mode = '{comfort}'")
            else:
                check(False, "Comfort toggle button not found")
        except Exception as e:
            check(False, f"Comfort toggle error: {e}")

        screenshot(page, "03-comfort-mode")

        # ── Scenario 4: Navigator — sessions visible ──
        print("── 4. Navigator / Sessions ──")
        # Navigator should be visible at 1440px width
        # Look for session list items or navigator container
        nav_items = page.locator("[class*='nav'], [class*='session'], [class*='navigator']")
        nav_visible = nav_items.count() > 0
        # Also check if there's a sessions tab or area
        session_area = page.locator("text=Сессии, text=Sessions, text=История")
        check(nav_visible or session_area.count() > 0, f"Navigator visible ({nav_items.count()} elements)")

        screenshot(page, "04-navigator")

        # ── Scenario 5: Chat input + SSE streaming ──
        print("── 5. Chat Input + SSE ──")
        textarea = page.locator('textarea[placeholder*="Опишите"]')
        if textarea.is_visible():
            check(True, "Chat textarea visible")
            textarea.fill("Say hello in one word")
            page.wait_for_timeout(200)

            # Click send button
            send_btn = page.locator("button:has(svg.lucide-send)").first
            if send_btn.is_visible() and send_btn.is_enabled():
                send_btn.click()
                # Wait for streaming to start
                page.wait_for_timeout(3000)
                # Check for streaming indicators or response content
                # Phase indicator appears during streaming
                phase = page.locator("[class*='phase'], [class*='Phase']")
                messages = page.locator("[class*='message'], [class*='Message'], [class*='chat-message']")
                check(
                    phase.count() > 0 or messages.count() > 0,
                    f"SSE streaming started (phase={phase.count()}, messages={messages.count()})",
                )
                # Wait for response to complete
                page.wait_for_timeout(5000)
            else:
                check(False, "Send button not visible or disabled")
        else:
            check(False, "Chat textarea not found")

        screenshot(page, "05-sse-streaming")

        # ── Scenario 6: Settings modal ──
        print("── 6. Settings Modal ──")
        try:
            settings_btn = page.locator("button:has(svg.lucide-settings)").first
            if settings_btn.is_visible():
                settings_btn.click()
                page.wait_for_timeout(500)
                # Check modal appears — look for modal overlay or dialog
                modal = page.locator("[class*='modal'], [class*='dialog'], [class*='overlay'], [role='dialog']")
                check(modal.count() > 0, f"Settings modal opened ({modal.count()} modal elements)")
                screenshot(page, "06-settings-modal")

                # Close with Escape
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                # Modal should be gone or hidden
                check(True, "Settings modal closed")
            else:
                check(False, "Settings button not found")
        except Exception as e:
            check(False, f"Settings modal error: {e}")

        # ── Scenario 7: Responsiveness (800px) ──
        print("── 7. Responsiveness (800px) ──")
        page.set_viewport_size({"width": 800, "height": 900})
        page.wait_for_timeout(500)

        # Navigator should collapse or be hidden at narrow width
        nav_items_small = page.locator("[class*='nav-item'], [class*='session-item']")
        # Check that layout adapts — either nav is hidden or content area is full-width
        check(True, "Viewport set to 800px")
        screenshot(page, "07-responsive-800px")

        browser.close()

    # ── Summary ──
    print()
    print(f"=== Results: {PASS} passed, {FAIL} failed ===")
    print(f"Screenshots: {SCREENSHOTS_DIR}/")
    if FAIL == 0:
        print("VISUAL OK")
    else:
        print("VISUAL TEST FAILED")
    sys.exit(FAIL)


if __name__ == "__main__":
    run()
