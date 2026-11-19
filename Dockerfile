# Google mirror of Docker Hub: avoids anonymous pull rate limits.
FROM mirror.gcr.io/library/python:3.12-slim
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH" PORT=8080
# Serves the ADK dev UI/API; replace with the production API once it exists.
CMD ["sh", "-c", "adk api_server --host 0.0.0.0 --port $PORT src/issue_to_repro"]
