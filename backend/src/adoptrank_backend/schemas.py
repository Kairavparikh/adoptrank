from datetime import datetime

from pydantic import BaseModel, Field


class RepositorySnapshot(BaseModel):
    full_name: str
    html_url: str
    captured_at: datetime
    description: str = ""
    language: str = "Unknown"
    license_spdx: str = "NOASSERTION"
    topics: list[str] = Field(default_factory=list)
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    watchers: int = 0
    size_kb: int = 0
    archived: bool = False
    fork: bool = False
    pushed_at: datetime | None = None
    created_at: datetime | None = None
    latest_release_at: datetime | None = None
    contributors_sampled: int = 0
    pypi_package: str | None = None
    pypi_downloads_1d: int | None = None
    pypi_downloads_7d: int | None = None
    pypi_downloads_30d: int | None = None
    pypi_latest_release: datetime | None = None
    source_query: str = ""
    indexed_commit_sha: str | None = None
    source_file_count: int = 0
    test_file_count: int = 0
    example_file_count: int = 0
    dependency_count: int = 0
    symbol_count: int = 0
    code_terms: list[str] = Field(default_factory=list)
    code_evidence_paths: list[str] = Field(default_factory=list)
    architecture_summary: str = ""
    code_chunks: list[str] = Field(default_factory=list)
    quality_score: float = 0.0
    depth_score: float = 0.0
    originality_score: float = 0.0


class ProjectContext(BaseModel):
    root_name: str = ""
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    summary: str = ""


class TrainingPair(BaseModel):
    query: str
    positive: RepositorySnapshot
    negative: RepositorySnapshot
    adoption_target: float | None = None
    observed_at: datetime


class RankedRepository(BaseModel):
    full_name: str
    url: str
    description: str
    score: float
    adoption_probability: float | None
    reason: str
    language: str
    license: str
    updated_at: datetime | None
    source: str = "pytorch"
    code_evidence: list[str] = Field(default_factory=list)
    relevance_score: float = 0.0
    depth_score: float = 0.0
    quality_score: float = 0.0
    maintenance_score: float = 0.0
    originality_score: float = 0.0


class SearchResponse(BaseModel):
    query: str
    results: list[RankedRepository]
    model_version: str
    data_watermark: datetime | None


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=10, ge=1, le=25)
    project_context: ProjectContext | None = None
