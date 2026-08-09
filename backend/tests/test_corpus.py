from datetime import UTC, datetime

from adoptrank_backend.corpus import snapshot_from_catalog_row
from adoptrank_backend.vector_index import _chunk_path


def test_catalog_row_and_code_chunk_keep_commit_provenance() -> None:
    row = {
        "full_name": "example/engine",
        "description": "matching engine",
        "language": "Rust",
        "license_spdx": "MIT",
        "topics": ["trading"],
        "stars": 10,
        "forks": 2,
        "is_archived": False,
        "github_updated_at": datetime(2026, 8, 7, tzinfo=UTC),
    }
    snapshot = snapshot_from_catalog_row(row).model_copy(
        update={"indexed_commit_sha": "abc123", "code_evidence_paths": ["src/lib.rs"]}
    )

    assert snapshot.html_url == "https://github.com/example/engine"
    assert snapshot.pushed_at == row["github_updated_at"]
    assert _chunk_path(snapshot, "File: src/book.rs\nfn match_order() {}", 0) == "src/book.rs"
