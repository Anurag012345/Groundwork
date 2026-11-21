"""Administrator CLI for dashboard users. Never exposed over HTTP; connects as the migration role.

    python -m rag.users add --tenant <tenant id> --email person@client.example
    python -m rag.users passwd --email person@client.example     # also signs that user out
    python -m rag.users disable --email person@client.example    # also signs that user out

The password is asked for twice at a prompt, or read from one line of stdin with --password-stdin.
It is never taken from the command line, where it would land in shell history and `ps`.
"""

import argparse
import getpass
import os
import sys
from uuid import UUID

from sqlalchemy import create_engine

from rag.accounts import create_user, disable_user, set_password


def read_password(parser: argparse.ArgumentParser, from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Again: "):
        parser.error("The two passwords differ")
    return password


def main():
    parser = argparse.ArgumentParser(prog="rag.users")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="create a user in a workspace")
    add.add_argument("--tenant", type=UUID, required=True)
    for name, text in (("passwd", "set a new password"), ("disable", "turn a user off")):
        commands.add_parser(name, help=text)
    for command in commands.choices.values():
        command.add_argument("--email", required=True)
    for name in ("add", "passwd"):
        commands.choices[name].add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()
    database_url = os.environ.get("MIGRATION_DATABASE_URL")
    if not database_url:
        parser.error("MIGRATION_DATABASE_URL is required")
    password = read_password(parser, args.password_stdin) if args.command != "disable" else ""
    try:
        with create_engine(database_url).begin() as connection:
            if args.command == "add":
                create_user(connection, args.tenant, args.email, password)
            elif args.command == "passwd":
                set_password(connection, args.email, password)
            else:
                disable_user(connection, args.email)
    except ValueError as error:
        parser.error(str(error))
    print(f"{args.command}: done for {args.email.strip().lower()}")


if __name__ == "__main__":
    main()
