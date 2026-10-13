import argparse

from pickled import migrate
from pickled.config import Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pickled")
    commands = parser.add_subparsers(dest="command", required=True)

    db_parser = commands.add_parser("db", help="manage the database")
    db_commands = db_parser.add_subparsers(dest="db_command", required=True)
    db_commands.add_parser(
        "upgrade", help="run the Alembic migrations and set up the LangGraph schema"
    )

    args = parser.parse_args(argv)

    if args.command == "db" and args.db_command == "upgrade":
        migrate.upgrade(Settings().database_url)
