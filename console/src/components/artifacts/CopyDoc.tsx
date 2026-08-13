import { Marked } from "@/lib/highlight";
import type { LandingCopy } from "./guards";

/** The `copy` artifact as a sectioned document: label, headline, body prose (FR-001),
 * with any quoted violation marked on the words themselves (FR-012). */
export function CopyDoc({ copy, quotes = [] }: { copy: LandingCopy; quotes?: string[] }) {
  return (
    <div className="space-y-5">
      {copy.sections.map((section, index) => (
        <section key={index}>
          <p className="text-[10px] font-medium tracking-wider text-ink-muted uppercase">
            {section.section}
          </p>
          <h3 className="mt-1 text-sm font-semibold">
            <Marked text={section.headline} quotes={quotes} />
          </h3>
          <p className="mt-1 text-sm whitespace-pre-wrap">
            <Marked text={section.body} quotes={quotes} />
          </p>
        </section>
      ))}
    </div>
  );
}
