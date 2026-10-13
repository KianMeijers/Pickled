# Pickled

A recipe app with an agent you talk to in natural language. It plans weekly meals
around current Albert Heijn and Jumbo deals and seasonal produce in the Netherlands.

## Setup

Needs [uv](https://docs.astral.sh/uv/) and Docker with Compose.

```bash
uv sync                    # create .venv and install dependencies
cp .env.example .env       # then add your RUNWARE_API_KEY
docker compose up -d       # start Postgres (also creates the pickled_test database)
uv run pickled db upgrade  # run migrations and set up the langgraph and procrastinate schemas
```

## Running

```bash
uv run pickled worker                               # background jobs and their schedules
uv run pickled jobs run fetch_deals [--source ah]   # rerun a job by hand, in this process
```

## Development

```bash
uv run pytest              # tests, against the pickled_test database in Compose Postgres
uv run ruff check .        # lint
uv run ruff format .       # format
uv run alembic revision --autogenerate -m "add x"  # draft a new migration
uv run python scripts/record_deal_fixture.py jumbo  # record a real Deals payload as a fixture
```

Every request to AH or Jumbo, including fixture recording, counts against the store's
budget of 60 requests a week (ADR 0005). Tests read recorded fixtures and never hit the
network.

The test database is migrated once per test run, and each test runs in a transaction
that is rolled back, so tests never see each other's data.
