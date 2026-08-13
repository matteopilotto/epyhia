import { formatAmount } from "@/lib/format";
import { Marked } from "@/lib/highlight";
import type { VideoProps } from "./guards";

/**
 * The `video_props` artifact as a scene-by-scene storyboard. Every on-screen value is
 * formatted as money in the currency that value itself carries — the currency is data
 * from the artifact, never code (FR-003). Every text leaf under `content` carries inline
 * violation marks, matching what grounding checks (`extract_video_props_content`); a
 * flagged storyboard renders with its marks rather than being hidden (FR-012).
 */
export function Storyboard({
  videoProps,
  quotes = [],
}: {
  videoProps: VideoProps;
  quotes?: string[];
}) {
  const { headline, subhead, scenes, cta } = videoProps.content;
  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold">
          <Marked text={headline} quotes={quotes} />
        </h3>
        {subhead && (
          <p className="text-sm text-ink-muted">
            <Marked text={subhead} quotes={quotes} />
          </p>
        )}
      </div>
      <ol className="space-y-2">
        {scenes.map((scene, index) => (
          <li key={index} className="rounded-md border border-line bg-surface-raised p-3">
            <div className="flex items-baseline gap-2 text-xs">
              <span className="text-ink-muted">Scene {index + 1}</span>
              <span className="font-medium">{scene.kind}</span>
            </div>
            {scene.lines.map((line, lineIndex) => (
              <p key={lineIndex} className="mt-1 text-sm">
                <Marked text={line} quotes={quotes} />
              </p>
            ))}
            {scene.values?.length ? (
              <ul className="mt-2 space-y-1">
                {scene.values.map((value, valueIndex) => (
                  <li key={valueIndex} className="text-sm">
                    <span className="text-ink-muted">{value.label}: </span>
                    <span className="font-medium">
                      {formatAmount(value.amount_minor, value.currency)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ol>
      {cta && (
        <p className="text-sm font-medium">
          <Marked text={cta} quotes={quotes} />
        </p>
      )}
    </div>
  );
}
