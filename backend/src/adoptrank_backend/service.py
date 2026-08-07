from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request

from .config import settings
from .index import RankingIndex
from .schemas import SearchResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    if (settings.model_dir / "ranker.pt").exists() and (settings.model_dir / "repositories.jsonl").exists():
        app.state.index = RankingIndex(settings.model_dir)
    else:
        app.state.index = None
    yield


app = FastAPI(title="AdoptRank Ranking API", version="0.1.0", lifespan=lifespan)


def authorize(x_adoptrank_key: str | None = Header(default=None)) -> None:
    if settings.ranker_api_key and x_adoptrank_key != settings.ranker_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/health")
def health(request: Request) -> dict:
    return {"status": "ok", "model_loaded": request.app.state.index is not None}


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
        model_version="pytorch-ranknet-v1",
        data_watermark=watermark,
    )
