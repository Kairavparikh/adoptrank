from pathlib import Path

from adoptrank_backend.local_scan import scan_project


def test_scanner_excludes_secrets(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("import torch\ndef detect_stream(): return True")
    (tmp_path / "requirements.txt").write_text("torch==2.7.1\nfastapi==0.128.3\n")
    (tmp_path / ".env").write_text("API_KEY=never-read")
    context = scan_project(tmp_path)
    assert "python" in context.languages
    assert "torch" in context.dependencies
    assert "never-read" not in context.model_dump_json()
