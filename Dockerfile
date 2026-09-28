FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.18
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra postgres --extra migrations --no-editable \
    && groupadd --system app && useradd --system --gid app --home-dir /app app \
    && mkdir /app/data && chown app:app /app/data
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts/smoke_installed.py scripts/verify_demo.py scripts/sql_walkthrough.py ./scripts/
ENV PATH="/app/.venv/bin:$PATH" DATABASE_URL="sqlite:////app/data/agent_eval.db"
USER app
# Stdio is the safe default; no HTTP listener is exposed by this image.
ENTRYPOINT ["agent-eval"]
CMD ["serve"]
