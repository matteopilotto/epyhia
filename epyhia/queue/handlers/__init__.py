"""Importing this package registers every task handler with the worker."""

from epyhia.queue.handlers import copy, demand, plan, resume, site, video  # noqa: F401
