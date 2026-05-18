import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path(__file__).parent.parent / "data" / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def audit_page(page, url, name):
    errors = []
    network_fails = []

    def on_console(msg):
        if msg.type in ("error", "warning"):
            errors.append(f"CONSOLE {msg.type.upper()}: {msg.text}")

    def on_page_error(err):
        errors.append(f"PAGE ERROR: {err}")

    def on_request_failed(req):
        network_fails.append(
            f"NETWORK FAIL: {req.method} {req.url} — {req.failure}"
        )

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("requestfailed", on_request_failed)

    print(f"\n{'='*60}")
    print(f"Navigating to: {url}")
    print(f"{'='*60}")

    try:
        response = page.goto(url, wait_until="networkidle", timeout=30000)
        if response:
            print(f"HTTP Status: {response.status} {response.status_text}")
    except Exception as e:
        print(f"Navigation error: {e}")

    # Wait for async rendering
    page.wait_for_timeout(3000)

    screenshot_path = str(SCREENSHOT_DIR / f"{name}.png")
    page.screenshot(path=screenshot_path, full_page=True)
    print(f"Screenshot saved: {screenshot_path}")

    title = page.title()
    print(f"Page title: {title}")

    # Headings and nav links
    try:
        headings = page.eval_on_selector_all(
            "h1, h2, h3, nav a, [role='navigation'] a",
            "els => els.map(el => el.tagName + ': ' + el.textContent.trim().substring(0, 100))"
            ".filter(s => s.length > 5)"
        )
        if headings:
            print("Headings/Nav links:")
            for h in headings[:25]:
                print(f"  {h}")
    except Exception as e:
        print(f"  (Could not get headings: {e})")

    # All links
    try:
        links = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(el => ({text: el.textContent.trim().substring(0, 50), href: el.href})).filter(l => l.text.length > 0)"
        )
        if links:
            print("Links found:")
            for l in links[:25]:
                print(f'  "{l["text"]}" -> {l["href"]}')
    except Exception as e:
        print(f"  (Could not get links: {e})")

    # Error messages on page
    try:
        error_texts = page.eval_on_selector_all(
            "[class*='error'], [class*='Error'], [role='alert'], [class*='warning']",
            "els => els.map(el => el.textContent.trim().substring(0, 200))"
        )
        visible_errors = [e for e in error_texts if e.strip()]
        if visible_errors:
            print("Error/alert elements on page:")
            for e in visible_errors:
                print(f"  {e}")
    except Exception as e:
        print(f"  (Could not check error elements: {e})")

    # Loading states
    try:
        loading_count = page.eval_on_selector_all(
            "[class*='loading'], [class*='skeleton'], [class*='spinner'], [class*='Spinner']",
            "els => els.length"
        )
        if loading_count:
            print(f"Loading/skeleton elements still visible: {loading_count}")
    except Exception as e:
        pass

    # Body text snippet
    try:
        body_text = page.inner_text("body")
        snippet = body_text.strip()[:1000]
        print(f"\nPage body text (first 1000 chars):\n{snippet}")
    except Exception as e:
        print(f"Could not read body text: {e}")

    if errors:
        print(f"\nConsole/Page errors ({len(errors)}):")
        for e in errors:
            print(f"  {e}")
    else:
        print("\nNo console errors detected.")

    if network_fails:
        print(f"\nNetwork failures ({len(network_fails)}):")
        for e in network_fails:
            print(f"  {e}")
    else:
        print("No network failures detected.")

    return errors, network_fails, links if 'links' in dir() else []


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})

        page = context.new_page()
        errors, network_fails, links = audit_page(
            page, "https://app.aipredictedwins.com", "main"
        )

        # Collect sub-page links from nav
        try:
            nav_links = page.eval_on_selector_all(
                "nav a, [role='navigation'] a, aside a, .sidebar a, [class*='nav'] a, [class*='Nav'] a",
                "els => els.map(el => ({text: el.textContent.trim(), href: el.href})).filter(l => l.href && !l.href.startsWith('#'))"
            )
        except Exception:
            nav_links = []

        base = "https://app.aipredictedwins.com"
        visited = {base, base + "/"}
        print(f"\n=== Sub-pages to visit (found {len(nav_links)} nav links) ===")
        for l in nav_links:
            print(f'  "{l["text"]}" -> {l["href"]}')

        count = 0
        for link in nav_links:
            if count >= 6:
                break
            href = link["href"]
            if href in visited:
                continue
            if "app.aipredictedwins.com" not in href:
                continue
            visited.add(href)
            sub_page = context.new_page()
            safe_name = "".join(c if c.isalnum() else "_" for c in href)[:40]
            audit_page(sub_page, href, f"subpage_{safe_name}")
            sub_page.close()
            count += 1

        browser.close()
        print("\n=== Audit complete ===")


if __name__ == "__main__":
    main()
