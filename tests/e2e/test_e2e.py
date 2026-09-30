"""End-to-end test in a real browser (Chromium via Playwright). Starts its own server on a free port.

    pip install -r requirements-dev.txt && python -m playwright install chromium   (once)
    pytest tests/e2e -q
Covers: open app → dashboard → inspect risk → map → submit report → water quality → rainwater calculator →
treated-water match → admin reviews report; plus console errors, mobile width, dark mode and keyboard access.
"""
import io
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[2]
ADMIN = ("admin@jalsetu.test", "correct-horse-battery")


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture(scope="module")
def base():
    port = _free_port()
    env = {**os.environ, "JALSETU_DB": os.path.join(tempfile.mkdtemp(), "e2e.db"), "ADMIN_EMAIL": ADMIN[0], "ADMIN_PASSWORD": ADMIN[1],
           "JALSETU_WRITE_LIMIT": "10000", "JALSETU_LOGIN_LIMIT": "10000"}
    env.pop("DATABASE_URL", None); env.pop("POSTGRES_URL", None); env.pop("ANTHROPIC_API_KEY", None); env.pop("JALSETU_DEMO", None)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "/api/health", timeout=1); break
        except Exception:
            time.sleep(0.25)
    yield url
    proc.terminate(); proc.wait(5)


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        exe = "/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None
        try:
            b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        except Exception as e:
            pytest.skip(f"Chromium not available: {e}")
        yield b
        b.close()


def _page(browser, **kw):
    ctx = browser.new_context(**kw)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(f"JS error: {e}"))
    page.on("console", lambda m: errors.append(f"CSP: {m.text}") if m.type == "error" and "Content Security Policy" in m.text else None)
    page.on("response", lambda r: errors.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and "/api/" in r.url else None)
    page.route("**/*", lambda route: route.abort() if not route.request.url.startswith("http://127.0.0.1") else route.continue_())
    return ctx, page, errors


def _wait(page, js: str, timeout: float = 15) -> None:
    """Poll a JS expression from Python. (Playwright's wait_for_function uses eval, which JalSetu's CSP correctly blocks.)"""
    end = time.time() + timeout
    while time.time() < end:
        if page.evaluate(js):
            return
        time.sleep(0.15)
    raise AssertionError(f"timed out waiting for: {js}")


def _tab(page, v):
    page.click(f'nav.tabs button[data-v="{v}"]')


def _jpeg():
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (1600, 1200), (60, 90, 120)).save(b, "JPEG"); return b.getvalue()


def test_full_user_journey(base, browser, tmp_path):
    ctx, page, errors = _page(browser, viewport={"width": 1280, "height": 900})
    # 1-2. open app, dashboard
    page.goto(base + "/")
    page.wait_for_selector(".gauge b")
    score = float(page.inner_text(".gauge b"))
    assert 0 < score <= 100 and page.inner_text("#riskPanel .pill") in ("LOW", "MODERATE", "HIGH", "CRITICAL")
    assert page.locator(".contrib .pts").count() == 6
    assert page.locator("#warnings .warn").count() >= 1
    assert page.locator("#indCards .card").count() == 8 and page.locator("#indCards .prov a").count() >= 6
    # 3. inspect risk explanation
    page.click("#riskPanel details summary")
    assert page.locator("#riskPanel details table tbody tr").count() == 6
    # 4. map with real ward polygons, lakes and filters
    _tab(page, "map")
    _wait(page, "document.querySelectorAll('#map path.leaflet-interactive').length > 240")
    page.locator("#map path.leaflet-interactive").nth(40).click(force=True)
    assert "Ward" in page.inner_text("#wardInfo h3")
    # 5. submit a report with photo on a map point
    _tab(page, "report")
    page.select_option("#rCat", "groundwater")
    page.select_option("#rArea", "Whitefield")
    page.fill("#rDesc", "E2E: borewell dry since Monday")
    photo = tmp_path / "p.jpg"; photo.write_bytes(_jpeg())
    page.set_input_files("#rPhoto", str(photo))
    page.click("#repBtn")
    _wait(page, "document.querySelector('#reports').innerText.includes('E2E: borewell dry')")
    assert page.locator("#reports img").count() >= 1 and "Submitted" in page.inner_text("#reports .item")
    # 6. water quality: safe / high / unsafe
    _tab(page, "quality")
    page.wait_for_selector("#q-no3")
    page.fill("#q-no3", "30"); _wait(page, "document.querySelector('#qs-no3').innerText.includes('Safe')")
    page.fill("#q-tds", "1200"); _wait(page, "document.querySelector('#qs-tds').innerText.includes('High')")
    page.fill("#q-no3", "60"); _wait(page, "document.querySelector('#qVerdict').innerText.includes('Not safe')")
    # 7. rainwater calculator
    _tab(page, "recharge")
    page.select_option("#sAge", "old"); page.fill("#sL", "60"); page.fill("#sW", "40"); page.fill("#bill", "800")
    _wait(page, "document.querySelector('#rwhOut').innerText.includes('₹8,400')")
    assert "Harvest (L) = rainfall" in page.inner_text("#rwhOut")
    # 8. treated-water: organization registers, offers, requests, ranks matches
    _tab(page, "exchange")
    page.click("#loginBtn"); page.click("#modeReg")
    page.fill("#aEmail", f"org-{uuid.uuid4().hex[:6]}@example.com"); page.fill("#aPass", "long-enough-pass")
    page.fill("#aName", "Asha"); page.select_option("#aRole", "organization"); page.fill("#aOrg", "Lakeview Apartments")
    page.click("#authSubmit")
    page.wait_for_selector("#offerPanel:not([hidden])")
    page.select_option("#oArea", "Marathahalli"); page.fill("#oQty", "80")
    page.fill("#oFrom", "2026-10-01"); page.fill("#oTo", "2027-03-31")
    page.check('#oCats input[value="construction"]'); page.click("#offerForm button[type=submit]")
    _wait(page, "document.querySelector('#offers').innerText.includes('Lakeview Apartments')")
    page.fill("#qName", "Site A"); page.select_option("#qArea", "Whitefield"); page.fill("#qQty", "60")
    page.select_option("#qPurpose", "construction"); page.fill("#qFrom", "2026-10-15"); page.fill("#qTo", "2026-12-15")
    page.click("#reqForm button[type=submit]")
    page.wait_for_selector("[data-match]")
    page.click("[data-match]")
    _wait(page, "document.querySelector('.match') && document.querySelector('.match').innerText.includes('#1 Lakeview Apartments')")
    assert "5.5 km apart" in page.inner_text(".match")
    # rain + ML page runs a prediction and shows its explanation
    _tab(page, "rain")
    page.wait_for_selector("#seasonChart svg")
    page.select_option("#mlYear", "2002")
    page.click("#mlForm button[type=submit]")
    _wait(page, "document.querySelector('#mlOut').innerText.includes('Model: random_forest')")
    assert page.locator("#mlOut .bar-pn").count() == 5 and "Random Forest (selected)" in page.inner_text("#mlEval")
    # 9. admin reviews the report
    a_ctx, admin, a_err = _page(browser, viewport={"width": 1280, "height": 900})
    admin.goto(base + "/admin")
    admin.fill("#email", ADMIN[0]); admin.fill("#pass", ADMIN[1]); admin.click("#loginForm button")
    admin.wait_for_selector("#repRows button[data-to='UNDER_REVIEW']")
    admin.click("#repRows button[data-to='UNDER_REVIEW']")
    admin.wait_for_selector("#repRows button[data-to='VERIFIED']")
    admin.click("#repRows button[data-to='VERIFIED']")
    _wait(admin, "document.querySelector('#audit').innerText.includes('report_status')")
    # admin deletes a report after confirming the dialog; list and counts refresh
    extra = admin.evaluate("""async () => { const r = await fetch('/api/reports', {method: 'POST', body: (() => { const f = new FormData();
        f.append('category', 'other'); f.append('area', 'Hebbal'); f.append('description', 'E2E rehearsal to delete'); return f; })()}); return (await r.json()).id; }""")
    admin.reload(); admin.wait_for_selector(f"button[data-del='{extra}']")
    admin.once("dialog", lambda d: d.accept())
    admin.click(f"button[data-del='{extra}']")
    _wait(admin, f"!document.querySelector(\"button[data-del='{extra}']\")")
    _wait(admin, "document.querySelector('#audit').innerText.includes('report_delete')")
    # admin makes another registered user an admin from the Users table
    admin.wait_for_selector("select[data-role]")
    sel = admin.locator("select[data-role]").filter(has=admin.locator("option[selected]", has_text="organization")).first
    admin.once("dialog", lambda d: d.accept())
    sel.select_option("admin")
    _wait(admin, "document.querySelector('#audit').innerText.includes('user_role')")
    page.reload(); _tab(page, "report")
    _wait(page, "document.querySelector('#reports').innerText.includes('Verified')")
    assert not errors and not a_err, errors + a_err
    ctx.close(); a_ctx.close()


@pytest.mark.parametrize("width,scheme", [(320, "dark"), (390, "light"), (768, "dark"), (1366, "light")])
def test_no_sideways_scroll_any_tab(base, browser, width, scheme):
    ctx, page, errors = _page(browser, viewport={"width": width, "height": 800}, color_scheme=scheme)
    page.goto(base + "/"); page.wait_for_selector(".gauge b")
    for v in ("overview", "rain", "map", "report", "exchange", "quality", "recharge"):
        _tab(page, v); page.wait_for_timeout(400)
        assert page.evaluate("document.documentElement.scrollWidth") <= width, f"{v} scrolls sideways at {width}px"
    assert not errors, errors
    ctx.close()


def test_keyboard_reaches_every_tab_with_visible_focus(base, browser):
    ctx, page, _ = _page(browser, viewport={"width": 1280, "height": 900})
    page.goto(base + "/"); page.wait_for_selector(".gauge b")
    seen, no_ring = set(), []
    for _ in range(160):
        page.keyboard.press("Tab")
        info = page.evaluate("""() => { const e = document.activeElement; if (!e || e === document.body) return null;
            const s = getComputedStyle(e); return {tab: e.dataset.v || null, ring: s.outlineStyle !== 'none' && s.outlineWidth !== '0px', tag: e.tagName}; }""")
        if not info:
            continue
        if info["tab"]:
            seen.add(info["tab"])
        if not info["ring"] and info["tag"] in ("BUTTON", "A", "INPUT", "SELECT"):
            no_ring.append(info["tag"])
    assert seen == {"overview", "rain", "map", "report", "exchange", "quality", "recharge"}
    assert not no_ring
    page.focus('nav.tabs button[data-v="quality"]'); page.keyboard.press("Enter")
    assert not page.is_hidden("#v-quality")
    ctx.close()


def test_main_site_login_and_delete_own_report(base, browser):
    ctx, page, errors = _page(browser, viewport={"width": 390, "height": 844})
    page.goto(base + "/"); page.wait_for_selector(".gauge b")
    email = f"friend-{uuid.uuid4().hex[:6]}@example.com"
    page.click("#loginBtn"); page.click("#modeReg")
    page.fill("#aEmail", email); page.fill("#aPass", "friend-pass-1"); page.fill("#aName", "Friend"); page.click("#authSubmit")
    _wait(page, "document.querySelector('#acct').innerText.includes('Friend')")
    page.click("#logoutBtn"); _wait(page, "!!document.querySelector('#loginBtn')")
    # log back in with the Log in tab (not registration)
    page.click("#loginBtn"); page.fill("#aEmail", email.upper()); page.fill("#aPass", "friend-pass-1"); page.click("#authSubmit")
    _wait(page, "document.querySelector('#acct').innerText.includes('Friend')")
    _tab(page, "report")
    page.select_option("#rCat", "other"); page.select_option("#rArea", "Hebbal"); page.fill("#rDesc", "friend test report")
    page.click("#repBtn")
    _wait(page, "!!document.querySelector('[data-delmine]')")
    page.once("dialog", lambda d: d.accept())
    page.click("[data-delmine]")
    _wait(page, "!document.querySelector('#reports').innerText.includes('friend test report')")
    assert not errors, errors
    ctx.close()


def test_admin_login_failure_explains_problem(base, browser):
    ctx, page, errors = _page(browser, viewport={"width": 1280, "height": 900})
    page.goto(base + "/admin")
    page.fill("#email", ADMIN[0]); page.fill("#pass", "Wrong-password-here"); page.click("#loginForm button")
    _wait(page, "document.querySelector('#loginErr').innerText.includes(\"doesn't match ADMIN_PASSWORD\")")
    page.fill("#email", "someone@else.com"); page.click("#loginForm button")
    _wait(page, "document.querySelector('#loginErr').innerText.includes('not the admin email')")
    ctx.close()
