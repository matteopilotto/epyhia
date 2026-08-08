import hashlib
import re
import unicodedata

from epyhia.ingest.hashing import canonical_json

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """The identifier the site's `data-product` carries and `/checkout` resolves on.

    Accents are folded rather than dropped, so a name in any locale still yields a stable,
    URL-safe identifier instead of collapsing to nothing.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return _NON_SLUG.sub("-", folded.lower()).strip("-")


def resolve_catalogue(products: list[dict]) -> list[dict]:
    """`brief.products[]` with the derived slug on each row, computed once at ingest.

    Both consumers read this row and neither reads the other's output: the site's buy button
    carries the slug, and Ops's price rows are created against the same one. Deriving it in
    two places — or deriving the button's from Ops's — would couple two tasks the pipeline
    deliberately runs in parallel, and would make the button wrong whenever the money stage
    had not landed yet (research.md R11, DESIGN.md §6.2).

    Every field is the brief's own. Nothing here converts, rounds or defaults an amount or a
    currency: `currency_display` and `currency_charge` travel side by side exactly as the
    business wrote them (FR-003, research.md R6).
    """
    return [{**product, "slug": slugify(product["name"])} for product in products]


def catalogue_hash(catalogue: list[dict]) -> str:
    """Identifies the catalogue an approval was given for. It is half of the
    `arm_charge_path` key, so editing a price and re-running asks for a fresh approval
    rather than short-circuiting on the old one (§7.2)."""
    return hashlib.sha256(
        canonical_json({"catalogue": catalogue}).encode("utf-8")
    ).hexdigest()
