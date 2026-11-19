"""Admin commands for a hosted server.

python -m finagent.cli reset-password someone@example.com
python -m finagent.cli list-users
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from .db import global_session, init_db
from .models import Business, Membership, User
from .services.auth import AuthError, set_password


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m finagent.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("reset-password", help="Set a new password (signs the user out everywhere)")
    rp.add_argument("email")
    sub.add_parser("list-users", help="List accounts and their businesses")
    args = ap.parse_args(argv)

    init_db()
    with global_session() as db:
        if args.cmd == "reset-password":
            pw = getpass.getpass("New password: ")
            if pw != getpass.getpass("Repeat: "):
                print("Passwords do not match.", file=sys.stderr)
                return 1
            try:
                set_password(db, args.email, pw)
            except AuthError as exc:
                print(exc, file=sys.stderr)
                return 1
            print("Password updated.")
        elif args.cmd == "list-users":
            rows = db.execute(
                select(User.email, Business.name, Membership.role)
                .join(Membership, Membership.user_id == User.id)
                .join(Business, Business.id == Membership.business_id)
                .order_by(User.email)
            ).all()
            for email, biz, role in rows:
                print(f"{email:40} {role:7} {biz}")
            print(f"{len(rows)} account(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
