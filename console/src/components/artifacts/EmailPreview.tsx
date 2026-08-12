import { Marked } from "@/lib/highlight";
import { CopyButton } from "./PostCards";
import type { LaunchEmail } from "./guards";

/**
 * The `email` artifact as an inbox-style preview: bold subject with the preheader in
 * muted text beside it — the pairing a mail client shows — body below. Subject and body
 * are each copyable in one click (FR-001); all three fields carry inline violation marks
 * (FR-012).
 */
export function EmailPreview({ email, quotes = [] }: { email: LaunchEmail; quotes?: string[] }) {
  return (
    <div className="rounded-md border border-line bg-surface-raised p-3">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-sm font-semibold">
          <Marked text={email.subject} quotes={quotes} />
        </span>
        <span className="text-sm text-ink-muted">
          <Marked text={email.preheader} quotes={quotes} />
        </span>
      </div>
      <p className="mt-3 border-t border-line pt-3 text-sm whitespace-pre-wrap">
        <Marked text={email.body} quotes={quotes} />
      </p>
      <div className="mt-3 flex gap-2">
        <CopyButton text={email.subject} label="Copy subject" />
        <CopyButton text={email.body} label="Copy body" />
      </div>
    </div>
  );
}
