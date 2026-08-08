import { AbsoluteFill, Sequence, interpolate, useCurrentFrame } from "remotion";

import { motionOf } from "../motion";
import {
  CTA_FRAMES,
  SCENE_FRAMES,
  TITLE_FRAMES,
  type Scene,
  type VideoProps,
  formatValue,
} from "../props";
import { useStage } from "../stage";

/** Precise, ruled, numeric — type and rules do the work, and nothing moves that need not. */

const Rule: React.FC<{ colour: string; progress: number; thickness: number }> = ({
  colour,
  progress,
  thickness,
}) => (
  <div
    style={{
      height: thickness,
      backgroundColor: colour,
      width: `${progress * 100}%`,
    }}
  />
);

const SpecRow: React.FC<{ scene: Scene; index: number; props: VideoProps }> = ({
  scene,
  index,
  props,
}) => {
  const frame = useCurrentFrame();
  const { palette, type } = props.style;
  const { u, vertical, density } = useStage(props.style);
  const motion = motionOf(props.style);
  const appear = interpolate(frame, [0, motion.ramp], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <div style={{ opacity: appear, display: "grid", gap: u * density.gap }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontFamily: type.body,
          fontSize: u * 1.6,
          letterSpacing: u * 0.15,
          textTransform: "uppercase",
          color: palette.muted,
        }}
      >
        <span>{scene.kind}</span>
        <span>{String(index + 1).padStart(2, "0")}</span>
      </div>
      <Rule colour={palette.accent} progress={appear} thickness={Math.max(2, u * 0.12)} />
      <div style={{ display: "grid", gap: u * 0.6 * density.gap }}>
        {scene.lines.map((line, i) => (
          <div
            key={i}
            style={{
              fontFamily: type.display,
              fontSize: u * (vertical ? 4.6 : 4),
              lineHeight: 1.15,
            }}
          >
            {line}
          </div>
        ))}
      </div>
      {scene.values?.length ? (
        <div style={{ display: "grid", gap: u * 0.5 }}>
          {scene.values.map((value, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                borderTop: `1px solid ${palette.muted}`,
                paddingTop: u * 0.5,
                fontFamily: type.body,
                fontSize: u * 2.4,
              }}
            >
              <span style={{ color: palette.muted }}>{value.label}</span>
              <span style={{ color: palette.accent }}>{formatValue(value)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
};

export const TechnicalSpecSheet: React.FC<VideoProps> = (props) => {
  const { content, style } = props;
  const { palette, type } = style;
  const { pad, u, vertical, density } = useStage(style);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: palette.bg,
        color: palette.fg,
        padding: pad,
        fontFamily: type.body,
      }}
    >
      <Sequence durationInFrames={TITLE_FRAMES}>
        <TitleCard {...props} />
      </Sequence>

      {content.scenes.map((scene, index) => (
        <Sequence
          key={index}
          from={TITLE_FRAMES + index * SCENE_FRAMES}
          durationInFrames={SCENE_FRAMES}
        >
          <AbsoluteFill style={{ padding: pad, justifyContent: "center" }}>
            <SpecRow scene={scene} index={index} props={props} />
          </AbsoluteFill>
        </Sequence>
      ))}

      {content.cta ? (
        <Sequence
          from={TITLE_FRAMES + content.scenes.length * SCENE_FRAMES}
          durationInFrames={CTA_FRAMES}
        >
          <AbsoluteFill
            style={{ padding: pad, justifyContent: "center", alignItems: "flex-start" }}
          >
            <div
              style={{
                border: `${Math.max(2, u * 0.15)}px solid ${palette.accent}`,
                padding: `${u * density.gap}px ${u * 2}px`,
                fontFamily: type.display,
                fontSize: u * (vertical ? 5 : 4.4),
              }}
            >
              {content.cta}
            </div>
          </AbsoluteFill>
        </Sequence>
      ) : null}
    </AbsoluteFill>
  );
};

const TitleCard: React.FC<VideoProps> = ({ content, style }) => {
  const frame = useCurrentFrame();
  const { palette, type } = style;
  const { pad, u, vertical, density } = useStage(style);
  const motion = motionOf(style);
  const wipe = interpolate(frame, [motion.hold, motion.hold + motion.ramp], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ padding: pad, justifyContent: "center", gap: u * density.gap }}>
      <div
        style={{
          fontFamily: type.display,
          fontSize: u * (vertical ? 8 : 7),
          lineHeight: 1.05,
        }}
      >
        {content.headline}
      </div>
      <Rule colour={palette.accent} progress={wipe} thickness={Math.max(2, u * 0.2)} />
      {content.subhead ? (
        <div style={{ fontSize: u * 2.6, color: palette.muted }}>{content.subhead}</div>
      ) : null}
    </AbsoluteFill>
  );
};
