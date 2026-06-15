"""Create or update the admin user.

Run via the Makefile target ``make create-admin`` (reads ADMIN_* from .env), or
directly:

    uv run python -m scripts.create_admin --username admin --email a@b.c --password secret

Idempotent: re-running updates the existing admin's password.
"""

import argparse
import sys

from app.auth.password import hash_password
from app.core.config import settings
from app.db.database import close_client, get_mongo_database, get_next_sequence
from app.db.models import Users


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update the admin user.")
    parser.add_argument("--username", default=settings.admin_username)
    parser.add_argument("--email", default=settings.admin_email)
    parser.add_argument("--password", default=settings.admin_password)
    args = parser.parse_args()

    missing = [
        name
        for name, value in (
            ("username", args.username),
            ("email", args.email),
            ("password", args.password),
        )
        if not value
    ]
    if missing:
        print(
            f"Error: missing admin {', '.join(missing)}. "
            "Set ADMIN_USERNAME/ADMIN_EMAIL/ADMIN_PASSWORD in .env or pass --username/--email/--password.",
            file=sys.stderr,
        )
        return 1

    db = get_mongo_database()
    users = db["users"]
    password_hash = hash_password(args.password)

    existing = users.find_one({"email": args.email})
    if existing:
        users.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "username": args.username,
                    "is_superuser": True,
                    "is_active": True,
                    "password_hash": password_hash,
                }
            },
        )
        print(f"Updated existing admin user: {args.username} <{args.email}>")
    else:
        user = Users(
            id=get_next_sequence("users"),
            email=args.email,
            username=args.username,
            name=args.username,
            is_active=True,
            is_superuser=True,
            password_hash=password_hash,
        )
        users.insert_one(user.to_document())
        print(f"Created admin user: {args.username} <{args.email}>")

    close_client()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
