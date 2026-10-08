# Pickle

A recipe app with an agent you talk to in natural language. It plans weekly meals
around current Albert Heijn and Jumbo deals and seasonal produce in the Netherlands.

## Setup

```bash
uv sync                 # create .venv and install dependencies
cp .env.example .env    # then add your ANTHROPIC_API_KEY
uv run pickle          # run the app
uv run pytest           # run tests
uv run ruff check .     # lint
uv run ruff format .    # format
```
