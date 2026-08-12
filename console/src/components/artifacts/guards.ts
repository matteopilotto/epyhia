/**
 * Hand-rolled shape guards over JSON.parse for the four structured deliverable kinds —
 * no schema library, deliberately (research R6). Each guard returns the typed value or
 * null, never throws; null means the artifact renders raw (FR-014). The shapes mirror
 * what the Marketer emits (`epyhia/agents/marketer.py`), video_props in its assembled
 * form.
 */

export type CopySection = { section: string; headline: string; body: string };
export type LandingCopy = { sections: CopySection[] };

export type SocialPost = { angle: string; body: string };
export type SocialPosts = { posts: SocialPost[] };

export type LaunchEmail = { subject: string; preheader: string; body: string };

export type OnScreenValue = { label: string; amount_minor: number; currency: string };
export type Scene = { kind: string; lines: string[]; values?: OnScreenValue[] };
export type VideoContent = {
  headline: string;
  subhead?: string;
  scenes: Scene[];
  cta?: string;
};
export type VideoProps = { content: VideoContent };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function tryParse(content: string): unknown {
  try {
    return JSON.parse(content);
  } catch {
    return null;
  }
}

function isCopySection(value: unknown): value is CopySection {
  return (
    isRecord(value) && isString(value.section) && isString(value.headline) && isString(value.body)
  );
}

export function parseCopy(content: string): LandingCopy | null {
  const data = tryParse(content);
  if (!isRecord(data)) return null;
  const sections = data.sections;
  if (!Array.isArray(sections) || sections.length === 0 || !sections.every(isCopySection)) {
    return null;
  }
  return { sections };
}

function isSocialPost(value: unknown): value is SocialPost {
  return isRecord(value) && isString(value.angle) && isString(value.body);
}

export function parsePosts(content: string): SocialPosts | null {
  const data = tryParse(content);
  if (!isRecord(data)) return null;
  const posts = data.posts;
  if (!Array.isArray(posts) || posts.length === 0 || !posts.every(isSocialPost)) return null;
  return { posts };
}

export function parseEmail(content: string): LaunchEmail | null {
  const data = tryParse(content);
  if (!isRecord(data) || !isString(data.subject) || !isString(data.preheader) || !isString(data.body)) {
    return null;
  }
  return { subject: data.subject, preheader: data.preheader, body: data.body };
}

function isOnScreenValue(value: unknown): value is OnScreenValue {
  return (
    isRecord(value) &&
    isString(value.label) &&
    typeof value.amount_minor === "number" &&
    isString(value.currency)
  );
}

function isScene(value: unknown): value is Scene {
  if (!isRecord(value) || !isString(value.kind)) return false;
  if (!Array.isArray(value.lines) || !value.lines.every(isString)) return false;
  if (value.values !== undefined) {
    if (!Array.isArray(value.values) || !value.values.every(isOnScreenValue)) return false;
  }
  return true;
}

export function parseVideoProps(content: string): VideoProps | null {
  const data = tryParse(content);
  if (!isRecord(data) || !isRecord(data.content)) return null;
  const inner = data.content;
  if (!isString(inner.headline)) return null;
  if (inner.subhead !== undefined && !isString(inner.subhead)) return null;
  if (inner.cta !== undefined && !isString(inner.cta)) return null;
  const scenes = inner.scenes;
  if (!Array.isArray(scenes) || scenes.length === 0 || !scenes.every(isScene)) return null;
  return { content: { headline: inner.headline, subhead: inner.subhead, scenes, cta: inner.cta } };
}
