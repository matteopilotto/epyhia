import type { LandingCopy } from "./guards";

/** The `copy` artifact as a sectioned document: label, headline, body prose (FR-001). */
export function CopyDoc({ copy }: { copy: LandingCopy }) {
  return (
    <div className="space-y-5">
      {copy.sections.map((section, index) => (
        <section key={index}>
          <p className="text-[10px] font-medium tracking-wider text-ink-muted uppercase">
            {section.section}
          </p>
          <h3 className="mt-1 text-sm font-semibold">{section.headline}</h3>
          <p className="mt-1 text-sm whitespace-pre-wrap">{section.body}</p>
        </section>
      ))}
    </div>
  );
}
