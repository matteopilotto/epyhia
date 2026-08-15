"""Importing this package registers every task handler with the worker."""

from epyhia.queue.handlers import (  # noqa: F401
    copy,
    demand,
    money,
    outreach,
    plan,
    resume,
    site,
    video,
)
