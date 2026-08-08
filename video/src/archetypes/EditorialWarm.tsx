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

/** Slow, human, generous — long holds and soft cross-fades, nothing cut hard. */

const useDrift = (props: VideoProps, duration: number) => {
  const frame = useCurrentFrame();
  const motion = motionOf(props.style);
  const fade = interpolate(
    frame,
    [0, motion.ramp, duration - motion.ramp, duration],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  // A long, even drift rather than an eased entrance: the movement should never resolve
  // while the frame is on screen.
  const drift = interpolate(frame, [0, duration], [motion.travel * 0.25, 0]);
  return { fade, drift };
};

const Passage: React.FC<{ scene: Scene; props: VideoProps }> = ({ scene, props }) => {
  const { palette, type } = props.style;
  const { pad, u, vertical, density } = useStage(props.style);
  const { fade, drift } = useDrift(props, SCENE_FRAMES);

  return (
    <AbsoluteFill
      style={{
        padding: pad * 1.4,
        justifyContent: "center",
        opacity: fade,
        transform: `translateY(${drift}px)`,
      }}
    >
      <div
        style={{
          fontFamily: type.body,
          fontSize: u * 1.7,
          letterSpacing: u * 0.2,
          textTransform: "uppercase",
          color: palette.muted,
          marginBottom: u * density.gap,
        }}
      >
        {scene.kind}
      </div>
      <div style={{ display: "grid", gap: u * 0.8 * density.gap }}>
        {scene.lines.map((line, i) => (
          <div
            key={i}
            style={{
              fontFamily: type.display,
              fontSize: u * (vertical ? 5 : 4.4),
              lineHeight: 1.35,
              maxWidth: vertical ? "100%" : "72%",
            }}
          >
            {line}
          </div>
        ))}
      </div>
      {scene.values?.length ? (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: u * 2 * density.gap,
            marginTop: u * 2 * density.gap,
            fontFamily: type.body,
            fontSize: u * 2.2,
          }}
        >
          {scene.values.map((value, i) => (
            <div key={i} style={{ display: "grid", gap: u * 0.3 }}>
              <span style={{ color: palette.muted, fontSize: u * 1.5 }}>{value.label}</span>
              <span style={{ color: palette.accent }}>{formatValue(value)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

export const EditorialWarm: React.FC<VideoProps> = (props) => {
  const { content, style } = props;
  const { palette, type } = style;
  const { pad } = useStage(style);

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
          <Passage scene={scene} props={props} />
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
  const { fade, drift } = useDrift(props, TITLE_FRAMES);

  return (
    <AbsoluteFill
      style={{
        padding: pad * 1.4,
        justifyContent: "center",
        opacity: fade,
        transform: `translateY(${drift}px)`,
        gap: u * density.gap,
      }}
    >
      <div
        style={{
          fontFamily: type.display,
          fontSize: u * (vertical ? 8.5 : 7.5),
          lineHeight: 1.1,
          maxWidth: vertical ? "100%" : "80%",
        }}
      >
        {content.headline}
      </div>
      {content.subhead ? (
        <div style={{ fontSize: u * 2.6, color: palette.muted, maxWidth: "60%" }}>
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
  const { fade } = useDrift(props, CTA_FRAMES);

  return (
    <AbsoluteFill
      style={{ padding: pad * 1.4, justifyContent: "center", opacity: fade }}
    >
      <div
        style={{
          fontFamily: type.display,
          fontSize: u * (vertical ? 6 : 5.2),
          color: palette.accent,
          borderBottom: `${Math.max(2, u * 0.1)}px solid ${palette.accent}`,
          paddingBottom: u,
          alignSelf: "flex-start",
        }}
      >
        {content.cta}
      </div>
    </AbsoluteFill>
  );
};
