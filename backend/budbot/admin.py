"""Local command-line administration for one-time first-owner setup."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import re
import sys
from uuid import UUID

from sqlalchemy import select

from budbot.core.config import get_settings
from budbot.core.security import hash_password, validate_new_password
from budbot.database.session import Database
from budbot.models.business import Business
from budbot.services.owner_setup_service import OwnerSetupError, OwnerSetupService

_EMAIL_SHAPE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m budbot.admin",
        description="Local BudBot administration setup. Passwords are prompted securely.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser(
        "setup-owner",
        help="Initialize the first owner once, attaching exactly one business.",
    )
    setup.add_argument("--email", help="Owner email (otherwise prompted)")
    setup.add_argument("--display-name", help="Owner display name (otherwise prompted)")
    setup.add_argument(
        "--business-id",
        help="Explicit active business UUID; required when selecting an existing tenant non-interactively",
    )
    setup.add_argument(
        "--business-name",
        help="Name for a new first business when the database has no active businesses",
    )
    return parser


async def _active_businesses() -> list[Business]:
    database = Database(get_settings())
    try:
        async with database.session_factory() as session:
            return list(
                (
                    await session.scalars(
                        select(Business)
                        .where(Business.active.is_(True))
                        .order_by(Business.display_name, Business.id)
                    )
                ).all()
            )
    finally:
        await database.dispose()


def _choose_business(
    businesses: list[Business], requested_id: str | None
) -> UUID | None:
    if requested_id:
        for business in businesses:
            if str(business.id) == requested_id:
                return business.id
        raise ValueError("--business-id must identify an active business.")
    if not businesses:
        return None

    print("Choose the one existing business that will receive the first owner:")
    for index, business in enumerate(businesses, 1):
        print(f"  {index}. {business.display_name} ({business.id})")
    while True:
        selected = input(f"Business number [1-{len(businesses)}]: ").strip()
        if selected.isdigit() and 1 <= int(selected) <= len(businesses):
            return businesses[int(selected) - 1].id
        print("Enter one of the listed business numbers.")


async def _setup_owner(args: argparse.Namespace) -> int:
    settings = get_settings()
    email = (args.email or input("Owner email: ")).strip().casefold()
    if not _EMAIL_SHAPE.fullmatch(email) or len(email) > 320:
        print("Enter a valid owner email address.", file=sys.stderr)
        return 2
    display_name = (args.display_name or input("Owner display name: ")).strip()
    if not display_name or len(display_name) > 200:
        print("Owner display name must contain 1 to 200 characters.", file=sys.stderr)
        return 2

    while True:
        password = getpass.getpass("New owner password: ")
        confirmation = getpass.getpass("Confirm owner password: ")
        if password != confirmation:
            print("Passwords did not match. No account was created.", file=sys.stderr)
            continue
        try:
            validate_new_password(password)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            continue
        break

    try:
        businesses = await _active_businesses()
        business_id = _choose_business(businesses, args.business_id)
        business_name = None
        if business_id is None:
            business_name = (args.business_name or input(
                "No active businesses exist. First business name: "
            )).strip()
            if not business_name or len(business_name) > 200:
                print("Business name must contain 1 to 200 characters.", file=sys.stderr)
                return 2
        password_hash = hash_password(password)
        password = ""
        confirmation = ""

        database = Database(settings)
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    result = await OwnerSetupService(session).initialize_first_owner(
                        email=email,
                        display_name=display_name,
                        password_hash=password_hash,
                        business_id=business_id,
                        new_business_name=business_name,
                    )
        finally:
            await database.dispose()
    except OwnerSetupError as exc:
        print(exc.detail, file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Owner setup was cancelled; no setup changes were kept.", file=sys.stderr)
        return 130
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        # Database/driver exceptions can contain URLs and credentials. Keep the
        # terminal response actionable without echoing exception or SQL details.
        print(
            "Owner setup could not complete. Confirm Alembic upgrade to head has "
            "finished and retry; no password or database secret was printed.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Owner setup completed for business {result.business_name} "
        f"({result.business_id}). The password was not displayed or stored in plaintext."
    )
    return 0


def main() -> None:
    args = _parser().parse_args()
    if args.command == "setup-owner":
        try:
            result = asyncio.run(_setup_owner(args))
        except (EOFError, KeyboardInterrupt):
            print("Owner setup was cancelled; no setup changes were kept.", file=sys.stderr)
            result = 130
        raise SystemExit(result)


if __name__ == "__main__":
    main()
