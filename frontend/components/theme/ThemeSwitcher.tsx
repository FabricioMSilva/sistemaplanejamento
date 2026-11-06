import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Check, Palette } from "lucide-react";
import { THEMES, type ThemeId } from "@/config/themes";
import { useTheme } from "@/providers/ThemeProvider";
import { Tooltip } from "@/components/ui/Tooltip";
import { cn } from "@/lib/utils";

function ThemePreview({ preview }: { preview: (typeof THEMES)[number]["preview"] }) {
  return (
    <span aria-hidden="true" className="flex h-11 w-16 shrink-0 flex-col overflow-hidden rounded-md border border-border"
      style={{ background: preview.background }}>
      <span className="h-2.5 w-full" style={{ background: preview.header }} />
      <span className="m-1 flex flex-1 gap-1">
        <span className="flex-1 rounded-sm" style={{ background: preview.card }} />
        <span className="flex-1 rounded-sm" style={{ background: preview.card }}>
          <span className="mx-1 mt-1 block h-1 rounded-full" style={{ background: preview.accent }} />
        </span>
      </span>
    </span>
  );
}

export default function ThemeSwitcher() {
  const { theme, setTheme, reducedMotion, setReducedMotion } = useTheme();
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const items = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    if (!open) return;
    items.current[THEMES.findIndex((item) => item.id === theme)]?.focus();
    const close = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open, theme]);

  function onMenuKey(event: KeyboardEvent<HTMLDivElement>) {
    const focusable = items.current.filter(Boolean) as HTMLButtonElement[];
    const index = focusable.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); }
    if (event.key === "ArrowDown") { event.preventDefault(); focusable[(index + 1) % focusable.length]?.focus(); }
    if (event.key === "ArrowUp") { event.preventDefault(); focusable[(index - 1 + focusable.length) % focusable.length]?.focus(); }
  }

  function choose(id: ThemeId) {
    setTheme(id);
    setOpen(false);
    trigger.current?.focus();
  }

  return (
    <div ref={container} className="relative">
      <Tooltip content="Aparência" hidden={open}>
        <button ref={trigger} type="button" aria-label="Aparência" aria-haspopup="menu" aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="inline-flex h-9 items-center gap-2 rounded-lg border border-header-foreground/25 px-2.5 text-sm font-medium text-header-foreground transition hover:bg-header-foreground/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          <Palette size={17} aria-hidden="true" />
          <span className="hidden lg:inline">Aparência</span>
        </button>
      </Tooltip>
      <AnimatePresence>
        {open && (
          <motion.div role="menu" aria-label="Tema da aplicação" onKeyDown={onMenuKey}
            initial={{ opacity: 0, y: -6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }} transition={{ duration: 0.16, ease: "easeOut" }}
            className="absolute right-0 top-full z-[110] mt-2 w-[min(92vw,22rem)] origin-top-right rounded-xl border border-border bg-surface-elevated p-2 text-foreground shadow-card">
            <p className="px-2 pb-2 pt-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Aparência</p>
            {THEMES.map((item, index) => {
              const active = item.id === theme;
              return (
                <button key={item.id} ref={(element) => { items.current[index] = element; }} type="button"
                  role="menuitemradio" aria-checked={active} onClick={() => choose(item.id)}
                  className={cn("flex w-full items-center gap-3 rounded-lg border p-2 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active ? "border-primary/50 bg-primary/10" : "border-transparent hover:bg-muted")}>
                  <ThemePreview preview={item.preview} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold">{item.name}</span>
                    <span className="block text-xs text-muted-foreground">{item.description}</span>
                  </span>
                  {active && <Check size={16} className="shrink-0 text-primary" aria-label="Selecionado" />}
                </button>
              );
            })}
            <label className="mt-2 flex cursor-pointer items-center justify-between gap-3 border-t border-border px-2 pb-1 pt-3 text-xs text-muted-foreground">
              Reduzir animações
              <input ref={(element) => { items.current[THEMES.length] = element as unknown as HTMLButtonElement; }}
                type="checkbox" checked={reducedMotion} onChange={(event) => setReducedMotion(event.target.checked)}
                className="h-4 w-4 accent-[rgb(var(--primary))]" />
            </label>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
