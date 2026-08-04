import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        default: "border-line bg-surface-raised text-ink",
        muted: "border-line bg-transparent text-ink-muted",
        good: "border-emerald-700 bg-emerald-950 text-emerald-300",
        warn: "border-amber-700 bg-amber-950 text-amber-300",
        bad: "border-red-800 bg-red-950 text-red-300",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export function Badge({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { badgeVariants };
