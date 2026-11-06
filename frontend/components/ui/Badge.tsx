import type { ReactNode } from "react";
import { CircleCheck, CircleHelp, CircleX, TriangleAlert, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

const TONES = {
  success: { className: "border-success/40 bg-success/10 text-success", icon: CircleCheck },
  warning: { className: "border-warning/50 bg-accent/20 text-foreground", icon: TriangleAlert },
  danger: { className: "border-danger/40 bg-danger/10 text-danger", icon: CircleX },
  info: { className: "border-info/40 bg-info/10 text-info", icon: CircleHelp },
  neutral: { className: "border-border bg-muted text-muted-foreground", icon: null },
} satisfies Record<string, { className: string; icon: LucideIcon | null }>;

export type BadgeTone = keyof typeof TONES;

/** Badge de status: sempre combina cor, ícone e texto (não depende só da cor). */
export function Badge({ tone = "neutral", children, className, showIcon = true }: {
  tone?: BadgeTone; children: ReactNode; className?: string; showIcon?: boolean;
}) {
  const { className: toneClass, icon: Icon } = TONES[tone];
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold", toneClass, className)}>
      {showIcon && Icon && <Icon size={12} aria-hidden="true" />}
      {children}
    </span>
  );
}
