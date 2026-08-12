# Feature Specification: Artifact Inspection & Pack Download

**Feature Branch**: `002-artifact-inspection`

**Created**: 2026-08-12

**Status**: Draft

**Input**: User description: "Artifact inspection and pack download in the operator console. Today every artifact a run produces is shown identically: a metadata row plus a raw JSON/text dump, and binary artifacts (the rendered launch videos) cannot be viewed at all because the API only inlines text content. Improve this so each artifact kind is displayed according to what it is, and the whole deliverable pack can be downloaded in bulk."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Read each deliverable in its natural form (Priority: P1)

An operator opens a run's artifacts view to judge what the crew produced. Instead of a wall
of raw JSON, each text deliverable is presented as the thing it is: the landing copy reads as
a structured document (each section with its label, headline, and body prose); the social
posts appear one card per post with the post's angle, its body, a character count, and a
one-click copy-to-clipboard; the launch email appears as an inbox-style preview (subject
shown bold, preheader in muted text beside it — the way a mail client pairs them — then the
body), with subject and body each copyable in one click; the video props appear as a
scene-by-scene storyboard, each scene showing its kind, its lines, and any on-screen money
values formatted as money using the currency the artifact itself carries. On every artifact,
a raw-content toggle remains available, because grounding violations quote against the exact
stored bytes and the operator must be able to see those bytes verbatim.

**Why this priority**: This is the core of the request — the inspection surface operators use
on every run, today unusable without mentally parsing JSON. It delivers value even if nothing
else in this feature ships.

**Independent Test**: Run a brief through the system (or seed a run's artifacts), open the
artifacts view, and confirm each of the four text deliverable kinds renders in its described
form, that copy-to-clipboard puts the expected text on the clipboard, and that the raw toggle
shows the exact stored content.

**Acceptance Scenarios**:

1. **Given** a run with a `copy` artifact, **When** the operator opens it, **Then** each
   section renders with its section label, headline, and body as readable prose, not JSON.
2. **Given** a run with a `posts` artifact containing N posts, **When** the operator opens
   it, **Then** N cards render, each showing angle, body, and a character count matching the
   body's length, each with a working copy-to-clipboard control.
3. **Given** a run with an `email` artifact, **When** the operator opens it, **Then** the
   subject renders emphasized with the preheader beside it in muted style, the body below,
   and subject and body are separately copyable.
4. **Given** a run with a `video_props` artifact whose scenes carry on-screen values, **When**
   the operator opens it, **Then** scenes render in order with kind, lines, and each value
   formatted as money in the currency named by that value in the artifact.
5. **Given** any rendered artifact, **When** the operator switches to the raw view, **Then**
   the exact stored content is shown unmodified.
6. **Given** an artifact whose content does not match its kind's expected shape, **When** the
   operator opens it, **Then** the console falls back to the raw view rather than failing or
   showing a blank panel.

---

### User Story 2 - Preview the site and watch both video cuts (Priority: P2)

The operator previews the generated site inside the console — rendered in an isolated frame
that cannot act on the console's own session — with an option to open it in a new tab and a
toggle between desktop and mobile widths. The two rendered video cuts play side by side in
native players, the vertical cut framed at phone aspect, so the operator can watch both films
before approving anything that publishes them. Today these binary artifacts cannot be viewed
at all; the operator's only option is a byte count and a hash.

**Why this priority**: The videos are currently uninspectable — the sharpest gap — but the
inspection view is still usable for text deliverables without this story, so it lands second.

**Independent Test**: On a run with a `site` artifact and both video artifacts, confirm the
site renders in its isolated preview at both widths and opens in a new tab, and that both
videos play to completion in the console.

**Acceptance Scenarios**:

1. **Given** a run with a `site` artifact, **When** the operator opens it, **Then** the site
   renders visually inside an isolated preview, and a control opens the same content in a new
   tab.
2. **Given** the site preview is open, **When** the operator toggles between desktop and
   mobile widths, **Then** the preview re-renders at the selected width.
3. **Given** a run with `video` and `video_vertical` artifacts, **When** the operator opens
   them, **Then** both play with standard playback controls, side by side, the vertical cut
   presented in a phone-aspect frame.
4. **Given** any binary artifact, **When** the operator requests a download, **Then** the
   file downloads with a sensible filename and its bytes match the stored artifact.

---

### User Story 3 - Download the whole pack in one action (Priority: P3)

The operator downloads the run's entire deliverable pack as a single archive: the latest
revision of each artifact, under the artifact's own filename; a manifest describing every
included file (kind, content hash, grounding status, revision) so the archive is
self-describing and each file is checkable against the audit trail; human-usable renderings
of the structured text deliverables alongside the records themselves, so the recipient can
paste copy without parsing data files; and any flagged artifacts segregated into a clearly
marked area of the archive together with what is wrong with them — included, never silently
dropped, and never mixed in with clean deliverables.

**Why this priority**: Bulk handoff is valuable but only after the deliverables themselves
are inspectable; it builds on the same read paths the first two stories establish.

**Independent Test**: Download the pack for a completed run, open the archive with standard
tools, and verify contents, manifest accuracy, hash correctness, and flagged segregation.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** the operator downloads the pack, **Then** one archive
   arrives containing the latest revision of every artifact the run produced.
2. **Given** the downloaded archive, **When** the manifest is read, **Then** every file in
   the archive is listed with its kind, content hash, grounding status, and revision, and
   each hash matches the file it describes.
3. **Given** a run with a flagged artifact, **When** the pack is downloaded, **Then** the
   flagged artifact appears in a clearly separated area of the archive together with its
   itemised violations, and does not appear among the clean deliverables.
4. **Given** structured text deliverables in the pack, **When** the archive is opened,
   **Then** a human-readable rendering of each accompanies its record file, with identical
   substantive content.
5. **Given** a run still in progress, **When** the operator downloads the pack, **Then** the
   archive contains what exists so far and the manifest reflects exactly that.

---

### User Story 4 - See what is wrong, on the words that are wrong (Priority: P4)

When a grounding violation quotes an offending string, the rendered view marks that exact
string inline — a visible mark on the phrase itself, in the copy section, post body, email,
or storyboard line where it occurs — in addition to the existing itemised violation list.
The operator sees not just *that* something is wrong but *where*, in context.

**Why this priority**: Polish on top of Story 1's renderers; the violation list already
satisfies the "shown with what is wrong" guarantee, so this refines rather than enables.

**Independent Test**: Seed a flagged artifact whose violation quotes a string present in the
content and confirm the string is visibly marked in the rendered view; seed one whose quote
does not appear verbatim and confirm the view degrades gracefully to the list alone.

**Acceptance Scenarios**:

1. **Given** a flagged artifact whose violation quote appears verbatim in the content,
   **When** the rendered view is shown, **Then** the quoted string is visibly marked at each
   place it occurs, and the itemised violation list is still shown.
2. **Given** a violation whose quote does not appear verbatim in the rendered text, **When**
   the rendered view is shown, **Then** the violation still appears in the itemised list and
   the view renders normally otherwise.

---

### User Story 5 - Revisions grouped, latest first (Priority: P5)

Deliverables that went through review cycles exist at multiple revisions. The artifacts view
groups revisions of the same deliverable, presents the latest by default, and lets the
operator switch to earlier revisions. Today each revision renders as a separate sibling
entry, which reads as multiple artifacts.

**Why this priority**: A navigation refinement — everything above works without it; it
matters most on runs where review produced several revisions.

**Independent Test**: Seed a run with a deliverable at three revisions and confirm one group
renders showing the latest, with a control that switches the view to each earlier revision.

**Acceptance Scenarios**:

1. **Given** a deliverable with revisions 0..N, **When** the artifacts view loads, **Then**
   one entry represents the deliverable, showing revision N.
2. **Given** that entry, **When** the operator selects an earlier revision, **Then** that
   revision's content and its own grounding status and violations are shown.

---

### Edge Cases

- An artifact's stored content fails to parse as its kind's expected shape → the renderer
  falls back to the raw view for that artifact; nothing else on the page is affected.
- A run has produced no artifacts yet → the view says so, and the pack download either
  produces an archive with an empty (but accurate) manifest or is disabled with an
  explanation; it never errors opaquely.
- A `video_props` artifact is flagged → the storyboard still renders, with its violations
  shown (and marked inline where quotes match); flagged content is displayed, never hidden.
- A violation quote appears more than once in the content → every occurrence is marked.
- The latest revision of a deliverable is flagged while an earlier one is clean → the latest
  is still what shows by default; the pack includes the latest revision, segregated as
  flagged.
- A video artifact is large → playback and download must not freeze the console view while
  content transfers.
- Copy-to-clipboard is invoked in a browser context that denies clipboard access → the
  operator gets visible feedback that the copy failed, not silent success.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST present each known artifact kind in a form appropriate to its
  content — landing copy as a sectioned document, social posts as per-post cards with angle,
  body, character count, and copy-to-clipboard, launch email as an inbox-style preview with
  separately copyable subject and body, video props as an ordered storyboard of scenes —
  rather than as raw data dumps.
- **FR-002**: Every artifact MUST retain an operator-accessible raw view showing the exact
  stored content, because violations quote against the stored bytes.
- **FR-003**: Money values in the storyboard MUST be formatted using the currency named by
  the value in the artifact itself; the console MUST NOT hardcode any currency, symbol,
  locale, or other client-derived value (Constitution I).
- **FR-004**: The system MUST render the generated site visually in an isolated preview that
  cannot act on the operator's console session, with an open-in-new-tab control and a
  desktop/mobile width toggle.
- **FR-005**: The system MUST play both rendered video cuts in the console with standard
  playback controls, presented side by side with the vertical cut in a phone-aspect frame.
- **FR-006**: The system MUST allow any single artifact, including binary ones, to be
  downloaded with a sensible filename, its bytes identical to the stored artifact.
- **FR-007**: Retrieval of artifact content for display, playback, or download MUST enforce
  the same operator authentication as the rest of the console, including for content loaded
  by media elements that cannot attach the console's usual credentials.
- **FR-008**: The system MUST provide a single-action download of a run's deliverable pack as
  one archive containing the latest revision of each artifact under its artifact filename.
- **FR-009**: The pack archive MUST include a manifest listing every contained file with its
  kind, content hash, grounding status, and revision, such that each file can be verified
  against the manifest and tied back to the run's records.
- **FR-010**: Flagged artifacts MUST be included in the pack, segregated into a clearly
  marked area together with their itemised violations — never silently dropped and never
  intermixed with clean deliverables.
- **FR-011**: The pack MUST include human-readable renderings of the structured text
  deliverables alongside the record files; these renderings MUST be produced mechanically
  from the stored artifact content, introducing no content of their own.
- **FR-012**: Where a violation quotes a string that appears verbatim in the rendered
  content, the rendered view MUST visibly mark every occurrence of that string inline, in
  addition to the itemised violation list; where the quote does not appear verbatim, the
  view MUST degrade to the list alone without error.
- **FR-013**: The artifacts view MUST group revisions of the same deliverable, presenting the
  latest by default with a control to view earlier revisions, each with its own grounding
  status and violations.
- **FR-014**: A renderer that cannot interpret an artifact's content MUST fall back to the
  raw view for that artifact without affecting the rest of the page.
- **FR-015**: This feature MUST be read-only with respect to run state: no operation it adds
  may create, modify, or delete artifacts, actions, tasks, or runs, and it MUST NOT alter
  gate, grounding, or generation behavior. Flagged artifacts remain visible with what is
  wrong with them (feature 001, FR-024).

### Key Entities

- **Artifact**: An existing record — a run's generated output with a kind, filename, content
  type, content, content hash, grounding status, itemised violations, and revision number.
  This feature reads it; nothing here writes it.
- **Deliverable pack**: A downloadable archive assembled on request from a run's artifacts:
  latest revision per kind, flagged items segregated with their violations, human-readable
  companions for structured text deliverables. Assembled per request from the records; not
  itself stored.
- **Pack manifest**: The archive's self-description: one entry per contained file with kind,
  content hash, grounding status, and revision.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can review every deliverable of a completed run — copy, posts,
  email, storyboard, site, and both video cuts — entirely within the console, without
  reading raw JSON and without any tool outside the console.
- **SC-002**: Both rendered video cuts are watchable in the console from start to finish;
  today the count of viewable video artifacts is zero.
- **SC-003**: An operator can hand off a run's complete deliverable pack via a single
  download action, and the archive opens with standard tools on a machine with no access to
  the system.
- **SC-004**: Every file in a downloaded pack can be verified against the manifest, and every
  manifest entry's hash matches the run's stored records.
- **SC-005**: For any flagged artifact, an operator can identify the offending content — via
  inline marking where the quote matches, via the itemised list always — without consulting
  raw data.
- **SC-006**: A second client's run, produced from a different brief with different
  currencies, prices, and copy, renders correctly through the same views with no code
  change — every displayed value traceable to that run's own artifacts.

## Assumptions

- The set of artifact kinds is closed and known (landing copy, site, posts, email, video
  props, two video cuts); a new kind is a deliberate system change, at which point its
  renderer is added. Unknown kinds fall back to the raw view (FR-014).
- Artifacts are small enough — text deliverables and short launch videos — that whole-content
  transfer per artifact is acceptable; no streaming or partial-content delivery is required.
- Operator authentication and authorization work as they do today; this feature adds no
  roles, permissions, or sharing. The pack archive is for the authenticated operator to
  download and distribute at their own discretion.
- The structured-record files (not the human-readable companions) remain the artifacts of
  record; the companions are a courtesy derived mechanically from them.
- The existing artifact records already carry everything the manifest needs (kind, hash,
  grounding status, revision); no new persistent data is introduced by this feature.
- Revision semantics follow the existing review loop: higher revision numbers supersede
  lower ones for the same deliverable kind.
