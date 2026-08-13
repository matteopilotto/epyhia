import { Fragment, createElement, type ReactNode } from "react";

/**
 * Inline marking of grounding violations on the words they quote (FR-012). Violations
 * quote against the stored bytes, so the match is an exact substring — never fuzzy or
 * normalised, which would mark text the check never flagged (research R8). A quote with
 * no verbatim occurrence marks nothing and raises nothing; the itemised list is the
 * fallback and is rendered in all cases.
 */

export type Segment = { text: string; marked: boolean };

/** Splits `text` on every exact occurrence of every quote. Overlaps resolve to the longest
 * quote matching at a position, so one span never swallows part of another's match. */
export function splitOnQuotes(text: string, quotes: string[]): Segment[] {
  const needles = [...new Set(quotes.filter((quote) => quote.length > 0))].sort(
    (a, b) => b.length - a.length,
  );
  if (needles.length === 0) return [{ text, marked: false }];

  const segments: Segment[] = [];
  let plain = "";
  let index = 0;

  while (index < text.length) {
    const hit = needles.find((needle) => text.startsWith(needle, index));
    if (hit === undefined) {
      plain += text[index];
      index += 1;
      continue;
    }
    if (plain) {
      segments.push({ text: plain, marked: false });
      plain = "";
    }
    segments.push({ text: hit, marked: true });
    index += hit.length;
  }
  if (plain) segments.push({ text: plain, marked: false });

  return segments;
}

/** `text` with every quoted occurrence wrapped in a visible mark. */
export function Marked({ text, quotes }: { text: string; quotes: string[] }): ReactNode {
  const segments = splitOnQuotes(text, quotes);
  if (!segments.some((segment) => segment.marked)) return text;

  return createElement(
    Fragment,
    null,
    ...segments.map((segment, index) =>
      segment.marked
        ? createElement(
            "mark",
            { key: index, className: "rounded-sm bg-red-900 px-0.5 text-red-100" },
            segment.text,
          )
        : createElement(Fragment, { key: index }, segment.text),
    ),
  );
}
