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
uv run pickled seasonal import  # load Seasonal Produce from the Voedingscentrum calendar
```

Seasonal Produce comes from the Voedingscentrum seizoenskalender, whose terms forbid
publishing a copy, so it is never committed (ADR 0003). `pickled seasonal import` reads the
page into your own database; run it again whenever you want to refresh it. It fails without
changing anything if the page has changed shape, and Pickled runs without it. Which crops
are sold from storage outside their harvest months is our own list, in
`src/pickled/seasonal/storage_crops.toml`.

## Running

```bash
uv run pickled worker                               # background jobs and their schedules
uv run pickled jobs run fetch_deals [--source ah]   # rerun a job by hand, in this process
uv run pickled jobs run tag_deals [--source ah]     # link untagged Deals to Ingredients
```

A finished `fetch_deals` queues `tag_deals` for its store, which the worker runs.

## Development

```bash
uv run pytest              # tests, against the pickled_test database in Compose Postgres
uv run pytest -m live      # live tests: call Runware for real (costs a fraction of a cent)
uv run ruff check .        # lint
uv run ruff format .       # format
uv run alembic revision --autogenerate -m "add x"  # draft a new migration
uv run python scripts/record_deal_fixture.py jumbo  # record a real Deals payload as a fixture
```

Every request to AH or Jumbo, including fixture recording, counts against the store's
budget of 60 requests a week (ADR 0005). Tests read recorded fixtures and never hit the
network. Tests build models through `make_chat_model(role, build=...)` with a fake chat
model, so they never call Runware either; only `-m live` does.

The test database is migrated once per test run, and each test runs in a transaction
that is rolled back, so tests never see each other's data.
