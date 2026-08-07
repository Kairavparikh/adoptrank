from contextlib import asynccontextmanager
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request

from .config import settings
from .index import RankingIndex
from .schemas import (
    ContextEvidenceRequest,
    ContextEvidenceResponse,
    SearchRequest,
    SearchResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if (settings.model_dir / "ranker.pt").exists() and (settings.model_dir / "repositories.jsonl").exists():
        app.state.index = RankingIndex(settings.model_dir)
    else:
        app.state.index = None
    yield


app = FastAPI(title="AdoptRank Ranking API", version="0.2.0", lifespan=lifespan)


def authorize(x_adoptrank_key: str | None = Header(default=None)) -> None:
    if settings.ranker_api_key and (
        x_adoptrank_key is None or not secrets.compare_digest(x_adoptrank_key, settings.ranker_api_key)
    ):
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/health")
def health(request: Request) -> dict:
    return {
        "status": "ok",
        "model_loaded": request.app.state.index is not None,
        "embedding_model": settings.embedding_model,
        "reranker_model": None if settings.disable_reranker else settings.reranker_model,
    }


@app.get("/v1/search", response_model=SearchResponse, dependencies=[Depends(authorize)])
def search(
    request: Request,
    query: str = Query(min_length=2, max_length=500),
    limit: int = Query(default=10, ge=1, le=25),
) -> SearchResponse:
    index: RankingIndex | None = request.app.state.index
    if index is None:
        raise HTTPException(status_code=503, detail="A trained model artifact has not been loaded")
    results = index.search(query, limit)
    watermark = max((repo.captured_at for repo in index.repositories), default=None)
    return SearchResponse(
        query=query,
        results=results,
        model_version="qwen3-infonce-ranknet-v2",
        data_watermark=watermark,
    )


@app.post("/v1/search", response_model=SearchResponse, dependencies=[Depends(authorize)])
def search_with_context(request: Request, payload: SearchRequest) -> SearchResponse:
    index: RankingIndex | None = request.app.state.index
    if index is None:
        raise HTTPException(status_code=503, detail="A trained model artifact has not been loaded")
    results = index.search(payload.query, payload.limit, payload.project_context)
    watermark = max((repo.captured_at for repo in index.repositories), default=None)
    return SearchResponse(
        query=payload.query,
        results=results,
        model_version="qwen3-infonce-ranknet-v2",
        data_watermark=watermark,
    )


@app.post("/v1/context", response_model=ContextEvidenceResponse, dependencies=[Depends(authorize)])
def context_evidence(request: Request, payload: ContextEvidenceRequest) -> ContextEvidenceResponse:
    index: RankingIndex | None = request.app.state.index
    if index is None:
        raise HTTPException(status_code=503, detail="A trained model artifact has not been loaded")
    evidence = index.context_evidence(
        payload.query,
        payload.token_budget,
        payload.limit,
        payload.project_context,
    )
    watermark = max((repo.captured_at for repo in index.repositories), default=None)
    return ContextEvidenceResponse(
        query=payload.query,
        evidence=evidence,
        estimated_tokens=sum(item.estimated_tokens for item in evidence),
        token_budget=payload.token_budget,
        model_version="qwen3-infonce-ranknet-context-v1",
        data_watermark=watermark,
        warnings=(
            []
            if evidence
            else ["No indexed code excerpt passed the relevance and budget constraints."]
        ),
    )
