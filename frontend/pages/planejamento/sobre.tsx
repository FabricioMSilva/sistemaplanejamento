import Head from "next/head";
import Link from "next/link";
import { ArrowRight, ClipboardList, Factory, Gauge, Info, ListChecks } from "lucide-react";

const workflows = [
  {
    icon: ClipboardList,
    title: "Coleta de ordens",
    description: "Selecione os setores de manutenção e atualize as ordens de trabalho disponíveis para planejamento.",
    href: "/planejamento",
    action: "Ir para a coleta",
  },
  {
    icon: Factory,
    title: "Carteira e capacidade",
    description: "Revise as OTs preventivas e corretivas, defina o período e confira a equipe e a capacidade disponível.",
    href: "/planejamento/ots",
    action: "Abrir a carteira",
  },
  {
    icon: ListChecks,
    title: "Acompanhamento",
    description: "Consulte planejamentos, abra cronogramas e registre revisões durante a execução.",
    href: "/planejamento/acompanhamento",
    action: "Ver planejamentos",
  },
];

export default function PlanningAboutPage() {
  return (
    <>
      <Head>
        <title>Sobre | Planning &amp; Scheduling Michelin</title>
        <meta name="description" content="Conheça o fluxo e o escopo do planejamento de manutenção." />
      </Head>
      <main className="pcm-workspace mx-auto min-h-screen max-w-6xl space-y-5 p-4 lg:p-8">
        <header className="pcm-panel p-6 sm:p-8">
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-sky-300">
            <Info size={15} aria-hidden="true" /> Planning &amp; Scheduling Michelin
          </p>
          <h1 className="mt-3 text-2xl font-semibold text-white sm:text-3xl">Sobre o planejamento</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">
            Um espaço de apoio ao planejamento e à programação da manutenção. Reúne as ordens de trabalho,
            a disponibilidade da equipe e o acompanhamento dos cronogramas em um fluxo único.
          </p>
        </header>

        <section aria-labelledby="workflow-title" className="space-y-3">
          <div>
            <h2 id="workflow-title" className="text-lg font-semibold text-white">Fluxo de trabalho</h2>
            <p className="mt-1 text-sm text-slate-400">Da seleção das ordens ao acompanhamento da execução.</p>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            {workflows.map(({ icon: Icon, title, description, href, action }) => (
              <article key={title} className="pcm-panel flex min-h-52 flex-col p-5">
                <Icon size={20} className="text-sky-300" aria-hidden="true" />
                <h3 className="mt-4 text-base font-semibold text-white">{title}</h3>
                <p className="mt-2 flex-1 text-sm leading-6 text-slate-400">{description}</p>
                <Link href={href} className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-sky-300 hover:text-sky-200">
                  {action} <ArrowRight size={15} aria-hidden="true" />
                </Link>
              </article>
            ))}
          </div>
        </section>

        <section aria-labelledby="scope-title" className="pcm-panel p-5 sm:p-6">
          <h2 id="scope-title" className="flex items-center gap-2 text-base font-semibold text-white">
            <Gauge size={18} className="text-amber-300" aria-hidden="true" /> Escopo e registros
          </h2>
          <ul className="mt-4 grid gap-3 text-sm leading-6 text-slate-300 md:grid-cols-3">
            <li className="border-l-2 border-sky-400/50 pl-3">O planejamento apoia a organização das OTs e da capacidade da equipe por período.</li>
            <li className="border-l-2 border-amber-400/50 pl-3">Confirmações e PDFs de acompanhamento são mantidos localmente pelo projeto.</li>
            <li className="border-l-2 border-rose-400/50 pl-3">O nome do planejador é informado pelo usuário; não equivale a autenticação ou aprovação. Integrações com BMA e SharePoint aguardam configuração.</li>
          </ul>
        </section>
      </main>
    </>
  );
}