"""Every site page has a title. #201 left site/concepts/index.qmd empty, which Quarto
renders as a blank page listed by its filename in the sidebar."""

from pathlib import Path

import pytest

PAGES = sorted(p for p in (Path(__file__).parent.parent / "site").rglob("*.qmd")
               if not p.name.startswith("_") and "_site" not in p.parts and "_freeze" not in p.parts)


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(p.parents[len(p.parts) - 2])))
def test_page_has_a_title(page):
    head = page.read_text().split("---")
    assert len(head) >= 3 and "title:" in head[1], f"{page} has no front-matter title"
