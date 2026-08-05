/**
 * The props contract, mirrored from specs/001-epyhia-agency/contracts/video-props.schema.json.
 *
 * The `content` / `style` split is load-bearing rather than tidy: the grounding check reads
 * every leaf under `content` and nothing under `style`, so there must be no field in `style`
 * through which a fact could reach the screen (research.md R5, FR-026).
 */

export type OnScreenValue = {
  label: string;
  amount_minor: number;
  currency: string;
};

export type Scene = {
  kind: string;
  lines: string[];
  values?: OnScreenValue[];
};

export type VideoContent = {
  headline: string;
  subhead?: string;
  scenes: Scene[];
  cta?: string;
};

export type VideoStyle = {
  palette: { bg: string; fg: string; accent: string; muted: string };
  type: { display: string; body: string };
  motion_intensity: "low" | "medium" | "high";
  density?: "sparse" | "balanced" | "dense";
};

export type VideoProps = {
  archetype_id: string;
  content: VideoContent;
  style: VideoStyle;
};

export const FPS = 30;

export const TITLE_FRAMES = 90;
export const SCENE_FRAMES = 120;
export const CTA_FRAMES = 90;

/** Duration follows the props, so a five-scene pack is not truncated into a three-scene film. */
export const totalFrames = (content: VideoContent): number =>
  TITLE_FRAMES + content.scenes.length * SCENE_FRAMES + (content.cta ? CTA_FRAMES : 0);

/**
 * Formatted with a fixed locale so two renders of the same props are byte-identical. The
 * currency and the amount both come from the props — never from here — and the exponent is
 * read from the currency itself, so a zero-decimal currency is not silently divided by 100.
 */
export const formatValue = (value: OnScreenValue): string => {
  const format = new Intl.NumberFormat("en", {
    style: "currency",
    currency: value.currency,
  });
  const digits = format.resolvedOptions().maximumFractionDigits ?? 2;
  return format.format(value.amount_minor / 10 ** digits);
};

/**
 * Preview-only placeholders for `remotion studio`. Every real render is driven by the run's
 * own `video_props` artifact through `--props`, so nothing here may ever be client-shaped —
 * and nothing here carries a numeral, which is the shape a fixture leak would take.
 */
export const PLACEHOLDER_CONTENT: VideoContent = {
  headline: "Headline",
  subhead: "Subhead",
  scenes: [
    { kind: "statement", lines: ["First line", "Second line"] },
    { kind: "detail", lines: ["Detail line"] },
  ],
  cta: "Call to action",
};

export const PLACEHOLDER_STYLE: VideoStyle = {
  palette: { bg: "#111111", fg: "#f5f5f5", accent: "#888888", muted: "#555555" },
  type: { display: "serif", body: "sans-serif" },
  motion_intensity: "medium",
  density: "balanced",
};
