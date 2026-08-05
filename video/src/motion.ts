import type { VideoStyle } from "./props";

/**
 * The two parameters that make one archetype look like several without any of them being a
 * different composition. Both are bounded enumerations copied from the brand doc, so the
 * range is EPYHIA's and the selection is the client's (DESIGN.md 6.4).
 */

type MotionSpec = { travel: number; ramp: number; hold: number };

const MOTION: Record<VideoStyle["motion_intensity"], MotionSpec> = {
  low: { travel: 12, ramp: 24, hold: 18 },
  medium: { travel: 40, ramp: 14, hold: 10 },
  high: { travel: 96, ramp: 7, hold: 4 },
};

type DensitySpec = { pad: number; gap: number; scale: number };

const DENSITY: Record<NonNullable<VideoStyle["density"]>, DensitySpec> = {
  sparse: { pad: 0.12, gap: 1.6, scale: 1.15 },
  balanced: { pad: 0.08, gap: 1.1, scale: 1 },
  dense: { pad: 0.05, gap: 0.7, scale: 0.85 },
};

export const motionOf = (style: VideoStyle): MotionSpec => MOTION[style.motion_intensity];

export const densityOf = (style: VideoStyle): DensitySpec =>
  DENSITY[style.density ?? "balanced"];
