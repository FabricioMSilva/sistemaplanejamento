import Head from "next/head";
import Link from "next/link";

export default function HomePage() {
  return (
    <>
      <Head>
        <title>BMA Intranet | Central de operações</title>
        <meta name="description" content="Acesse os fluxos de ordens de trabalho e planejamento." />
      </Head>
      <main className="relative flex min-h-screen flex-col overflow-hidden px-5 py-6 sm:px-8 lg:px-12">
        <div className="pointer-events-none absolute -right-40 -top-48 h-[34rem] w-[34rem] rounded-full border border-white/5" />
        <div className="pointer-events-none absolute -right-20 -top-28 h-[25rem] w-[25rem] rounded-full border border-white/5" />
        <header className="relative z-10 mx-auto flex w-full max-w-7xl items-center justify-between border-b border-white/10 pb-5">
          <div className="flex items-center gap-3">
            <img src="/logo.svg?v=robomario" alt="Logo RoboMario" className="h-11 w-11" />
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-accent-400">BMA Intranet</p>
              <p className="mt-0.5 text-sm text-slate-300">RoboMario · Operações</p>
            </div>
          </div>
          <span className="hidden items-center gap-2 rounded-full border border-white/10 px-3 py-1.5 text-xs text-slate-300 sm:inline-flex">
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
            Área de trabalho
          </span>
        </header>

        <section className="relative z-10 mx-auto flex w-full max-w-7xl flex-1 flex-col justify-center py-14">
          <div className="mb-10 max-w-2xl">
            <p className="mb-3 text-sm font-medium uppercase tracking-[0.16em] text-slate-400">Central de operações</p>
            <h1 className="text-3xl font-semibold leading-tight text-white sm:text-4xl">O que vamos organizar hoje?</h1>
            <p className="mt-3 max-w-xl text-base leading-7 text-slate-400">
              Escolha um fluxo para começar. Você pode abrir uma ordem de trabalho ou estruturar um novo planejamento.
            </p>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <Link
              href="/ot"
              className="group flex min-h-64 flex-col justify-between rounded-xl border border-accent-400/30 bg-navy-900/80 p-6 transition hover:border-accent-400/70 hover:bg-navy-800/90 focus:outline-none focus:ring-2 focus:ring-accent-400 sm:p-8"
            >
              <div className="flex items-start justify-between">
                <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-accent-400/10 text-sm font-bold text-accent-400">OT</span>
                <span className="text-xl text-slate-500 transition group-hover:translate-x-1 group-hover:text-accent-400" aria-hidden="true">→</span>
              </div>
              <div className="mt-10">
                <h2 className="text-2xl font-semibold text-white">Criar OT</h2>
                <p className="mt-2 max-w-md text-sm leading-6 text-slate-400">
                  Processe uma planilha de anomalias, revise os registros e gere ordens de trabalho.
                </p>
                <span className="mt-5 inline-flex text-sm font-medium text-accent-400">Abrir fluxo de OT</span>
              </div>
            </Link>

            <Link
              href="/planejamento"
              className="group flex min-h-64 flex-col justify-between rounded-xl border border-sky-300/25 bg-navy-900/80 p-6 transition hover:border-sky-300/60 hover:bg-navy-800/90 focus:outline-none focus:ring-2 focus:ring-sky-300 sm:p-8"
            >
              <div className="flex items-start justify-between">
                <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-sky-300/10 text-lg text-sky-300" aria-hidden="true">▦</span>
                <span className="text-xl text-slate-500 transition group-hover:translate-x-1 group-hover:text-sky-300" aria-hidden="true">→</span>
              </div>
              <div className="mt-10">
                <h2 className="text-2xl font-semibold text-white">Criar planejamento</h2>
                <p className="mt-2 max-w-md text-sm leading-6 text-slate-400">
                  Defina objetivo, área responsável e período para organizar uma nova atividade.
                </p>
                <span className="mt-5 inline-flex text-sm font-medium text-sky-300">Iniciar planejamento</span>
              </div>
            </Link>
          </div>
          <Link
            href="/planejamento/acompanhamento"
            className="mt-5 inline-flex w-fit items-center gap-3 rounded-lg border border-emerald-400/25 bg-emerald-400/5 px-5 py-3 text-sm font-medium text-emerald-300 transition hover:bg-emerald-400/10 focus:outline-none focus:ring-2 focus:ring-emerald-400"
          >
            Acompanhar planejamentos · cronogramas e revisões <span aria-hidden="true">→</span>
          </Link>
        </section>

        <footer className="relative z-10 mx-auto w-full max-w-7xl border-t border-white/10 pt-4 text-xs text-slate-500">
          RoboMario · Intranet BMA
        </footer>
      </main>
    </>
  );
}
