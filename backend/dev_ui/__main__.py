"""Usage: uv run --group ui python -m dev_ui --api http://localhost:8000"""

import argparse

from dev_ui.api import MinutesApi
from dev_ui.app import build


def main() -> None:
    parser = argparse.ArgumentParser(description="DESS Minutes dev interface")
    parser.add_argument("--api", default="http://localhost:8000", help="backend base URL")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    build(MinutesApi(args.api)).launch(server_port=args.port)


if __name__ == "__main__":
    main()
