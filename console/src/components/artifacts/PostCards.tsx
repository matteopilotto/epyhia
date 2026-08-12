import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { SocialPosts } from "./guards";

type CopyState = "idle" | "copied" | "failed";

/**
 * Copy-to-clipboard with visible success AND failure feedback — denied clipboard access
 * must never read as silent success (US1 edge case). Shared by the post cards and the
 * email preview.
 */
export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [state, setState] = useState<CopyState>("idle");
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = async () => {
    window.clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    timer.current = window.setTimeout(() => setState("idle"), 2000);
  };

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={copy}
      className={state === "failed" ? "border-red-800 text-red-300" : undefined}
    >
      {state === "idle" ? label : state === "copied" ? "Copied" : "Copy failed"}
    </Button>
  );
}

/** The `posts` artifact as one card per post: angle, body, character count, copy control. */
export function PostCards({ posts }: { posts: SocialPosts }) {
  return (
    <ul className="space-y-3">
      {posts.posts.map((post, index) => (
        <li key={index} className="rounded-md border border-line bg-surface-raised p-3">
          <div className="flex items-baseline gap-2">
            <span className="text-xs font-medium text-ink-muted">{post.angle}</span>
            <span className="ml-auto text-xs text-ink-muted">{post.body.length} chars</span>
          </div>
          <p className="mt-2 text-sm whitespace-pre-wrap">{post.body}</p>
          <div className="mt-2">
            <CopyButton text={post.body} />
          </div>
        </li>
      ))}
    </ul>
  );
}
