"""The web app: FastAPI routes, Jinja templates with HTMX, and chat over SSE (spec §8)."""

from pickled.web.app import create_app
from pickled.web.services import Services

__all__ = ["Services", "create_app"]
