import argparse
import logging

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from pickled import jobs, migrate, seasonal
from pickled.config import Settings
from pickled.stores import Store


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pickled")
    commands = parser.add_subparsers(dest="command", required=True)

    db_parser = commands.add_parser("db", help="manage the database")
    db_commands = db_parser.add_subparsers(dest="db_command", required=True)
    db_commands.add_parser(
        "upgrade", help="run the migrations and set up the LangGraph and Procrastinate schemas"
    )

    commands.add_parser("worker", help="run the background job worker and its schedules")

    jobs_parser = commands.add_parser("jobs", help="run background jobs by hand")
    jobs_commands = jobs_parser.add_subparsers(dest="jobs_command", required=True)
    run_parser = jobs_commands.add_parser("run", help="run a job now, in this process")
    run_parser.add_argument("job", choices=sorted(jobs.RUNNABLE))
    run_parser.add_argument(
        "--source",
        choices=[store.value for store in Store],
        help="for a job run per store; default: every store",
    )

    seasonal_parser = commands.add_parser("seasonal", help="manage Seasonal Produce")
    seasonal_commands = seasonal_parser.add_subparsers(dest="seasonal_command", required=True)
    seasonal_commands.add_parser(
        "import", help="replace Seasonal Produce with the Voedingscentrum calendar"
    )

    args = parser.parse_args(argv)

    if args.command == "db" and args.db_command == "upgrade":
        migrate.upgrade(Settings().database_url)
    elif args.command == "worker":
        logging.basicConfig(level=logging.INFO)
        jobs.run_worker()
    elif args.command == "jobs" and args.jobs_command == "run":
        if args.source and args.job not in jobs.PER_STORE:
            run_parser.error(f"{args.job} is not run per store, so it takes no --source")
        logging.basicConfig(level=logging.INFO)
        jobs.run_job(args.job, args.source)
    elif args.command == "seasonal" and args.seasonal_command == "import":
        import_seasonal_produce()


def import_seasonal_produce() -> None:
    """Download the calendar and replace Seasonal Produce with it in one transaction."""
    engine = create_engine(Settings().database_url)
    try:
        page = seasonal.download_calendar()
        with Session(engine) as session, session.begin():
            summary = seasonal.import_calendar(session, page)
    except (httpx.HTTPError, seasonal.CalendarError) as error:
        raise SystemExit(f"Seasonal Produce not imported, the old data is kept: {error}") from error
    finally:
        engine.dispose()
    print(
        f"Imported {summary.produce} Seasonal Produce entries for {summary.ingredients} "
        f"Ingredients ({summary.stored} stored)."
    )
