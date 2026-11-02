"""The dependency rules from spec §3, checked on the import statements."""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parents[1] / "src" / "pickled"

FORBIDDEN = {
    "stores": {"ingredients", "deals", "seasonal", "planning", "taste", "agent", "web", "jobs"},
    "ingredients": {"deals", "seasonal", "planning", "taste", "agent", "web", "jobs"},
    "deals": {"seasonal", "planning", "taste", "agent", "web", "jobs"},
    "seasonal": {"stores", "deals", "planning", "taste", "agent", "web", "jobs"},
    "taste": {
        "stores",
        "ingredients",
        "deals",
        "seasonal",
        "planning",
        "llm",
        "agent",
        "web",
        "jobs",
    },
    "planning": {"seasonal", "llm", "agent", "web", "jobs"},
    "agent": {"web", "jobs"},
    "llm": {
        "stores",
        "ingredients",
        "deals",
        "seasonal",
        "planning",
        "taste",
        "agent",
        "web",
        "jobs",
    },
}


def imported_modules(module: str) -> set[str]:
    found = set()
    for path in (PACKAGE / module).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module)
    return found


def pickled_modules(imports: set[str]) -> set[str]:
    return {name.split(".")[1] for name in imports if name.startswith("pickled.")}


@pytest.mark.parametrize("module", sorted(FORBIDDEN))
def test_module_imports_nothing_it_must_not_depend_on(module):
    assert pickled_modules(imported_modules(module)) & FORBIDDEN[module] == set()
