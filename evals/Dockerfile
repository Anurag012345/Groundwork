# The production API image plus fastembed, so evals can rerank. Build context is apps/api.
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -c constraints.txt . && pip install --no-cache-dir fastembed
ENV FASTEMBED_CACHE_PATH=/models
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
