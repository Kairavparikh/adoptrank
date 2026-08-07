from adoptrank_backend.code_analysis import _priority, extract_code_evidence


def test_extracts_real_code_signals() -> None:
    result = extract_code_evidence(
        [
            ("src/detect.py", "import torch\nclass Detector:\n    def predict(self, stream): return stream"),
            ("tests/test_detect.py", "from src.detect import Detector\ndef test_prediction(): pass"),
        ],
        ["src/detect.py", "tests/test_detect.py", "README.md"],
        "abc123",
    )
    assert result["indexed_commit_sha"] == "abc123"
    assert result["source_file_count"] == 2
    assert result["test_file_count"] == 1
    assert result["symbol_count"] >= 3
    assert "detector" in result["code_terms"]


def test_file_priority_is_stable() -> None:
    assert _priority("tests/test_ranker.py") < _priority("examples/ranker.py") < _priority("src/ranker.py")
