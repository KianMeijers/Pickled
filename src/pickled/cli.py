import argparse
import logging

from pickled import jobs, migrate
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
        "--source", choices=[store.value for store in Store], help="default: every store"
    )

    args = parser.parse_args(argv)

    if args.command == "db" and args.db_command == "upgrade":
        migrate.upgrade(Settings().database_url)
    elif args.command == "worker":
        logging.basicConfig(level=logging.INFO)
        jobs.run_worker()
    elif args.command == "jobs" and args.jobs_command == "run":
        logging.basicConfig(level=logging.INFO)
        jobs.run_job(args.job, args.source)
