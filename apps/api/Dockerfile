FROM python:3.12-slim
WORKDIR /app
COPY . .
# EXTRAS adds optional features, comma separated: rerank (cross-encoder reranker, RERANKER_MODEL)
# and trace (Langfuse tracing, LANGFUSE_*).
ARG EXTRAS=
# The cache mount keeps downloaded wheels between builds, so a code change reinstalls from disk
# instead of downloading every dependency again. It needs BuildKit, the default in Docker 23 and later.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -c constraints.txt ".${EXTRAS:+[$EXTRAS]}"
ENV FASTEMBED_CACHE_PATH=/app/data/models
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
