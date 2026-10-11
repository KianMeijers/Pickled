# Pickled

A recipe app with an agent you talk to in natural language. It plans weekly meals
around current Albert Heijn and Jumbo deals and seasonal produce in the Netherlands.

## Setup

Needs [uv](https://docs.astral.sh/uv/) and Docker with Compose.

```bash
uv sync                    # create .venv and install dependencies
cp .env.example .env       # then add your RUNWARE_API_KEY
docker compose up -d       # start Postgres (also creates the pickled_test database)
uv run pickled db upgrade  # run migrations and set up the langgraph schema
```

## Development

```bash
uv run pytest              # tests, against the pickled_test database in Compose Postgres
uv run ruff check .        # lint
uv run ruff format .       # format
uv run alembic revision --autogenerate -m "add x"  # draft a new migration
```

The test database is migrated once per test run, and each test runs in a transaction
that is rolled back, so tests never see each other's data.
