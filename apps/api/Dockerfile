FROM python:3.12-slim
WORKDIR /app
COPY . .
# EXTRAS=rerank adds the optional cross-encoder reranker (RERANKER_MODEL).
ARG EXTRAS=
RUN pip install --no-cache-dir -c constraints.txt ".${EXTRAS:+[$EXTRAS]}"
ENV FASTEMBED_CACHE_PATH=/app/data/models
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
