# The app and the worker in one image, run by the `app` Compose profile.
FROM ghcr.io/astral-sh/uv:0.9.5-python3.14-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1

# Dependencies first, so a code change doesn't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

COPY README.md alembic.ini ./
COPY src ./src
RUN uv sync --locked

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "pickled.web.app:production_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
