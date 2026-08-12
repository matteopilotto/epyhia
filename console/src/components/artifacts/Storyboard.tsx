import { formatAmount } from "@/lib/format";
import type { VideoProps } from "./guards";

/**
 * The `video_props` artifact as a scene-by-scene storyboard. Every on-screen value is
 * formatted as money in the currency that value itself carries — the currency is data
 * from the artifact, never code (FR-003).
 */
export function Storyboard({ videoProps }: { videoProps: VideoProps }) {
  const { headline, subhead, scenes, cta } = videoProps.content;
  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold">{headline}</h3>
        {subhead && <p className="text-sm text-ink-muted">{subhead}</p>}
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
                {line}
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
      {cta && <p className="text-sm font-medium">{cta}</p>}
    </div>
  );
}
