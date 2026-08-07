FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
ENV MODEL_DIR=/models/qwen EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B RERANKER_MODEL=Qwen/Qwen3-Reranker-0.6B
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[ml,ops]"
COPY artifacts/qwen /models/qwen

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "adoptrank_backend.service:app", "--host", "0.0.0.0", "--port", "8000"]
