import hashlib
from pathlib import Path

import asyncpg

from .embeddings import QwenEmbedder
from .schemas import RepositorySnapshot


def load_snapshots(path: Path) -> list[RepositorySnapshot]:
    with path.open() as handle:
        return [RepositorySnapshot.model_validate_json(line) for line in handle if line.strip()]


async def populate_pgvector(database_url: str, snapshots_path: Path) -> int:
    snapshots = [repo for repo in load_snapshots(snapshots_path) if repo.indexed_commit_sha]
    return await populate_pgvector_snapshots(database_url, snapshots)


def _chunk_path(repo: RepositorySnapshot, chunk: str, index: int) -> str:
    first_line = chunk.splitlines()[0] if chunk else ""
    if first_line.startswith("File: "):
        return first_line.removeprefix("File: ").strip()
    if repo.code_evidence_paths:
        return repo.code_evidence_paths[min(index, len(repo.code_evidence_paths) - 1)]
    return "repository-summary"


async def populate_pgvector_snapshots(
    database_url: str, snapshots: list[RepositorySnapshot]
) -> int:
    snapshots = [repo for repo in snapshots if repo.indexed_commit_sha]
    records = []
    for repo in snapshots:
        chunks = repo.code_chunks or [repo.architecture_summary]
        for index, chunk in enumerate(chunks):
            if chunk:
                records.append((repo, index, chunk))
    vectors = QwenEmbedder().encode_documents([chunk for _, _, chunk in records])
    connection = await asyncpg.connect(database_url)
    written = 0
    try:
        async with connection.transaction():
            for (repo, index, chunk), vector in zip(records, vectors, strict=True):
                repository_id = await connection.fetchval(
                    "select id from repositories where full_name=$1", repo.full_name
                )
                if not repository_id:
                    continue
                path = _chunk_path(repo, chunk, index)
                vector_literal = "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"
                await connection.execute(
                    """insert into code_chunk_embeddings(repository_id,commit_sha,path,chunk_index,content_hash,model_version,embedding,summary) values($1,$2,$3,$4,$5,$6,$7::vector,$8) on conflict(repository_id,commit_sha,path,chunk_index,model_version) do update set embedding=excluded.embedding,summary=excluded.summary,content_hash=excluded.content_hash,embedded_at=now()""",
                    repository_id,
                    repo.indexed_commit_sha,
                    path,
                    index,
                    hashlib.sha256(chunk.encode()).hexdigest(),
                    "qwen3-embedding-v1",
                    vector_literal,
                    chunk[:2000],
                )
                written += 1
    finally:
        await connection.close()
    return written
