import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useState, type ReactNode } from "react";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { ClipboardList, Ellipsis, History, House, Info, Menu, Monitor, RefreshCw, X, type LucideIcon } from "lucide-react";
import AssetImage from "@/components/ui/AssetImage";
import ThemeSwitcher from "@/components/theme/ThemeSwitcher";
import NfeReportButton from "@/components/NfeReportButton";
import { APP_BRAND, BRAND_ASSETS } from "@/config/brand-assets";
import { useTheme } from "@/providers/ThemeProvider";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: LucideIcon; match: (path: string) => boolean };

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Início", icon: House, match: (path) => path === "/" },
  { href: "/planejamento/sobre", label: "Sobre", icon: Info,
    match: (path) => path === "/planejamento/sobre" },
  { href: "/ot", label: "Criar OT", icon: ClipboardList, match: (path) => path === "/ot" },
  { href: "/historico", label: "Histórico", icon: History, match: (path) => path === "/historico" },
];

function NavLinks({ pathname, onNavigate, vertical }: { pathname: string; onNavigate?: () => void; vertical?: boolean }) {
  const [actionsOpen, setActionsOpen] = useState(false);
  return (
    <ul className={cn("flex gap-1", vertical ? "flex-col" : "items-center")}>
      {NAV_ITEMS.map(({ href, label, icon: Icon, match }) => {
        const active = match(pathname);
        return (
          <li key={href}>
            <Link href={href} onClick={onNavigate} aria-current={active ? "page" : undefined}
              className={cn(
                "relative flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                vertical ? "text-foreground hover:bg-muted" : "text-header-foreground/80 hover:bg-header-foreground/10 hover:text-header-foreground",
                active && (vertical ? "bg-primary/10 text-primary" : "text-header-foreground"),
              )}>
              <Icon size={16} aria-hidden="true" />
              {label}
              {active && !vertical && (
                <motion.span layoutId="nav-active" className="absolute inset-x-2 -bottom-[9px] h-[3px] rounded-full bg-accent"
                  transition={{ type: "spring", stiffness: 420, damping: 34 }} />
              )}
            </Link>
          </li>
        );
      })}
      {pathname === "/planejamento/ots" && <li className="relative">
        <button type="button" aria-haspopup="true" aria-expanded={actionsOpen} aria-controls="pcm-navigation-actions"
          onClick={() => setActionsOpen((open) => !open)}
          className={cn(
            "relative flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-accent",
            vertical ? "w-full text-foreground hover:bg-muted" : "text-header-foreground/80 hover:bg-header-foreground/10 hover:text-header-foreground",
            actionsOpen && (vertical ? "bg-primary/10 text-primary" : "text-header-foreground"),
          )}>
          <Ellipsis size={16} aria-hidden="true" /> Ações da carteira
        </button>
        {actionsOpen && <div id="pcm-navigation-actions" aria-label="Ações da carteira"
          className={cn("z-[100] rounded-lg border border-border bg-surface-elevated p-3 shadow-card",
            vertical ? "ml-2 mt-1 w-[calc(100%-0.5rem)]" : "absolute right-0 top-full mt-2 w-72")}>
          <p className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            BMA · snapshot local
          </p>
          <NfeReportButton compact />
          <div className="mt-2 grid gap-1 border-t border-border pt-2">
            <button type="button" onClick={() => window.dispatchEvent(new Event("pcm:toggle-tv"))}
              className="pcm-small-button w-full justify-start"><Monitor size={14} /> Alternar modo TV</button>
            <button type="button" onClick={() => window.dispatchEvent(new Event("pcm:reload-data"))}
              className="pcm-small-button w-full justify-start"><RefreshCw size={14} /> Recarregar carteira</button>
          </div>
        </div>}
      </li>}
    </ul>
  );
}

function MichelinHeader({ pathname }: { pathname: string }) {
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => setMenuOpen(false), [pathname]);
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  return (
    <header className="relative z-[90] border-b border-header-foreground/10 bg-header text-header-foreground shadow-card">
      <div className="mx-auto flex h-16 w-full max-w-[1920px] items-center gap-4 px-4 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-3 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          aria-label={`${APP_BRAND.name} · página inicial`}>
          <AssetImage asset={BRAND_ASSETS.nfeIcon} height={42} priority className="shrink-0 rounded-full bg-white" />
          <span className="hidden border-l border-header-foreground/20 pl-3 leading-tight md:block">
            <span className="block text-[15px] font-semibold tracking-tight">{APP_BRAND.name}</span>
            <span className="block text-[11px] text-header-foreground/70">{APP_BRAND.subtitle}</span>
          </span>
        </Link>
        <span className="hidden rounded-md bg-accent px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-accent-foreground sm:inline">
          {APP_BRAND.context}
        </span>
        <nav aria-label="Navegação principal" className="ml-auto hidden lg:block">
          <NavLinks pathname={pathname} />
        </nav>
        <div className="ml-auto flex items-center gap-2 lg:ml-2">
          <ThemeSwitcher />
          <button type="button" aria-label={menuOpen ? "Fechar menu" : "Abrir menu"} aria-expanded={menuOpen}
            aria-controls="mobile-navigation" onClick={() => setMenuOpen((value) => !value)}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-header-foreground/25 transition hover:bg-header-foreground/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent lg:hidden">
            {menuOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>
      </div>
      <AnimatePresence>
        {menuOpen && (
          <>
            <motion.div className="fixed inset-0 top-16 z-[80] bg-black/40 lg:hidden" onClick={() => setMenuOpen(false)}
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }} />
            <motion.nav id="mobile-navigation" aria-label="Navegação principal"
              className="fixed right-0 top-16 z-[90] h-[calc(100vh-4rem)] w-72 max-w-[85vw] border-l border-border bg-surface-elevated p-3 shadow-card lg:hidden"
              initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ duration: 0.24, ease: [0.2, 0.7, 0.2, 1] }}>
              <p className="px-3 pb-2 pt-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{APP_BRAND.subtitle}</p>
              <NavLinks pathname={pathname} vertical onNavigate={() => setMenuOpen(false)} />
            </motion.nav>
          </>
        )}
      </AnimatePresence>
    </header>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { reducedMotion } = useTheme();
  return (
    <MotionConfig reducedMotion={reducedMotion ? "always" : "user"}>
      <a href="#conteudo" className="sr-only z-[200] rounded-md bg-accent px-3 py-2 text-accent-foreground focus:not-sr-only focus:fixed focus:left-3 focus:top-3">
        Pular para o conteúdo
      </a>
      <MichelinHeader pathname={router.pathname} />
      {/* A chave é a rota (sem query) para não remontar a página quando só os parâmetros mudam. */}
      <motion.div id="conteudo" key={router.pathname} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.26, ease: [0.2, 0.7, 0.2, 1] }}>
        {children}
      </motion.div>
    </MotionConfig>
  );
}
