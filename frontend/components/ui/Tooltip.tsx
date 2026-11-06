import { useId, type ReactElement, type ReactNode } from "react";
import { cloneElement } from "react";
import { cn } from "@/lib/utils";

/** Tooltip acessível (hover e foco) para ações representadas só por ícone. */
export function Tooltip({ content, children, side = "bottom", hidden = false }: {
  content: ReactNode; children: ReactElement<{ "aria-describedby"?: string }>; side?: "top" | "bottom"; hidden?: boolean;
}) {
  const id = useId();
  return (
    <span className="group/tooltip relative inline-flex">
      {cloneElement(children, { "aria-describedby": id })}
      <span id={id} role="tooltip"
        className={cn(
          "pointer-events-none absolute left-1/2 z-[120] -translate-x-1/2 whitespace-nowrap rounded-md border border-border bg-surface-elevated px-2 py-1 text-[11px] font-medium text-foreground opacity-0 shadow-card transition duration-150",
          "group-hover/tooltip:opacity-100 group-has-[:focus-visible]/tooltip:opacity-100",
          hidden && "hidden",
          side === "bottom" ? "top-full mt-2" : "bottom-full mb-2",
        )}>
        {content}
      </span>
    </span>
  );
}
