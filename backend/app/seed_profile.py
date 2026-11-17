"""Load a minutes profile file into the database.

Usage: uv run python -m app.seed_profile [PATH] --confirm

PATH defaults to the bundled DESS Standard profile (app/minutes/profiles/dess_standard.md).
A new version is only created when the file has changed, so it is safe to run on every deploy.
"""

import argparse
from pathlib import Path

from pydantic import ValidationError

from app.db import SessionLocal
from app.minutes.profile_content import DEFAULT_PROFILE_PATH, load_profile_file
from app.services.profile import seed_profile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "path", type=Path, nargs="?", default=DEFAULT_PROFILE_PATH, help="profile .md or .json"
    )
    parser.add_argument(
        "--slug", default="dess-standard", help="profile slug (default: %(default)s)"
    )
    parser.add_argument("--confirm", action="store_true", help="mark the version confirmed")
    parser.add_argument("--by", default="seed", help="recorded as created_by / confirmed_by")
    args = parser.parse_args(argv)

    try:
        content = load_profile_file(args.path)
    except (OSError, ValueError, ValidationError) as e:
        print(f"invalid profile file {args.path}: {e}")
        return 1

    with SessionLocal() as db:
        result = seed_profile(db, content, slug=args.slug, confirm_version=args.confirm, by=args.by)
        v = result.version
        action = "created" if result.created else "unchanged, kept"
        sha = v.content_sha256[:12]
        print(f"{args.slug}: {action} version {v.version_number} ({v.status}) sha={sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
