import { useVideoConfig } from "remotion";

import { densityOf } from "./motion";
import type { VideoStyle } from "./props";

/**
 * What every archetype needs to lay itself out at either aspect ratio. The vertical cut is
 * the same archetype at 1080x1920 consuming the same props (DESIGN.md 6.4) — so orientation
 * is read from the composition here rather than being a second set of components.
 */
export const useStage = (style: VideoStyle) => {
  const { width, height } = useVideoConfig();
  const density = densityOf(style);
  const short = Math.min(width, height);
  return {
    width,
    height,
    vertical: height > width,
    density,
    pad: short * density.pad,
    // One responsive unit, so type sized in `u` reads the same at both aspect ratios.
    u: (short / 100) * density.scale,
  };
};
