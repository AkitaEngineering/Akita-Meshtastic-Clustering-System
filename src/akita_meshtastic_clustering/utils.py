# Copyright (c) 2025 Akita Engineering <https://www.akitaengineering.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import time
import uuid
from typing import Optional

# Basic Logging Setup
def setup_logging(level: int = logging.INFO):
    """Configures basic stream logging with timestamps and module info."""
    logging.basicConfig(
        level=level,
        format='%(asctime)s.%(msecs)03d - %(levelname)-7s - %(name)-22s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # Silence overly verbose libraries - adjust levels as needed
    logging.getLogger("meshtastic").setLevel(logging.WARNING)
    logging.getLogger("pubsub").setLevel(logging.WARNING)


def generate_message_id() -> str:
    """Generates a unique message identifier (UUID4)."""
    return str(uuid.uuid4())

class Timer:
    """A simple monotonic timer."""
    def __init__(self, duration_seconds: float):
        """
        Initializes the timer.
        Args:
            duration_seconds: The duration for the timer in seconds.
        Raises:
            ValueError: If duration is negative.
        """
        if duration_seconds < 0:
            raise ValueError("Timer duration cannot be negative")
        self.duration = duration_seconds
        self.start_time: Optional[float] = None

    def start(self):
        """Starts (or restarts) the timer."""
        self.start_time = time.monotonic()

    def stop(self):
        """Stops the timer. It can be restarted."""
        self.start_time = None

    def reset(self):
        """Resets the timer to its full duration by restarting it."""
        self.start()

    def expired(self) -> bool:
        """Checks if the timer has run for its full duration since starting."""
        if self.start_time is None or self.duration <= 0: # Timer must have a positive duration
            return False
        return (time.monotonic() - self.start_time) >= self.duration

    def remaining(self) -> float:
        """Gets the remaining time in seconds. Returns duration if not started."""
        if self.start_time is None:
            return self.duration
        elapsed = time.monotonic() - self.start_time
        return max(0.0, self.duration - elapsed)

    def elapsed(self) -> float:
        """Gets the elapsed time in seconds since started. Returns 0 if not started."""
        if self.start_time is None:
            return 0.0
        return time.monotonic() - self.start_time

    def is_running(self) -> bool:
        """Checks if the timer is currently running (has been started and not stopped)."""
        return self.start_time is not None
