import type { Allocation, PlanPerson, Requirement, WorkPlan } from "@/services/pcm";
import { orderKey } from "@/services/pcm";
import { cellText, getWorkType } from "@/utils/orderFilters";
import { numericField, localDate } from "@/utils/pcmDashboard";
import { plannedLabor } from "@/utils/plannedLabor";

export const activityMode = (order: WorkPlan["ordens"][number]) => getWorkType(order) === "E" ? "corretiva" : "pm";
export function activityCategory(order: WorkPlan["ordens"][number]): string {
  if (activityMode(order) === "corretiva") return "corretiva";
  const level = cellText(order, "description").trim().toUpperCase().match(/^PM\s*([123])\b/)?.[1];
  return level ? `pm${level}` : "outras-pm";
}
export const specialtyMatches = (person: PlanPerson, requirement: Requirement) =>
  requirement.todas_especialidades === true || (person.orgid === requirement.orgid && person.funcao === requirement.funcao);
export const allocatedDuration = (plan: WorkPlan, key: string) =>
  plan.blocos.filter((b) => b.ot === key).reduce((sum, b) => sum + b.horas, 0);
export function prepareDraggedOrder(plan: WorkPlan, key: string): WorkPlan {
  const order = plan.ordens.find((item) => orderKey(item) === key);
  const requirement = plan.requisitos[key];
  if (!order || !requirement) return plan;
  const people = requirement.pessoas && requirement.pessoas > 0 ? requirement.pessoas : 1;
  const estimatedDuration = numericField(order, "estdur");
  const estimatedLabor = numericField(order, "estlabhrs");
  const duration = requirement.duracao && requirement.duracao > 0 ? requirement.duracao
    : estimatedDuration && estimatedDuration > 0 ? estimatedDuration
      : estimatedLabor && estimatedLabor > 0 ? estimatedLabor / people : null;
  const hasSpecialty = !!requirement.todas_especialidades || !!(requirement.orgid && requirement.funcao);
  return { ...plan, requisitos: { ...plan.requisitos, [key]: {
    ...requirement, duracao: duration, pessoas: people,
    todas_especialidades: hasSpecialty ? requirement.todas_especialidades : true,
  } } };
}
export function pendingActivity(plan: WorkPlan, key: string): boolean {
  const duration = plan.requisitos[key]?.duracao;
  return !duration || allocatedDuration(plan, key) < duration - 1e-6;
}
export function activityPlanningComplete(plan: WorkPlan, key: string): boolean {
  const requirement = plan.requisitos[key];
  if (!requirement?.duracao || !requirement.pessoas
    || (!requirement.todas_especialidades && (!requirement.funcao || !requirement.orgid))
    || pendingActivity(plan, key)) return false;
  const blocks = plan.blocos.filter((block) => block.ot === key);
  return blocks.length > 0 && blocks.every((block) => block.executantes.length === requirement.pessoas);
}
export function readyForAutoConfirmation(plan: WorkPlan): boolean {
  if (!plan.blocos.length || plan.posicionamentos?.length || conflictingBlocks(plan).size) return false;
  const scheduled = new Set(plan.blocos.map((block) => block.ot));
  return [...scheduled].every((key) => activityPlanningComplete(plan, key))
    && Object.entries(plan.requisitos).every(([key, requirement]) =>
      !requirement.selecionada || activityPlanningComplete(plan, key));
}
export const dayLoad = (plan: WorkPlan, person: string, day: string) =>
  plan.blocos.filter((b) => b.dia === day && b.executantes.includes(person)).reduce((sum, b) => sum + b.horas, 0);
export function provisionalDayLoad(plan: WorkPlan, person: string, day: string): number {
  const placements = new Set((plan.posicionamentos ?? [])
    .filter((placement) => placement.executante === person && placement.dia === day)
    .map((placement) => placement.ot));
  return [...placements].reduce((sum, key) => {
    const duration = plan.requisitos[key]?.duracao;
    return sum + (duration ? Math.max(0, duration - allocatedDuration(plan, key)) : 0);
  }, 0);
}
export const displayedDayLoad = (plan: WorkPlan, person: string, day: string) =>
  dayLoad(plan, person, day) + provisionalDayLoad(plan, person, day);
export const availableDay = (plan: WorkPlan, person: string, day: string) =>
  !!plan.pessoas.find((p) => p.id === person)?.dias.includes(day)
  && !plan.indisponibilidades.some((a) => a.executante === person && a.dia === day);

export function proposedDays(order: WorkPlan["ordens"][number], days: string[]): string[] {
  return days.filter((day) => [["targstartdate", "targcompdate"], ["schedstart", "schedfinish"]].some(([a, b]) => {
    const start = localDate(cellText(order, a)), end = localDate(cellText(order, b));
    return start && end && start <= end ? start <= day && day <= end : day === start || day === end;
  }));
}

export function isTargetDay(order: WorkPlan["ordens"][number], day: string): boolean {
  const start = localDate(cellText(order, "targstartdate"));
  const end = localDate(cellText(order, "targcompdate"));
  return start && end && start <= end ? start <= day && day <= end : day === start || day === end;
}

export function activityDateConstraintError(order: WorkPlan["ordens"][number], day: string): string | null {
  const earliest = localDate(cellText(order, "sneconstraint"));
  const latest = localDate(cellText(order, "fnlconstraint"));
  const format = (value: string) => value.split("-").reverse().join("/");
  if (earliest && day < earliest) return `${order.wonum}: não iniciar antes de ${format(earliest)}.`;
  if (latest && day > latest) return `${order.wonum}: não terminar depois de ${format(latest)}.`;
  return null;
}

export function scheduleSelectedDays(plan: WorkPlan, key: string, dates: string[], members: string[]): Allocation[] {
  const req = plan.requisitos[key], order = plan.ordens.find((o) => orderKey(o) === key);
  const days = [...new Set(dates)].sort(), crew = [...new Set(members)];
  if (!req?.duracao || !order || !days.length || !crew.length)
    throw new Error("Informe duração, dias de execução e executantes.");
  if (days.some((d) => weekStart(d) !== weekStart(days[0]))
    || plan.blocos.some((b) => b.ot === key && weekStart(b.dia) !== weekStart(days[0])))
    throw new Error("A atividade deve permanecer na mesma semana.");
  if (plan.blocos.some((b) => b.ot === key && b.executantes.length !== crew.length))
    throw new Error("A quantidade de executantes deve ser igual nos blocos da OT. Retire os blocos anteriores para mudar a equipe simultânea.");
  if (days.some((d) => d < plan.inicio || d > plan.fim))
    throw new Error("Dia fora do horizonte do planejamento.");
  const dateError = days.map((day) => activityDateConstraintError(order, day)).find(Boolean);
  if (dateError) throw new Error(dateError);
  if (crew.some((id) => {
    const person = plan.pessoas.find((p) => p.id === id);
    return !person || !specialtyMatches(person, req) || days.some((d) => !availableDay(plan, id, d));
  })) throw new Error("Há executante incompatível ou indisponível em um dos dias marcados.");
  const blocks = [...plan.blocos];
  let remaining = req.duracao - allocatedDuration(plan, key);
  if (remaining <= 1e-6) throw new Error("Esta atividade já está totalmente alocada.");
  for (const day of days) {
    if (remaining <= 1e-6) break;
    const snapshot = { ...plan, blocos: blocks };
    const hours = Math.round(Math.max(0, Math.min(remaining, ...crew.map((p) =>
      Math.min(8 - dayLoad(snapshot, p, day), weeklyBalance(snapshot, p, day).remaining)))) * 1e6) / 1e6;
    if (!hours) continue;
    blocks.push({ id: crypto.randomUUID(), ot: key, dia: day, inicio: 0, horas: hours, executantes: crew });
    remaining = Math.round((remaining - hours) * 1e6) / 1e6;
  }
  if (remaining > 1e-6)
    throw new Error(`Faltam ${remaining} h de espaço nos dias marcados. Marque mais dias da mesma semana ou escolha outra equipe. Nenhum bloco foi adicionado.`);
  return blocks;
}

export function resequenceWeek(
  plan: WorkPlan, blockId: string, sourcePerson: string, targetPerson: string, targetDay: string, beforeBlockId?: string,
): Allocation[] {
  const moving = plan.blocos.find((b) => b.id === blockId);
  const before = beforeBlockId ? plan.blocos.find((b) => b.id === beforeBlockId) : undefined;
  if (!moving || !moving.executantes.includes(sourcePerson))
    throw new Error("Alocação de origem não encontrada.");
  const week = weekStart(moving.dia);
  if (weekStart(targetDay) !== week || targetDay < plan.inicio || targetDay > plan.fim)
    throw new Error("Reordene dentro da mesma semana do planejamento.");
  if (beforeBlockId && (!before || before.dia !== targetDay || !before.executantes.includes(targetPerson)))
    throw new Error("Destino da sequência inválido.");
  if (before?.ot === moving.ot) return plan.blocos;
  const affected = new Set(plan.blocos.filter((b) => weekStart(b.dia) === week
    && (b.executantes.includes(sourcePerson) || b.executantes.includes(targetPerson))).map((b) => b.ot));
  const jobs = [...affected].map((ot) => {
    const blocks = plan.blocos.filter((b) => b.ot === ot);
    const crew = blocks[0].executantes;
    if (blocks.some((b) => weekStart(b.dia) !== week || b.executantes.length !== crew.length
      || b.executantes.some((p) => !crew.includes(p))))
      throw new Error("OT com equipes diferentes entre os dias: ajuste a equipe no editor antes de reordenar.");
    return { ot, crew: [...crew], hours: blocks.reduce((sum, b) => sum + b.horas, 0),
      firstDay: blocks.map((b) => b.dia).sort()[0], index: plan.blocos.indexOf(blocks[0]) };
  }).sort((a, b) => a.firstDay.localeCompare(b.firstDay) || a.index - b.index);
  const job = jobs.find((j) => j.ot === moving.ot)!;
  const nextCrew = [...new Set(job.crew.map((p) => p === sourcePerson ? targetPerson : p))];
  if (nextCrew.length !== job.crew.length) throw new Error("O executante de destino já integra esta atividade.");
  job.crew = nextCrew;
  const queue = jobs.filter((j) => j.ot !== job.ot);
  const insertion = before ? queue.findIndex((j) => j.ot === before.ot) : queue.findIndex((j) => j.firstDay >= targetDay);
  queue.splice(insertion < 0 ? queue.length : insertion, 0, job);
  const blocks = plan.blocos.filter((b) => !affected.has(b.ot));
  const cursors = new Map<string, string>();
  for (const current of queue) {
    const req = plan.requisitos[current.ot], order = plan.ordens.find((o) => orderKey(o) === current.ot);
    if (!req || !order || current.crew.some((id) => {
      const person = plan.pessoas.find((p) => p.id === id);
      return !person || !specialtyMatches(person, req);
    })) throw new Error("Equipe incompatível com a especialidade da OT.");
    const earliest = localDate(cellText(order, "sneconstraint")), latest = localDate(cellText(order, "fnlconstraint"));
    const start = [plan.inicio, week, earliest ?? "", current.ot === job.ot ? targetDay : "",
      ...current.crew.map((p) => cursors.get(p) ?? "")].sort().pop()!;
    const dates = [...new Set(plan.pessoas.flatMap((p) => p.dias))].sort().filter((d) =>
      d >= start && d <= plan.fim && weekStart(d) === week && (!latest || d <= latest)
      && current.crew.every((p) => availableDay(plan, p, d)));
    let remaining = current.hours;
    for (const day of dates) {
      if (remaining <= 1e-6) break;
      const snapshot = { ...plan, blocos: blocks };
      const hours = Math.round(Math.max(0, Math.min(remaining, ...current.crew.map((p) =>
        Math.min(8 - dayLoad(snapshot, p, day), weeklyBalance(snapshot, p, day).remaining)))) * 1e6) / 1e6;
      if (!hours) continue;
      blocks.push({ id: crypto.randomUUID(), ot: current.ot, dia: day, inicio: 0, horas: hours, executantes: current.crew });
      remaining = Math.round((remaining - hours) * 1e6) / 1e6;
      for (const person of current.crew) cursors.set(person, day);
    }
    if (remaining > 1e-6) throw new Error(`${order.wonum}: a nova sequência não cabe nos dias/equipe da semana. Nenhuma alocação foi alterada.`);
  }
  return blocks;
}

export function weekStart(day: string): string {
  const value = new Date(`${day}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() - (value.getUTCDay() + 6) % 7);
  return value.toISOString().slice(0, 10);
}

export function weeklyBalance(plan: WorkPlan, person: string, day: string) {
  const week = weekStart(day);
  const capacity = (plan.pessoas.find((p) => p.id === person)?.dias ?? []).filter((d) =>
    d >= plan.inicio && d <= plan.fim && weekStart(d) === week && availableDay(plan, person, d)).length * 8;
  const load = plan.blocos.filter((b) => b.executantes.includes(person) && weekStart(b.dia) === week)
    .reduce((sum, b) => sum + b.horas, 0);
  return { capacity, load, remaining: capacity - load };
}

export function conflictingBlocks(plan: WorkPlan): Set<string> {
  const overloaded = new Set<string>();
  for (const person of plan.pessoas) {
    for (const week of new Set(person.dias.map(weekStart))) {
      if (weeklyBalance(plan, person.id, week).remaining < -1e-6) overloaded.add(JSON.stringify([person.id, week]));
    }
  }
  return new Set(plan.blocos.filter((b) => b.executantes.some((p) => overloaded.has(JSON.stringify([p, weekStart(b.dia)])))).map((b) => b.id));
}

export function planningMetrics(plan: WorkPlan) {
  const modes = new Map(plan.ordens.map((o) => [orderKey(o), activityMode(o)]));
  const capacity = plan.pessoas.reduce((sum, p) => sum + p.dias.filter((day) => availableDay(plan, p.id, day)).length * 8, 0);
  const pm = plan.blocos.filter((b) => modes.get(b.ot) === "pm").reduce((sum, b) => sum + b.horas * b.executantes.length, 0);
  const corrective = plan.blocos.filter((b) => modes.get(b.ot) === "corretiva").reduce((sum, b) => sum + b.horas * b.executantes.length, 0);
  return { capacity, pm, corrective, remaining: capacity - pm - corrective };
}

export function specialtyWorkload(plan: WorkPlan) {
  type Group = {
    orgid: string; funcao: string; nome: string; ordens: Set<string>;
    horasPM: number; estimativasPendentes: Set<string>; capacidade: number; comprometido: number;
  };
  const groups = new Map<string, Group>();
  const people = new Map(plan.pessoas.map((person) => [person.id, person]));
  const groupFor = (orgid: string, funcao: string, nome?: string) => {
    const key = JSON.stringify([orgid, funcao]);
    let group = groups.get(key);
    if (!group) {
      group = { orgid, funcao, nome: nome || (funcao ? `Especialidade ${funcao}` : "Não definida"),
        ordens: new Set(), horasPM: 0, estimativasPendentes: new Set(), capacidade: 0, comprometido: 0 };
      groups.set(key, group);
    } else if (nome && group.nome.startsWith("Especialidade ")) group.nome = nome;
    return group;
  };

  for (const person of plan.pessoas) {
    const group = groupFor(person.orgid, person.funcao, person.funcao_descricao);
    group.capacidade += person.dias.filter((day) => availableDay(plan, person.id, day)).length * 8;
  }
  for (const block of plan.blocos) {
    for (const personId of block.executantes) {
      const person = people.get(personId);
      if (person) groupFor(person.orgid, person.funcao, person.funcao_descricao).comprometido += block.horas;
    }
  }
  for (const order of plan.ordens) {
    if (activityMode(order) !== "pm") continue;
    const key = orderKey(order), requirement = plan.requisitos[key];
    const labor = plannedLabor(order);
    const rows = labor.length ? labor.map((item) => ({
      orgid: item.orgid || requirement?.orgid || "",
      funcao: item.craft,
      nome: undefined as string | undefined,
      horas: item.hours.trim() ? Number(item.hours) : Number.NaN,
    })) : [{
      orgid: requirement?.orgid ?? "", funcao: requirement?.funcao ?? "", nome: undefined as string | undefined,
      horas: numericField(order, "estlabhrs") ?? (requirement?.duracao && requirement.pessoas
        ? requirement.duracao * requirement.pessoas : Number.NaN),
    }];
    for (const row of rows) {
      const group = groupFor(row.orgid, row.funcao, row.nome);
      group.ordens.add(key);
      if (Number.isFinite(row.horas) && row.horas >= 0) group.horasPM += row.horas;
      else group.estimativasPendentes.add(key);
    }
  }
  return [...groups.values()].map((group) => ({
    ...group, ordensPM: group.ordens.size, estimativasPendentes: group.estimativasPendentes.size,
    saldo: group.capacidade - group.comprometido,
  })).sort((a, b) => b.horasPM - a.horasPM || a.nome.localeCompare(b.nome));
}

export function dropActivity(
  plan: WorkPlan, key: string, day: string, personId: string, blockId?: string, sourcePerson?: string,
): Allocation[] {
  const req = plan.requisitos[key];
  if (!req?.duracao || !req.pessoas || (!req.todas_especialidades && (!req.funcao || !req.orgid)))
    throw new Error("Prepare a OT: duração, pessoas e especialidade.");
  const order = plan.ordens.find((o) => orderKey(o) === key);
  if (day < plan.inicio || day > plan.fim) throw new Error("Dia fora do horizonte do planejamento.");
  const dateError = order && activityDateConstraintError(order, day);
  if (dateError) throw new Error(dateError);
  const previous = plan.blocos.find((b) => b.id === blockId);
  const blocks = plan.blocos.filter((b) => b.id !== blockId);
  const snapshot = { ...plan, blocos: blocks };
  if (blocks.some((b) => b.ot === key && weekStart(b.dia) !== weekStart(day)))
    throw new Error("A continuação da atividade deve permanecer na mesma semana. Retire/replaneje a OT completa para mudar de semana.");
  const eligible = plan.pessoas.filter((p) => specialtyMatches(p, req) && availableDay(snapshot, p.id, day))
    .sort((a, b) => dayLoad(snapshot, a.id, day) - dayLoad(snapshot, b.id, day)).map((p) => p.id);
  const crew = previous
    ? [...new Set(previous.executantes.map((p) => p === sourcePerson ? personId : p))]
    : [personId, ...eligible.filter((p) => p !== personId)].slice(0, req.pessoas);
  if (!eligible.includes(personId) || crew.length !== req.pessoas || crew.some((p) => !eligible.includes(p)))
    throw new Error("Não há equipe compatível disponível neste dia.");
  const remaining = req.duracao - allocatedDuration(snapshot, key);
  if (remaining <= 1e-6) throw new Error("Esta atividade já está totalmente alocada.");
  const hours = previous?.horas ?? Math.min(remaining, ...crew.map((p) =>
    Math.min(8 - dayLoad(snapshot, p, day), weeklyBalance(snapshot, p, day).remaining)));
  if (hours <= 1e-6) throw new Error("Não há capacidade diária de referência ou semanal livre.");
  return [...blocks, { id: previous?.id ?? crypto.randomUUID(), ot: key, dia: day, inicio: 0,
    horas: Math.round(hours * 1e6) / 1e6, executantes: crew }];
}

export function distributeBatch(plan: WorkPlan, keys: string[], personId: string, fromDay = plan.inicio, exactDay = false) {
  const target = plan.pessoas.find((p) => p.id === personId);
  if (!target) throw new Error("Executante fora da equipe.");
  let blocks = [...plan.blocos];
  const messages: string[] = [];
  for (const key of [...new Set(keys)]) {
    const req = plan.requisitos[key];
    const order = plan.ordens.find((o) => orderKey(o) === key);
    if (!order || !req?.duracao || !req.pessoas
      || (!req.todas_especialidades && (!req.funcao || !req.orgid))) {
      const missing = [
        !req?.duracao && "duração",
        !req?.pessoas && "quantidade de pessoas",
        !req?.todas_especialidades && (!req?.funcao || !req?.orgid) && "especialidade",
      ].filter(Boolean).join(", ");
      messages.push(`${order?.wonum ?? key}: informe ${missing} na preparação para alocar.`);
      continue;
    }
    if (!specialtyMatches(target, req)) {
      messages.push(`${order.wonum}: executante incompatível com a especialidade exigida.`);
      continue;
    }
    const earliest = localDate(cellText(order, "sneconstraint"));
    const latest = localDate(cellText(order, "fnlconstraint"));
    const activityWeek = weekStart(blocks.find((b) => b.ot === key)?.dia ?? fromDay);
    const days = [...target.dias].sort().filter((d) => weekStart(d) === activityWeek && d >= fromDay && d >= plan.inicio && d <= plan.fim
      && (!earliest || d >= earliest) && (!latest || d <= latest) && availableDay(plan, personId, d));
    let remaining = Math.max(0, req.duracao - allocatedDuration({ ...plan, blocos: blocks }, key));
    if (exactDay && keys.length === 1 && remaining > 1e-6) {
      if (!days.includes(fromDay)) {
        messages.push(activityDateConstraintError(order, fromDay)
          ?? `${order.wonum}: o dia escolhido está indisponível ou fora da semana/restrições da OT. Nenhum outro dia foi usado.`);
        continue;
      }
      const snapshot = { ...plan, blocos: blocks };
      const room = (p: string) => Math.min(weeklyBalance(snapshot, p, fromDay).remaining, 8 - dayLoad(snapshot, p, fromDay));
      const others = plan.pessoas.filter((p) => p.id !== personId && specialtyMatches(p, req) && availableDay(plan, p.id, fromDay))
        .sort((a, b) => room(b.id) - room(a.id));
      const crew = [personId, ...others.map((p) => p.id)].slice(0, req.pessoas);
      const hours = crew.length === req.pessoas ? Math.round(Math.min(remaining, 8, ...crew.map(room)) * 1e6) / 1e6 : 0;
      if (hours <= 1e-6) {
        messages.push(`${order.wonum}: sem equipe compatível ou espaço diário/semanal para o quadrado escolhido. Nenhum outro dia foi usado.`);
        continue;
      }
      blocks.push({ id: crypto.randomUUID(), ot: key, dia: fromDay, inicio: 0, horas: hours, executantes: crew });
      remaining = Math.round((remaining - hours) * 1e6) / 1e6;
    }
    // First spread at the 8 h/day reference; then allow daily flexibility within each week's capacity.
    for (const flexible of exactDay ? [false] : [false, true]) {
      for (const day of days) {
        if (remaining <= 1e-6) break;
        const snapshot = { ...plan, blocos: blocks };
        const room = (p: string) => Math.max(0, Math.min(weeklyBalance(snapshot, p, day).remaining,
          flexible ? remaining : 8 - dayLoad(snapshot, p, day)));
        const others = plan.pessoas.filter((p) => p.id !== personId && specialtyMatches(p, req) && availableDay(plan, p.id, day))
          .sort((a, b) => room(b.id) - room(a.id));
        const crew = [personId, ...others.map((p) => p.id)].slice(0, req.pessoas);
        if (crew.length !== req.pessoas) continue;
        const hours = Math.round(Math.min(remaining, ...crew.map(room)) * 1e6) / 1e6;
        if (hours <= 1e-6) continue;
        blocks.push({ id: crypto.randomUUID(), ot: key, dia: day, inicio: 0, horas: hours, executantes: crew });
        remaining = Math.round((remaining - hours) * 1e6) / 1e6;
      }
    }
    if (remaining > 1e-6)
      messages.push(`${order.wonum}: ${remaining} h pendentes; não cabem na capacidade semanal/equipe/datas disponíveis. Não foram enviadas para outra semana automaticamente.`);
  }
  return { blocos: blocks, mensagens: messages };
}
