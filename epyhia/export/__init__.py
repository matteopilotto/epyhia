"""Assembly of the deliverable pack from stored artifact rows.

Named `export` rather than `pack` because `epyhia/queue/handlers/pack.py` already owns that
word: that module *generates* the marketing pack with the crew, this one hands the finished
records to an operator. Everything here is a pure function over rows — no session, no
credentials, no network — which is what makes the archive's self-description testable in
full (research R4).
"""
