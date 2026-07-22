import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_creator_pipeline_can_run_as_a_direct_script():
    result = subprocess.run(
        [sys.executable, "scripts/creator_pipeline.py", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Build personal AI Coding creator editions" in result.stdout
