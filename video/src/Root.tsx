import { type CalculateMetadataFunction, Composition } from "remotion";

import { EditorialWarm } from "./archetypes/EditorialWarm";
import { KineticProduct } from "./archetypes/KineticProduct";
import { TechnicalSpecSheet } from "./archetypes/TechnicalSpecSheet";
import {
  FPS,
  PLACEHOLDER_CONTENT,
  PLACEHOLDER_STYLE,
  type VideoProps,
  totalFrames,
} from "./props";

/**
 * The archetype library, keyed by the id the Strategist selects in the brand doc. These ids
 * are EPYHIA's own — they are the same strings `prompts/_archetypes.jinja` offers, so the
 * Strategist cannot select a composition that does not exist (DESIGN.md 6.4).
 */
const ARCHETYPES: Record<string, React.FC<VideoProps>> = {
  technical_spec_sheet: TechnicalSpecSheet,
  editorial_warm: EditorialWarm,
  kinetic_product: KineticProduct,
};

/**
 * The vertical cut is the same archetype at 1080x1920 consuming the same props, not a second
 * composition with its own layout — which is what keeps the two cuts from drifting apart.
 */
export const VERTICAL_SUFFIX = "-vertical";

const ORIENTATIONS = [
  { suffix: "", width: 1920, height: 1080 },
  { suffix: VERTICAL_SUFFIX, width: 1080, height: 1920 },
];

/**
 * Remotion composition ids admit no underscores, and the archetype ids carry them — so the
 * id is derived, and the renderer derives it the same way rather than being handed it.
 */
export const compositionId = (archetypeId: string, vertical: boolean): string =>
  archetypeId.replaceAll("_", "-") + (vertical ? VERTICAL_SUFFIX : "");

const calculateMetadata: CalculateMetadataFunction<VideoProps> = ({ props }) => ({
  durationInFrames: totalFrames(props.content),
});

export const RemotionRoot: React.FC = () => (
  <>
    {Object.entries(ARCHETYPES).flatMap(([id, component]) =>
      ORIENTATIONS.map(({ suffix, width, height }) => (
        <Composition
          key={id + suffix}
          id={compositionId(id, suffix === VERTICAL_SUFFIX)}
          component={component}
          width={width}
          height={height}
          fps={FPS}
          durationInFrames={totalFrames(PLACEHOLDER_CONTENT)}
          calculateMetadata={calculateMetadata}
          // Studio-preview placeholders only. Every render passes the run's own props with
          // `--props`, so nothing client-shaped is ever compiled into this bundle.
          defaultProps={{
            archetype_id: id,
            content: PLACEHOLDER_CONTENT,
            style: PLACEHOLDER_STYLE,
          }}
        />
      )),
    )}
  </>
);
