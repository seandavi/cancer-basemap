"""Render site/social-card.png (1200x630 Open Graph / Twitter card).

Regenerate:  uvx --from playwright python site/social/make_card.py
The map is the landing page's build-time extract (site/extracts/home_map.json);
no release date on the card, so it doesn't go stale between releases (the
map legend names its own source and edition). Needs network for the CDN
libraries (d3-geo, topojson-client, us-atlas) and web fonts.
"""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
SITE = HERE.parent
CHROME = "/home/davsean/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome"
MEASURE, YEAR = "PLACES:COLON_SCREEN:age_adjusted", "2025"

data = json.loads((SITE / "extracts/home_map.json").read_text())
label = next(m["label"] for m in data["measures"] if m["id"] == MEASURE)
html = (
    (HERE / "card.html").read_text()
    .replace("__ROWS__", json.dumps(data["obs"][YEAR][MEASURE]))
    .replace("__MEASURE__", label)
    .replace("__YEAR__", f"PLACES {YEAR} release")
)
out = HERE / "card.rendered.html"  # scratch; served via file:// so the module imports work
out.write_text(html)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME)
    page = browser.new_page(viewport={"width": 1200, "height": 630})
    page.goto(out.as_uri())
    page.wait_for_selector("body[data-ready]", timeout=60000)
    page.screenshot(path=str(SITE / "social-card.png"))
    browser.close()
out.unlink()
print("wrote site/social-card.png")
