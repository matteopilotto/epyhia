import logfire

_configured = False


def configure_tracing() -> None:
    """Configure tracing for the calling process, once.

    Both Fly processes run this image, and each needs its own call: `create_app()` for
    `web`, `run_worker()` for `worker`. The crew runs entirely in the latter, so a
    configuration that only ever ran in the API left every agent untraced.

    Not at import time in either module. `configure()` starts an exporter thread, and the
    test suite, `alembic` and every `python -c` against this package would otherwise pay
    for one.

    `send_to_logfire="if-token-present"` is what keeps CI credential-free: no token, no
    exporter, no network.
    """
    global _configured
    if _configured:
        return

    logfire.configure(send_to_logfire="if-token-present")
    # A global patch, so no `Agent(...)` construction needs an `instrument=` argument.
    #
    # `include_content` stays on deliberately (its default), but not for the reason first
    # written here. That reason was that a `ThinkingPart` carries its `content` into the span
    # only when it is set, and the Strategist's drafted directions live in extended thinking.
    # Both halves are wrong: Opus 5 never returns its raw chain of thought, so the part is
    # empty whatever this is set to, and nothing in FR-019 or the Strategist's prompt puts
    # the drafts in thinking — the model writes them into its response text, which reaches
    # `gen_ai.output.messages` because of this setting (evidence.md, "The drafts were never
    # in thinking"). So the setting earns its place; the justification had to change.
    #
    # The cost of that choice, stated rather than assumed: every client-derived byte the crew
    # handles — brief, brand doc, copy, the whole generated page — is sent to Logfire.
    #
    # `include_binary_content` is off, and its default is on: an agent that passes a
    # full-page screenshot would otherwise upload the render on every call, when what a
    # trace is for is the finding it drew from it. The pixels are reproducible from the
    # stored artifact.
    logfire.instrument_pydantic_ai(include_binary_content=False)
    _configured = True
