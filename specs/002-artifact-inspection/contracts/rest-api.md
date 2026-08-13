# Contract: HTTP surface additions

Extends feature 001's [rest-api.md](../../001-epyhia-agency/contracts/rest-api.md); its
rules hold unchanged here — every route below is an operator route served under `/api`,
Auth0 Bearer through the same validator, no second path in (FR-057), one origin, no CORS.
Headings are written bare because the `/api` prefix belongs to the mounting.

Both routes are **reads**. Neither creates, modifies, or deletes anything (FR-015).

---

## `GET /artifacts/{artifact_id}/content`

The stored bytes of one artifact, verbatim — the delivery path for video playback, site
preview, and single-artifact download (FR-005, FR-004, FR-006), and the reason media
retrieval carries the same auth as everything else (FR-007): the console fetches with its
Bearer header and feeds the response to media elements as a blob URL, so no token ever
rides a query string.

**Response** `200`:

- Body: `artifact.bytes`, unmodified. Byte-identity with the stored row is the contract —
  `sha256(body) == artifact.sha256`, always.
- `Content-Type`: the artifact's stored `content_type` (`video/mp4`, `text/html`,
  `application/json`, …).
- `Content-Disposition`: `attachment; filename="<artifact.path>"` — the "sensible
  filename" of FR-006. (The console overrides disposition semantics by constructing its
  own blob URLs; the header serves direct downloads.)

**Errors**: `404` `{"error": "not_found", "detail": "artifact not found"}` in the standard
error shape. Auth failures as everywhere: `401`.

The existing `GET /artifacts/{artifact_id}` JSON route is unchanged; its inline `content`
field (text types only) remains what the raw view displays.

---

## `GET /runs/{run_id}/pack`

The run's deliverable pack, assembled per request from the `artifacts` table — latest
revision per kind — and never stored (FR-008). Layout and inclusion rules are specified in
[data-model.md](../data-model.md) § "Transient archive structures"; the manifest schema is
[pack-manifest.schema.json](./pack-manifest.schema.json).

**Response** `200`:

- Body: a zip archive. Opens with standard tools on a machine with no access to the system
  (SC-003).
- `Content-Type`: `application/zip`.
- `Content-Disposition`: `attachment; filename="pack-{run_id}.zip"`. The filename derives
  from the run id alone — a client name in it would be client data in code
  (Constitution I).

**Contract points**:

- Every clean latest-revision artifact appears under `deliverables/` under its
  `artifact.path`; every flagged one under `flagged/` with a sibling
  `<stem>.violations.json` carrying its itemised violations (FR-010).
- `manifest.json` lists every other file in the archive; `record` entries carry the stored
  `sha256`, and unzipping-then-hashing reproduces it (FR-009, SC-004).
- Structured text deliverables (`copy`, `posts`, `email`, `video_props`) are accompanied by
  a Markdown companion rendered mechanically from the record; a record whose content fails
  to parse ships without one (FR-011).
- A run still in progress returns what exists so far; a run with no artifacts returns a
  valid archive whose manifest lists zero files (edge cases; acceptance scenario 5 of US3).

**Errors**: `404` for an unknown run, standard error shape; `401` as everywhere.
