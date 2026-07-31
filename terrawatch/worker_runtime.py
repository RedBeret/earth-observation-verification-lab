"""Signal-aware worker container runtime."""

from __future__ import annotations

import argparse
import asyncio
import signal

import structlog

from terrawatch.logging import configure_logging
from terrawatch.messaging import ensure_streams


async def run_worker(service_name: str) -> None:
    configure_logging()
    logger = structlog.get_logger(service=service_name)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop.set)
    await ensure_streams()
    logger.info("worker_ready")
    await stop.wait()
    logger.info("worker_stopped", unfinished_work_acknowledged=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("service_name", choices=("imagery-worker", "correlation-worker"))
    args = parser.parse_args()
    asyncio.run(run_worker(args.service_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
