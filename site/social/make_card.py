"""Render site/social-card.png (1200x630 Open Graph / Twitter card).

Regenerate:  uvx --from playwright python site/social/make_card.py
The map is the landing page's build-time extract (site/extracts/home_map.json);
the release date is read from the live manifest. Needs network for the CDN
libraries (d3-geo, topojson-client, us-atlas) and web fonts.
"""
import json
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
SITE = HERE.parent
CHROME = "/home/davsean/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome"
MEASURE, YEAR = "PLACES:COLON_SCREEN:age_adjusted", "2025"
MANIFEST = "https://basemap.cancerdatasci.org/data/latest/manifest.json"

# Cloudflare blocks urllib's default User-Agent.
req = urllib.request.Request(MANIFEST, headers={"User-Agent": "cancer-basemap-social-card/1.0"})
release = json.load(urllib.request.urlopen(req, timeout=30))["release"]

data = json.loads((SITE / "extracts/home_map.json").read_text())
label = next(m["label"] for m in data["measures"] if m["id"] == MEASURE)
html = (
    (HERE / "card.html").read_text()
    .replace("__ROWS__", json.dumps(data["obs"][YEAR][MEASURE]))
    .replace("__MEASURE__", label)
    .replace("__YEAR__", f"PLACES {YEAR} release")
    .replace("__RELEASE__", release)
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
print(f"wrote site/social-card.png (release {release})")
