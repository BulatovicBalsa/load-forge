from __future__ import annotations

import asyncio
import sys
import threading
from typing import Callable, Optional


async def wait_for_stop_or_timeout(
    stop_event: asyncio.Event, seconds: float
) -> bool:
    """
    Wait for stop_event up to *seconds*.
    Returns True if stop was requested, False if timeout elapsed first.
    """
    if seconds <= 0:
        return stop_event.is_set()
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return stop_event.is_set()


async def drain_virtual_users(
    tasks: list[asyncio.Task],
    stop_event: asyncio.Event,
    timeout: float = 30.0,
) -> None:
    """
    Gracefully ask virtual users to stop, then cancel leftovers after timeout.
    """
    stop_event.set()
    if not tasks:
        return

    _, pending = await asyncio.wait(tasks, timeout=timeout)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def start_stdin_control_listener(
    loop: asyncio.AbstractEventLoop,
    enabled: bool,
    request_stop: Callable[[str], None],
) -> Optional[threading.Thread]:
    """
    Listen for control commands on stdin.
    Supported commands:
      - STOP
    """
    if not enabled:
        return None

    stdin = sys.stdin
    if stdin is None or getattr(stdin, "closed", False):
        return None

    try:
        # Avoid consuming interactive terminal input.
        if stdin.isatty():
            return None
    except Exception:
        return None

    def _reader() -> None:
        while True:
            try:
                line = stdin.readline()
            except Exception:
                return

            # Pipe was closed.
            if line == "":
                return

            if line.strip().upper() == "STOP":
                loop.call_soon_threadsafe(request_stop, "STDIN")
                return

    thread = threading.Thread(
        target=_reader,
        name="loadforge-stdin-control",
        daemon=True,
    )
    thread.start()
    return thread
