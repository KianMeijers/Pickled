"""The seam for telling the Household that something happened. v1 sends no notifications, so it
does nothing; the status line shows what went wrong instead (spec §6)."""


def notify(event: str, **details: object) -> None:
    """Tell the Household about `event`. Does nothing in v1."""
