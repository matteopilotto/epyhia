from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Every model module must be imported somewhere for SQLAlchemy to resolve cross-table
# foreign keys given by string reference (e.g. `runs.brand_doc_id` -> `brand_docs.id`),
# regardless of which individual model a caller imports directly.
from epyhia.models import actions as _actions  # noqa: E402,F401
from epyhia.models import agent_cache as _agent_cache  # noqa: E402,F401
from epyhia.models import agent_calls as _agent_calls  # noqa: E402,F401
from epyhia.models import artifacts as _artifacts  # noqa: E402,F401
from epyhia.models import brand_docs as _brand_docs  # noqa: E402,F401
from epyhia.models import briefs as _briefs  # noqa: E402,F401
from epyhia.models import orders as _orders  # noqa: E402,F401
from epyhia.models import runs as _runs  # noqa: E402,F401
from epyhia.models import sink_posts as _sink_posts  # noqa: E402,F401
from epyhia.models import tasks as _tasks  # noqa: E402,F401
