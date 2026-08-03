"""Importing this package registers every task handler with the worker."""

from epyhia.queue.handlers import copy, plan, resume, site  # noqa: F401
