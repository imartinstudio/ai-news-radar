from pathlib import Path

WORKFLOW = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")


def test_ci_runs_full_suite_with_development_dependencies():
    assert "pip install -r requirements-dev.txt" in WORKFLOW
    assert "python -m compileall -q scripts" in WORKFLOW
    assert "python -m pytest -q" in WORKFLOW
    assert "contents: read" in WORKFLOW
