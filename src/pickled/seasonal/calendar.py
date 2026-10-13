"""The Voedingscentrum seizoenskalender, read from its page's JSON-LD (ADR 0003).

The page embeds the calendar as a schema.org FAQPage: one Question per month, named in Dutch,
whose answer is HTML with a `<h3>Seizoensgroente</h3>` and a `<h3>Seizoensfruit</h3>` list.
Its JSON strings hold raw newlines, so it is parsed leniently.

Anything else unexpected raises `CalendarError`, so a changed page never half-loads.
"""

import html
import json
import re
from dataclasses import dataclass

import httpx

CALENDAR_URL = (
    "https://www.voedingscentrum.nl/nl/service/vraag-en-antwoord/"
    "gezonde-voeding-en-voedingsstoffen/wat-zijn-seizoensgroenten-en-seizoensfruit.aspx"
)
USER_AGENT = "Pickled/0.1 (personal meal planner)"
LD_JSON = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)
SECTION = re.compile(r"<h3>(.*?)</h3>\s*<ul>(.*?)</ul>", re.DOTALL)
ITEM = re.compile(r"<li>(.*?)</li>", re.DOTALL)
TAG = re.compile(r"<[^>]+>")

# The lists the calendar has for each month. Herbs or anything else would not be Seasonal Produce.
SECTIONS = {"Seizoensgroente", "Seizoensfruit"}

MONTH_NAMES = (
    "januari februari maart april mei juni juli augustus september oktober november december"
)
MONTHS = {name: number for number, name in enumerate(MONTH_NAMES.split(), start=1)}


class CalendarError(Exception):
    """The page doesn't hold the calendar in the shape it is read in."""


@dataclass(frozen=True)
class CalendarEntry:
    """A name the calendar lists as in season in `month`, as the page writes it."""

    name: str
    month: int


def download_calendar() -> str:
    """The calendar page's HTML."""
    response = httpx.get(
        CALENDAR_URL, headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True
    )
    response.raise_for_status()
    return response.text


def parse_calendar(page: str) -> list[CalendarEntry]:
    """Every (name, month) the calendar on `page` lists; all twelve months must be there."""
    entries = []
    months = set()
    for question in _faq(page):
        try:
            name, answer = question["name"], question["acceptedAnswer"]["text"]
        except (KeyError, TypeError) as error:
            raise CalendarError(f"a month has no name or answer: {question!r:.200}") from error
        if not isinstance(name, str) or not isinstance(answer, str):
            raise CalendarError(f"a month's name or answer isn't text: {question!r:.200}")
        month = MONTHS.get(name.strip().lower())
        if month is None:
            raise CalendarError(f"{name!r} is not a month")
        if month in months:
            raise CalendarError(f"{name!r} is listed twice")
        months.add(month)
        entries.extend(CalendarEntry(item, month) for item in _items(name, answer))
    if missing := set(MONTHS.values()) - months:
        raise CalendarError(f"months missing from the calendar: {sorted(missing)}")
    return entries


def _faq(page: str) -> list:
    """The questions of the page's FAQPage JSON-LD."""
    for block in LD_JSON.findall(page):
        try:
            data = json.loads(block, strict=False)
        except json.JSONDecodeError as error:
            raise CalendarError(f"a JSON-LD block doesn't parse: {error}") from error
        if isinstance(data, dict) and data.get("@type") == "FAQPage":
            questions = data.get("mainEntity")
            if not isinstance(questions, list):
                raise CalendarError("the FAQPage has no list of questions")
            return questions
    raise CalendarError("the page has no FAQPage JSON-LD")


def _items(month: str, answer: str) -> list[str]:
    """The names in one month's answer, after checking it has exactly the expected lists."""
    sections = {_text(heading): items for heading, items in SECTION.findall(answer)}
    if set(sections) != SECTIONS or answer.count("<ul>") != len(SECTIONS):
        raise CalendarError(f"{month} has the lists {sorted(sections)}, not {sorted(SECTIONS)}")
    names = [_text(item) for items in sections.values() for item in ITEM.findall(items)]
    if not names or not all(names):
        raise CalendarError(f"{month} has an empty list or item")
    return names


def _text(fragment: str) -> str:
    return " ".join(html.unescape(TAG.sub(" ", fragment)).split())
