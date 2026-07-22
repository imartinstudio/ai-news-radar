from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_creator_page_loads_public_history_json():
    html = read("creator/index.html")
    app = read("creator/assets/app.js")

    assert "./assets/styles.css" in html
    assert "./assets/app.js" in html
    assert "../data/creator-editions.json" in app
    assert 'id="editionList"' in html
    assert 'id="statusFilter"' in html
    assert 'id="editionFilter"' in html


def test_creator_page_renders_source_links_safely():
    app = read("creator/assets/app.js")

    assert "function escapeHtml" in app
    assert "function safeUrl" in app
    assert 'rel="noopener noreferrer"' in app
    assert "innerHTML" in app


def test_creator_page_has_no_third_party_runtime_dependency():
    html = read("creator/index.html")

    assert "https://unpkg.com" not in html
    assert "https://cdn.jsdelivr.net" not in html
