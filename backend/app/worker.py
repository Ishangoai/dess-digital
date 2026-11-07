"""Background worker: processes documents and generates minutes."""

import logging
import time

log = logging.getLogger("worker")


def run_once() -> None:
    # TODO: pick up pending jobs, read files, call the LLM, write results.
    pass


def main(poll_seconds: float = 5.0) -> None:
    logging.basicConfig(level=logging.INFO)
    log.info("worker started")
    while True:
        run_once()
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
