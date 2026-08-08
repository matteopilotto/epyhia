import {
  AbsoluteFill,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

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

/** Fast cuts, strong motion, the offering front and centre. */

const useSnap = (props: VideoProps, delay: number) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const motion = motionOf(props.style);
  return spring({
    frame: frame - delay,
    fps,
    // Ramp is frames-to-settle for the other two archetypes; here it drives the spring's
    // stiffness, so the same brand-doc choice reads as speed in every archetype.
    config: { damping: 14, stiffness: 600 / motion.ramp, mass: 0.6 },
  });
};

const Panel: React.FC<{ scene: Scene; index: number; props: VideoProps }> = ({
  scene,
  index,
  props,
}) => {
  const { palette, type } = props.style;
  const { pad, u, vertical, density } = useStage(props.style);
  const motion = motionOf(props.style);
  const enter = useSnap(props, 0);
  const frame = useCurrentFrame();
  const band = interpolate(frame, [0, motion.ramp * 1.5], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ justifyContent: "center" }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          top: vertical ? "18%" : "12%",
          width: `${band * (index % 2 === 0 ? 70 : 45)}%`,
          height: vertical ? "10%" : "14%",
          backgroundColor: palette.accent,
          opacity: 0.22,
        }}
      />
      <div
        style={{
          padding: pad,
          transform: `translateX(${(1 - enter) * motion.travel}px)`,
          opacity: enter,
          display: "grid",
          gap: u * density.gap,
        }}
      >
        <div
          style={{
            fontFamily: type.body,
            fontSize: u * 1.8,
            letterSpacing: u * 0.25,
            textTransform: "uppercase",
            color: palette.accent,
          }}
        >
          {scene.kind}
        </div>
        {scene.lines.map((line, i) => (
          <div
            key={i}
            style={{
              fontFamily: type.display,
              fontSize: u * (vertical ? 6 : 5.4),
              lineHeight: 1.05,
            }}
          >
            {line}
          </div>
        ))}
        {scene.values?.length ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: u * density.gap }}>
            {scene.values.map((value, i) => (
              <div
                key={i}
                style={{
                  backgroundColor: palette.accent,
                  color: palette.bg,
                  padding: `${u * 0.5}px ${u * 1.2}px`,
                  fontFamily: type.body,
                  fontSize: u * 2.6,
                  display: "flex",
                  gap: u * 0.8,
                }}
              >
                <span style={{ opacity: 0.75 }}>{value.label}</span>
                <span>{formatValue(value)}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

export const KineticProduct: React.FC<VideoProps> = (props) => {
  const { content, style } = props;
  const { palette, type } = style;

  return (
    <AbsoluteFill
      style={{ backgroundColor: palette.bg, color: palette.fg, fontFamily: type.body }}
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
          <Panel scene={scene} index={index} props={props} />
        </Sequence>
      ))}

      {content.cta ? (
        <Sequence
          from={TITLE_FRAMES + content.scenes.length * SCENE_FRAMES}
          durationInFrames={CTA_FRAMES}
        >
          <CtaCard {...props} />
        </Sequence>
      ) : null}
    </AbsoluteFill>
  );
};

const TitleCard: React.FC<VideoProps> = (props) => {
  const { content, style } = props;
  const { palette, type } = style;
  const { pad, u, vertical, density } = useStage(style);
  const enter = useSnap(props, 0);
  const subhead = useSnap(props, 8);

  return (
    <AbsoluteFill
      style={{ padding: pad, justifyContent: "center", gap: u * density.gap }}
    >
      <div
        style={{
          fontFamily: type.display,
          fontSize: u * (vertical ? 9 : 8),
          lineHeight: 1,
          transform: `scale(${0.85 + enter * 0.15})`,
          transformOrigin: "left center",
          opacity: enter,
        }}
      >
        {content.headline}
      </div>
      {content.subhead ? (
        <div
          style={{
            fontSize: u * 2.8,
            color: palette.muted,
            opacity: subhead,
          }}
        >
          {content.subhead}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

const CtaCard: React.FC<VideoProps> = (props) => {
  const { content, style } = props;
  const { palette, type } = style;
  const { pad, u, vertical } = useStage(style);
  const enter = useSnap(props, 0);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: palette.accent,
        color: palette.bg,
        padding: pad,
        justifyContent: "center",
        opacity: enter,
      }}
    >
      <div
        style={{
          fontFamily: type.display,
          fontSize: u * (vertical ? 7 : 6),
          lineHeight: 1.05,
        }}
      >
        {content.cta}
      </div>
    </AbsoluteFill>
  );
};
