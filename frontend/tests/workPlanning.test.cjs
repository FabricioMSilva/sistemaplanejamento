const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const cache = new Map();
function load(relative) {
  const file = path.join(__dirname, "..", `${relative}.ts`);
  if (cache.has(file)) return cache.get(file);
  const js = ts.transpileModule(fs.readFileSync(file, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const m = { exports: {} };
  cache.set(file, m.exports);
  new Function("require", "module", "exports", js)((request) => {
    if (request.startsWith("@/")) return load(request.slice(2));
    throw Error(`Unexpected runtime dependency: ${request}`);
  }, m, m.exports);
  return m.exports;
}
const { dropActivity, activityDateConstraintError, activityDateWarning, activityDateStatus, isGalleryBmaStatus, isTargetDay, planningMetrics, dayLoad, provisionalDayLoad, displayedDayLoad, specialtyWorkload, distributeBatch, prepareDraggedOrder, activityPlanningComplete, readyForAutoConfirmation, conflictingBlocks, allocatedDuration, weeklyBalance, pendingActivity, scheduleSelectedDays, proposedDays, activityCategory, resequenceWeek, laborHelperCandidates, addLaborHelper, returnOrderToPortfolio } = load("utils/workPlanning");
const { matchesOrderSpecialty, missingPlanningData, plannedLabor, plannedBmaOrders } = load("utils/plannedLabor");
const { preparationRequirements, underAllocatedPreparationOrders } = load("utils/plannedLabor");
function fixture() {
  return {
    inicio: "2026-10-26", fim: "2026-10-27",
    pessoas: ["A", "B"].map(id => ({ id, orgid: "BR", funcao: "180", dias: ["2026-10-26", "2026-10-27"] })),
    ordens: [{ siteid: "RES", wonum: "PM1", dados: { worktype: "S" } }, { siteid: "RES", wonum: "E1", dados: { worktype: "E" } }],
    requisitos: {
      "RES:PM1": { duracao: 10, pessoas: 2, orgid: "BR", funcao: "180", liberada: true },
      "RES:E1": { duracao: 6, pessoas: 2, orgid: "BR", funcao: "180", liberada: true },
    },
    blocos: [], indisponibilidades: [],
  };
}
test("drop creates simultaneous daily blocks and shared PM/corrective capacity", () => {
  const plan = fixture();
  plan.blocos = dropActivity(plan, "RES:PM1", "2026-10-26", "A");
  assert.equal(plan.blocos[0].horas, 8);
  assert.deepEqual(plan.blocos[0].executantes, ["A", "B"]);
  plan.blocos = dropActivity(plan, "RES:PM1", "2026-10-27", "B");
  assert.equal(plan.blocos[1].horas, 2);
  plan.blocos = dropActivity(plan, "RES:E1", "2026-10-27", "A");
  assert.equal(plan.blocos[2].inicio, 0);
  assert.equal(plan.blocos[2].horas, 6);
  assert.deepEqual(planningMetrics(plan), { capacity: 32, pm: 20, corrective: 12, remaining: 0 });
  assert.equal(dayLoad(plan, "A", "2026-10-27"), 8);
  assert.throws(() => dropActivity(plan, "RES:PM1", "2026-10-27", "A"), /totalmente alocada/);
});
test("manual multi-person drop uses only the explicitly selected crew", () => {
  const plan = fixture();
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], duracao: 2, pessoas: 2 };

  const result = distributeBatch(plan, ["RES:PM1"], "A", plan.inicio, true, ["A", "B"]);

  assert.equal(result.blocos.length, 1);
  assert.deepEqual(result.blocos[0].executantes, ["A", "B"]);
  const invalidTeam = distributeBatch(plan, ["RES:PM1"], "A", plan.inicio, true, ["A"]);
  assert.equal(invalidTeam.blocos.length, 0);
  assert.match(invalidTeam.mensagens[0], /exatamente 2 executantes/);
});
test("not-before stays enforced while a late exact drop is allowed and marked", () => {
  const plan = fixture(), order = plan.ordens[0];
  plan.fim = "2026-10-28";
  for (const person of plan.pessoas) person.dias.push("2026-10-28");
  order.dados = { sneconstraint: "2026-10-27", fnlconstraint: "2026-10-27" };
  assert.throws(() => dropActivity(plan, "RES:PM1", "2026-10-26", "A"), /PM1: não iniciar antes de 27\/10\/2026/);
  assert.equal(activityDateConstraintError(order, "2026-10-28"), null);
  assert.equal(activityDateStatus(order, "2026-10-28"), "late");
  assert.equal(dropActivity(plan, "RES:PM1", "2026-10-28", "A").length, 1);
  assert.match(activityDateConstraintError(order, "2026-10-26"), /não iniciar antes/);
  const invalidDrop = distributeBatch(plan, ["RES:PM1"], "A", "2026-10-26", true);
  assert.equal(invalidDrop.blocos.length, 0);
  assert.match(invalidDrop.mensagens[0], /não iniciar antes/);
  const lateDrop = distributeBatch(plan, ["RES:PM1"], "A", "2026-10-28", true);
  assert.equal(lateDrop.blocos[0].dia, "2026-10-28");
});
test("dropping on an executor name may allocate late and still reports the deadline", () => {
  const plan = fixture();
  plan.fim = "2026-10-28";
  plan.blocos = [];
  for (const person of plan.pessoas) person.dias.push("2026-10-28");
  plan.ordens[0].dados = { sneconstraint: plan.inicio, fnlconstraint: "2026-10-27" };
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], duracao: 1, pessoas: 1 };

  const result = distributeBatch(plan, ["RES:PM1"], "A", "2026-10-28");

  assert.equal(result.blocos[0].dia, "2026-10-28");
  assert.match(activityDateWarning(plan.ordens[0], result.blocos[0].dia), /atraso/);
});
test("same-week reordering can move an activity past the BMA finish constraint", () => {
  const plan = fixture();
  plan.fim = "2026-10-28";
  for (const person of plan.pessoas) person.dias.push("2026-10-28");
  plan.ordens[0].dados = { sneconstraint: plan.inicio, fnlconstraint: "2026-10-27" };
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], duracao: 1, pessoas: 1 };
  plan.blocos = [{ id: "late-move", ot: "RES:PM1", dia: plan.inicio, inicio: 0, horas: 1, executantes: ["A"] }];

  const moved = resequenceWeek(plan, "late-move", "A", "A", "2026-10-28");

  assert.equal(moved[0].dia, "2026-10-28");
  assert.equal(activityDateStatus(plan.ordens[0], moved[0].dia), "late");
});
test("drag preparation uses BMA estimates and safe defaults without inventing duration", () => {
  const plan = fixture();
  plan.ordens[0].dados.estdur = 4;
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], duracao: null, pessoas: null, orgid: "", funcao: "", todas_especialidades: false };
  const prepared = prepareDraggedOrder(plan, "RES:PM1");
  assert.equal(prepared.requisitos["RES:PM1"].duracao, 4);
  assert.equal(prepared.requisitos["RES:PM1"].pessoas, 1);
  assert.equal(prepared.requisitos["RES:PM1"].todas_especialidades, true);
  const scheduled = distributeBatch(prepared, ["RES:PM1"], "A", plan.inicio, true);
  assert.equal(scheduled.blocos[0].horas, 4);
  assert.deepEqual(scheduled.blocos[0].executantes, ["A"]);

  const noEstimate = { ...plan, ordens: [{ siteid: "RES", wonum: "PM1", dados: { worktype: "S" } }] };
  assert.equal(prepareDraggedOrder(noEstimate, "RES:PM1").requisitos["RES:PM1"].duracao, null);
});
test("collected preparation flags an OT with multiple specialty requirements and one assigned person", () => {
  const plan = fixture();
  plan.ordens[0].dados = { wplabor_origem: "Preparação", wplabor: [
    { especialidade: "180", quantidade: "1", "horas normais": "4" },
    { especialidade: "300", quantidade: "1", "horas normais": "2" },
  ] };
  plan.blocos = [{ id: "b1", ot: "RES:PM1", dia: plan.inicio, inicio: 0, horas: 4, executantes: ["A"] }];

  const requirements = preparationRequirements(plan.ordens[0]);
  const understaffed = underAllocatedPreparationOrders(plan);

  assert.deepEqual(requirements.map((row) => [row.especialidade, row.quantidade, row.horas_normais]), [
    ["180", 1, "4"], ["300", 1, "2"],
  ]);
  assert.equal(understaffed.length, 1);
  assert.equal(understaffed[0].requiredCount, 2);
  assert.equal(understaffed[0].missingCount, 1);
  plan.blocos[0].executantes.push("B");
  assert.equal(underAllocatedPreparationOrders(plan).length, 0);
});
test("complete dragged orders are ready for automatic confirmation only without pending work or conflicts", () => {
  const plan = fixture();
  plan.ordens[0].dados.estdur = 4;
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], duracao: null, pessoas: null, orgid: "", funcao: "", todas_especialidades: false };
  const prepared = prepareDraggedOrder(plan, "RES:PM1");
  const result = distributeBatch(prepared, ["RES:PM1"], "A", plan.inicio, true);
  const ready = { ...prepared, blocos: result.blocos,
    requisitos: { ...prepared.requisitos, "RES:PM1": { ...prepared.requisitos["RES:PM1"], selecionada: true } } };
  assert.equal(activityPlanningComplete(ready, "RES:PM1"), true);
  assert.equal(readyForAutoConfirmation(ready), true);
  assert.equal(readyForAutoConfirmation({ ...ready, posicionamentos: [{ ot: "RES:E1", executante: "A", dia: plan.inicio }] }), false);
  assert.equal(readyForAutoConfirmation({ ...ready, requisitos: { ...ready.requisitos, "RES:E1": { ...ready.requisitos["RES:E1"], selecionada: true } } }), false);
});
test("drop refuses absence and missing preparation but allows different specialties", () => {
  const plan = fixture();
  plan.indisponibilidades = [{ executante: "A", dia: "2026-10-26", motivo: "Falta" }];
  assert.throws(() => dropActivity(plan, "RES:PM1", "2026-10-26", "A"), /equipe compatível/);
  plan.indisponibilidades = [];
  plan.pessoas[1].funcao = "OTHER";
  assert.deepEqual(dropActivity(plan, "RES:PM1", "2026-10-26", "A")[0].executantes, ["A", "B"]);
  plan.requisitos["RES:PM1"].pessoas = null;
  assert.throws(() => dropActivity(plan, "RES:PM1", "2026-10-26", "A"), /Prepare/);
});
test("moving a block preserves duration and replaces only source member", () => {
  const plan = fixture();
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], duracao: 4, pessoas: 1 };
  plan.blocos = dropActivity(plan, "RES:PM1", "2026-10-26", "A");
  const original = plan.blocos[0];
  plan.blocos = dropActivity(plan, "RES:PM1", "2026-10-27", "B", original.id, "A");
  assert.equal(plan.blocos.length, 1);
  assert.equal(plan.blocos[0].id, original.id);
  assert.equal(plan.blocos[0].horas, 4);
  assert.deepEqual(plan.blocos[0].executantes, ["B"]);
  assert.equal(plan.blocos[0].dia, "2026-10-27");
});
test("all specialties permits mixed crew without bypassing absences or simultaneous count", () => {
  const plan = fixture();
  plan.pessoas[1].funcao = "210";
  plan.requisitos["RES:PM1"] = {
    ...plan.requisitos["RES:PM1"], orgid: "", funcao: "", todas_especialidades: true,
  };
  const blocks = dropActivity(plan, "RES:PM1", "2026-10-26", "B");
  assert.deepEqual(blocks[0].executantes, ["B", "A"]);
  plan.indisponibilidades = [{ executante: "A", dia: "2026-10-26", motivo: "Falta" }];
  assert.throws(() => dropActivity(plan, "RES:PM1", "2026-10-26", "B"), /equipe compatível/);
  plan.indisponibilidades = [];
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], todas_especialidades: false, orgid: "BR", funcao: "180" };
  assert.deepEqual(dropActivity(plan, "RES:PM1", "2026-10-26", "B")[0].executantes, ["B", "A"]);
});

test("batch uses 10 free hours and leaves 2 pending instead of exceeding the week", () => {
  const plan = fixture();
  plan.requisitos["RES:E1"].pessoas = 1;
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], duracao: 12, pessoas: 1 };
  plan.blocos = dropActivity(plan, "RES:E1", "2026-10-26", "A");
  const result = distributeBatch(plan, ["RES:PM1"], "A");
  assert.match(result.mensagens[0], /2 h pendentes/);
  plan.blocos = result.blocos;
  assert.equal(allocatedDuration(plan, "RES:PM1"), 10);
  assert.equal(plan.blocos.reduce((sum, b) => sum + b.horas, 0), 16);
  assert.equal(dayLoad(plan, "A", "2026-10-26"), 8);
  assert.equal(conflictingBlocks(plan).size, 0);
  assert.ok(plan.blocos.every((b) => b.inicio === 0));
  assert.equal(distributeBatch(plan, ["RES:PM1"], "A").blocos.length, plan.blocos.length);
  plan.blocos = distributeBatch(plan, ["RES:PM1"], "B").blocos;
  assert.equal(allocatedDuration(plan, "RES:PM1"), 12);
  assert.equal(conflictingBlocks(plan).size, 0);
});

test("batch reports incompatible or unprepared OTs and respects absences and date constraints", () => {
  const plan = fixture();
  plan.requisitos["RES:E1"].duracao = null;
  let result = distributeBatch(plan, ["RES:E1"], "A");
  assert.equal(result.blocos.length, 0);
  assert.equal(result.mensagens.length, 1);
  plan.ordens[0].dados.sneconstraint = "2026-10-27";
  plan.indisponibilidades = [{ executante: "A", dia: "2026-10-27", motivo: "Falta" }];
  result = distributeBatch(plan, ["RES:PM1"], "A");
  assert.equal(result.blocos.length, 0);
  assert.match(result.mensagens[0], /pendentes/);
  assert.throws(() => dropActivity(plan, "RES:PM1", "2026-10-26", "A"), /não iniciar antes/);
});

test("daily 12 h is valid within a 16 h week; only weekly excess is red", () => {
  const plan = fixture();
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], duracao: 12, pessoas: 1 };
  plan.blocos = distributeBatch(plan, ["RES:PM1"], "A").blocos;
  assert.deepEqual(plan.blocos.map((b) => b.horas), [8, 4]);
  const nextDay = plan.blocos[1];
  plan.blocos = dropActivity(plan, nextDay.ot, "2026-10-26", "A", nextDay.id, "A");
  assert.equal(dayLoad(plan, "A", "2026-10-26"), 12);
  assert.equal(conflictingBlocks(plan).size, 0);
  assert.deepEqual(weeklyBalance(plan, "A", plan.inicio), { capacity: 16, load: 12, remaining: 4 });
  plan.blocos.push({ id: "excess", ot: "RES:E1", dia: plan.inicio, inicio: 0, horas: 6, executantes: ["A"] });
  assert.equal(conflictingBlocks(plan).size, 3);
  assert.equal(weeklyBalance(plan, "A", plan.inicio).remaining, -2);
});

test("one week cannot borrow capacity from the following week or absent days", () => {
  const plan = fixture();
  plan.fim = "2026-11-02";
  plan.pessoas[0].dias.push("2026-11-02");
  plan.blocos = [{ id: "a", ot: "RES:PM1", dia: plan.inicio, inicio: 0, horas: 18, executantes: ["A"] }];
  assert.equal(conflictingBlocks(plan).size, 1);
  assert.equal(weeklyBalance(plan, "A", "2026-11-02").remaining, 8);
  plan.indisponibilidades.push({ executante: "A", dia: "2026-10-27", motivo: "Falta" });
  assert.equal(weeklyBalance(plan, "A", plan.inicio).capacity, 8);
});

test("specialty filter uses collected BMA labor, supports multiple specialties and manual legacy requirements", () => {
  const plan = fixture(), order = plan.ordens[0], req = plan.requisitos["RES:PM1"];
  assert.equal(matchesOrderSpecialty(order, req, "180"), true);
  order.dados.wplabor = [{ craft: { value: "270" }, quantity: 1, laborhrs: 40 }, { craft: "210", quantity: 2 }];
  assert.equal(plannedLabor(order)[0].craft, "270");
  assert.equal(matchesOrderSpecialty(order, req, "270"), true);
  assert.equal(matchesOrderSpecialty(order, req, "210"), true);
  assert.equal(matchesOrderSpecialty(order, req, "180"), false);
  assert.equal(matchesOrderSpecialty(order, req, "indefinida"), false);
  order.dados.estdur = 4;
  order.dados.wplabor = [{ especialidade: "300", quantidade: "1", "horas normais": "0:30" }];
  assert.deepEqual(plannedLabor(order)[0], { craft: "300", orgid: "", quantity: "1", hours: "0:30", skill: "" });
  assert.equal(matchesOrderSpecialty(order, req, "300"), true);
  assert.deepEqual(missingPlanningData(order), []);
  order.dados.wplabor = [];
  req.funcao = "";
  assert.equal(matchesOrderSpecialty(order, req, "indefinida"), true);
  req.todas_especialidades = true;
  assert.equal(matchesOrderSpecialty(order, req, "qualquer"), true);
});
test("missing BMA duration or quantity is identified for red schedule borders", () => {
  const order = fixture().ordens[0];
  order.dados.estdur = 4;
  assert.deepEqual(missingPlanningData(order), ["quantidade de mão de obra"]);
  order.dados.wplabor = [{ craft: { value: "180" }, quantity: { _value: 1 }, laborhrs: 4 }];
  assert.deepEqual(missingPlanningData(order), []);
  delete order.dados.estdur;
  order.dados.estlabhrs = 0;
  assert.deepEqual(missingPlanningData(order), ["duração estimada"]);
});

test("BMA preview groups planned order blocks with each date and assigned executants", () => {
  const plan = {
    ordens: [
      { siteid: "RES", wonum: "OT-10", dados: { description: "Bomba" } },
      { siteid: "RES", wonum: "OT-2", dados: { description: "Motor" } },
      { siteid: "RES", wonum: "OT-99", dados: { description: "Não alocada" } },
    ],
    requisitos: { "RES:OT-10": { funcao: "180" } },
    pessoas: [
      { id: "BR:100", nome: "Ana Souza", matricula: "100" },
      { id: "BR:200", nome: "Bruno Lima", matricula: "200" },
    ],
    blocos: [
      { ot: "RES:OT-10", dia: "2026-10-28", horas: 2, executantes: ["BR:100"] },
      { ot: "RES:OT-10", dia: "2026-10-29", horas: 1, executantes: ["BR:100", "BR:200"] },
      { ot: "RES:OT-2", dia: "2026-10-27", horas: 3, executantes: ["BR:200"] },
    ],
  };
  const rows = plannedBmaOrders(plan);
  assert.deepEqual(rows.map((row) => row.order.wonum), ["OT-2", "OT-10"]);
  assert.deepEqual(rows[1].allocations, [
    { dia: "2026-10-28", horas: 2, executantes: ["Ana Souza - 100"] },
    { dia: "2026-10-29", horas: 1, executantes: ["Ana Souza - 100", "Bruno Lima - 200"] },
  ]);
  assert.deepEqual(rows[1].planning, {
    planned_start: "2026-10-28T00:01:00",
    planned_finish: "2026-10-29T23:59:00",
    specialty: "180",
    assignments: [
      { dia: "2026-10-28", laborcode: "100", horas: 2 },
      { dia: "2026-10-29", laborcode: "100", horas: 1 },
      { dia: "2026-10-29", laborcode: "200", horas: 1 },
    ],
  });
});

test("BMA preview infers specialty from a unique assigned labor registration", () => {
  const plan = {
    ordens: [{ siteid: "RES", wonum: "OT-1", dados: {} }],
    requisitos: { "RES:OT-1": { funcao: "" } },
    pessoas: [{ id: "BR:100", nome: "Ana Souza", matricula: "100", funcao: "180" }],
    blocos: [{ ot: "RES:OT-1", dia: "2026-10-28", horas: 2, executantes: ["BR:100"] }],
  };
  const [row] = plannedBmaOrders(plan);
  assert.equal(row.planning.specialty, "180");
  assert.deepEqual(row.allocations[0].executantes, ["Ana Souza - 100"]);
});

test("pending portfolio hides complete orders, retains partials, and restores removed allocations", () => {
  const plan = fixture();
  assert.equal(pendingActivity(plan, "RES:PM1"), true);
  plan.blocos = dropActivity(plan, "RES:PM1", plan.inicio, "A");
  assert.equal(pendingActivity(plan, "RES:PM1"), true);
  plan.blocos = distributeBatch(plan, ["RES:PM1"], "A").blocos;
  assert.equal(pendingActivity(plan, "RES:PM1"), false);
  plan.blocos = [];
  assert.equal(pendingActivity(plan, "RES:PM1"), true);
  plan.requisitos["RES:PM1"].duracao = null;
  assert.equal(pendingActivity(plan, "RES:PM1"), true);
});

test("specialty is optional preparation data while people count is still required", () => {
  const plan = fixture();
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], pessoas: null, funcao: "", orgid: "" };
  const result = distributeBatch(plan, ["RES:PM1"], "A");
  assert.equal(result.blocos.length, 0);
  assert.match(result.mensagens[0], /quantidade de pessoas/);
  assert.doesNotMatch(result.mensagens[0], /especialidade/);
});

test("positioned estimated hours preview daily occupancy without reserving capacity", () => {
  const plan = fixture();
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], duracao: 4, pessoas: null };
  plan.posicionamentos = [{ ot: "RES:PM1", executante: "A", dia: plan.inicio }];
  assert.equal(dayLoad(plan, "A", plan.inicio), 0);
  assert.equal(provisionalDayLoad(plan, "A", plan.inicio), 4);
  assert.equal(displayedDayLoad(plan, "A", plan.inicio), 4);
  plan.blocos.push({ id: "partial", ot: "RES:PM1", dia: plan.inicio, inicio: 0, horas: 2, executantes: ["A"] });
  assert.equal(provisionalDayLoad(plan, "A", plan.inicio), 2);
  assert.equal(displayedDayLoad(plan, "A", plan.inicio), 4);
  assert.equal(weeklyBalance(plan, "A", plan.inicio).remaining, 14);
});

test("PM workload compares specialty labor hours with team capacity and remaining balance", () => {
  const plan = fixture();
  plan.pessoas[0].funcao_descricao = "Mecânico";
  plan.pessoas[1] = { ...plan.pessoas[1], funcao: "210", funcao_descricao: "Eletricista" };
  plan.ordens[0].dados.wplabor = [{ craft: "180", orgid: "BR", laborhrs: 6 }];
  plan.ordens.push({ siteid: "RES", wonum: "PM2", dados: { worktype: "S", wplabor: [
    { craft: "210", orgid: "BR", laborhrs: 3 },
  ] } });
  plan.requisitos["RES:PM2"] = { ...plan.requisitos["RES:PM1"], duracao: 3, pessoas: 1, funcao: "210" };
  plan.blocos = [{ id: "pm-block", ot: "RES:PM1", dia: plan.inicio, inicio: 0, horas: 2, executantes: ["A"] }];
  const workload = specialtyWorkload(plan);
  const mechanic = workload.find((row) => row.funcao === "180");
  const electrician = workload.find((row) => row.funcao === "210");
  assert.deepEqual([mechanic.horasPM, mechanic.capacidade, mechanic.comprometido, mechanic.saldo, mechanic.ordensPM], [6, 16, 2, 14, 1]);
  assert.deepEqual([electrician.horasPM, electrician.capacidade, electrician.comprometido, electrician.saldo, electrician.ordensPM], [3, 16, 0, 16, 1]);
});

test("exact cell drop on a full day keeps intention pending rather than exceeding daily reference", () => {
  const plan = fixture();
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], duracao: 4, pessoas: 1 };
  plan.requisitos["RES:E1"] = { ...plan.requisitos["RES:E1"], duracao: 8, pessoas: 1 };
  plan.blocos = dropActivity(plan, "RES:E1", plan.inicio, "A");
  const result = distributeBatch(plan, ["RES:PM1"], "A", plan.inicio, true);
  assert.match(result.mensagens[0], /espaço diário/);
  assert.equal(result.blocos.length, 1);
  assert.equal(dayLoad({ ...plan, blocos: result.blocos }, "A", plan.inicio), 8);
});

test("80% occupied Monday starts 20% of an 8h activity and continues 80% on Tuesday", () => {
  const plan = fixture();
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], duracao: 8, pessoas: 1 };
  plan.blocos = [{ id: "existing", ot: "RES:E1", dia: plan.inicio, inicio: 0, horas: 6.4, executantes: ["A"] }];
  for (const result of [
    scheduleSelectedDays(plan, "RES:PM1", [plan.fim, plan.inicio], ["A"]),
    distributeBatch(plan, ["RES:PM1"], "A", plan.inicio, true).blocos,
  ]) {
    const added = result.filter((b) => b.ot === "RES:PM1");
    assert.deepEqual(added.map((b) => [b.dia, b.horas]), [[plan.inicio, 1.6], [plan.fim, 6.4]]);
    assert.equal(dayLoad({ ...plan, blocos: result }, "A", plan.inicio), 8);
  }
});

test("manual scheduling uses selected crew count and fails atomically for insufficient days, absences and cross-week", () => {
  const plan = fixture();
  const before = structuredClone(plan);
  assert.throws(() => scheduleSelectedDays(plan, "RES:PM1", [plan.inicio], ["A"]), /Faltam 2 h/);
  assert.deepEqual(plan, before);
  const result = scheduleSelectedDays(plan, "RES:PM1", [plan.inicio, plan.fim], ["A"]);
  assert.deepEqual(result.map((b) => b.executantes), [["A"], ["A"]]);
  assert.equal(result.reduce((sum, b) => sum + b.horas, 0), 10);
  assert.throws(() => scheduleSelectedDays(plan, "RES:PM1", [plan.inicio, "2026-11-02"], ["A"]), /mesma semana/);
  plan.indisponibilidades.push({ executante: "A", dia: plan.fim, motivo: "Falta" });
  assert.throws(() => scheduleSelectedDays(plan, "RES:PM1", [plan.inicio, plan.fim], ["A"]), /indisponível/);
});

test("BMA finish constraint marks late days while target start remains a soft target", () => {
  const plan = fixture(), order = plan.ordens[0];
  order.dados = { targstartdate: "2026-10-27", targcompdate: "2026-10-29", sneconstraint: plan.inicio, fnlconstraint: "2026-10-28" };
  assert.deepEqual(proposedDays(order, [plan.inicio, plan.fim, "2026-10-28", "2026-10-29"]), [plan.inicio, plan.fim, "2026-10-28"]);
  assert.equal(isTargetDay(order, plan.inicio), false);
  assert.equal(isTargetDay(order, "2026-10-27"), true);
  assert.equal(isTargetDay(order, "2026-10-28"), false);
  assert.equal(isTargetDay(order, "2026-10-29"), false);
  assert.equal(activityDateStatus(order, "2026-10-27"), "target");
  assert.equal(activityDateStatus(order, "2026-10-28"), "window");
  assert.equal(activityDateStatus(order, "2026-10-29"), "late");
  assert.match(activityDateWarning(order, "2026-10-29"), /prazo de 28\/10\/2026 ultrapassado/);
  order.dados = { schedstart: `${plan.fim}T08:00:00-03:00` };
  assert.equal(isTargetDay(order, plan.fim), true);
  order.dados = { sneconstraint: "2026-10-27", fnlconstraint: "2026-10-28" };
  assert.deepEqual(proposedDays(order, [plan.inicio, plan.fim, "2026-10-28", "2026-10-29"]), [plan.fim, "2026-10-28"]);
  order.dados = {};
  assert.deepEqual(proposedDays(order, [plan.inicio, plan.fim]), [plan.inicio, plan.fim]);
});
test("gallery shows only PREPARED, WSCH and WFSCH BMA statuses", () => {
  for (const status of ["PREPARED", "WSCH", "WFSCH"]) assert.equal(isGalleryBmaStatus(status), true);
  for (const status of ["APPR", "INPRG", "COMP", "CLOSE", "CAN", ""]) assert.equal(isGalleryBmaStatus(status), false);
});

test("exact drop on unavailable date must not silently move to another cell", () => {
  const plan = fixture();
  plan.indisponibilidades.push({ executante: "A", dia: plan.inicio, motivo: "Falta" });
  const result = distributeBatch(plan, ["RES:PM1"], "A", plan.inicio, true);
  assert.equal(result.blocos.length, 0);
  assert.match(result.mensagens[0], /Nenhum outro dia/);
});

test("gallery types identify PM1/PM2/PM3 independently from specialty", () => {
  const make = (description, worktype = "S") => ({ dados: { description, worktype } });
  assert.equal(activityCategory(make("PM1 - teste")), "pm1");
  assert.equal(activityCategory(make(" pm2 teste")), "pm2");
  assert.equal(activityCategory(make("PM3 - teste")), "pm3");
  assert.equal(activityCategory(make("PM30 teste")), "outras-pm");
  assert.equal(activityCategory(make("PM3 teste", "E")), "corretiva");
});

function sequenceFixture() {
  const plan = fixture();
  for (const req of Object.values(plan.requisitos)) { req.duracao = 6; req.pessoas = 1; }
  plan.blocos = distributeBatch(plan, ["RES:PM1", "RES:E1"], "A", plan.inicio, true).blocos;
  return plan;
}

test("moving a continuation before the first card reschedules whole activities, preserving hours and crew", () => {
  const plan = sequenceFixture(), original = structuredClone(plan);
  const before = plan.blocos.find((b) => b.ot === "RES:PM1");
  const moving = plan.blocos.find((b) => b.ot === "RES:E1" && b.dia === plan.fim);
  const blocks = resequenceWeek(plan, moving.id, "A", "A", plan.inicio, before.id);
  assert.deepEqual(blocks.map((b) => [b.ot, b.dia, b.horas]), [
    ["RES:E1", plan.inicio, 6], ["RES:PM1", plan.inicio, 2], ["RES:PM1", plan.fim, 4],
  ]);
  assert.deepEqual(plan, original);
  assert.equal(planningMetrics({ ...plan, blocos: blocks }).pm, 6);
  assert.equal(planningMetrics({ ...plan, blocos: blocks }).corrective, 6);
  assert.ok(blocks.every((b) => b.executantes.join() === "A"));
  assert.equal(dayLoad({ ...plan, blocos: blocks }, "A", plan.inicio), 8);
});

test("sequence move to another specialty changes only source crew member and preserves other allocated work", () => {
  const plan = sequenceFixture();
  const moving = plan.blocos[0];
  const blocks = resequenceWeek(plan, moving.id, "A", "B", plan.inicio);
  assert.ok(blocks.filter((b) => b.ot === moving.ot).every((b) => b.executantes.join() === "B"));
  assert.equal(allocatedDuration({ ...plan, blocos: blocks }, moving.ot), 6);
  assert.equal(allocatedDuration({ ...plan, blocos: blocks }, "RES:E1"), 6);
  plan.pessoas.push({ id: "C", orgid: "BR", funcao: "OTHER", dias: [plan.inicio, plan.fim] });
  const crossSpecialtyBlocks = resequenceWeek(plan, moving.id, "A", "C", plan.inicio);
  assert.ok(crossSpecialtyBlocks.filter((b) => b.ot === moving.ot).every((b) => b.executantes.join() === "C"));
});

test("failed sequence changes preserve all original blocks for constraints, absences, full week and mixed crews", () => {
  const plan = sequenceFixture(), moving = plan.blocos[0], before = structuredClone(plan);
  assert.throws(() => resequenceWeek(plan, moving.id, "A", "A", "2026-11-02"), /mesma semana/);
  assert.deepEqual(plan, before);
  plan.indisponibilidades.push({ executante: "B", dia: plan.inicio, motivo: "Falta" },
    { executante: "B", dia: plan.fim, motivo: "Falta" });
  assert.throws(() => resequenceWeek(plan, moving.id, "A", "B", plan.inicio), /Nenhuma alocação/);
  plan.indisponibilidades = [];
  plan.ordens[0].dados.fnlconstraint = plan.inicio;
  const lateBlocks = resequenceWeek(plan, moving.id, "A", "A", plan.fim);
  assert.ok(lateBlocks.some((block) => block.ot === moving.ot && block.dia >= plan.fim));
  plan.ordens[0].dados.fnlconstraint = "";
  plan.blocos[2].executantes = ["B"];
  assert.throws(() => resequenceWeek(plan, moving.id, "A", "A", plan.inicio), /equipes diferentes/);
});

test("joint activities stay simultaneous when reordered and cannot collapse crew by moving onto a current member", () => {
  const plan = fixture();
  plan.blocos = distributeBatch(plan, ["RES:PM1", "RES:E1"], "A", plan.inicio, true).blocos;
  const moving = plan.blocos.find((b) => b.ot === "RES:E1");
  const blocks = resequenceWeek(plan, moving.id, "A", "A", plan.inicio, plan.blocos[0].id);
  assert.ok(blocks.every((b) => b.executantes.join() === "A,B"));
  assert.equal(allocatedDuration({ ...plan, blocos: blocks }, "RES:PM1"), 10);
  assert.equal(allocatedDuration({ ...plan, blocos: blocks }, "RES:E1"), 6);
  assert.throws(() => resequenceWeek(plan, moving.id, "A", "B", plan.inicio), /já integra/);
});

test("labor shortage offers available helpers across specialties and records weekly overtime", () => {
  const plan = fixture();
  plan.pessoas[1].funcao = "210";
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], duracao: 2, pessoas: 1 };
  plan.blocos = [{ id: "pm", ot: "RES:PM1", dia: plan.inicio, inicio: 0, horas: 2, executantes: ["A"] }];
  plan.blocos.push({ id: "busy-1", ot: "RES:E1", dia: plan.inicio, inicio: 0, horas: 8, executantes: ["B"] });
  plan.blocos.push({ id: "busy-2", ot: "RES:E1", dia: plan.fim, inicio: 0, horas: 8, executantes: ["B"] });
  const labor = [{ especialidade: "180", orgid: "BR", quantidade: 2, horas_normais: "2" }];
  const candidates = laborHelperCandidates(plan, "RES:PM1", labor);
  assert.deepEqual(candidates.map(({ person, overtimeMinimum }) => [person.id, overtimeMinimum]), [["B", 2]]);
  const updated = addLaborHelper(plan, "RES:PM1", "B", 2, labor);
  assert.deepEqual(updated.blocos[0].executantes, ["A", "B"]);
  assert.deepEqual(updated.horas_extras, [{ ot: "RES:PM1", executante: "B", dia: plan.inicio, horas: 2 }]);
  assert.equal(weeklyBalance(updated, "B", plan.inicio).remaining, 0);
  assert.equal(planningMetrics(updated).capacity, 34);
  assert.equal(specialtyWorkload(updated).reduce((sum, row) => sum + row.capacidade, 0), 34);
  const returned = returnOrderToPortfolio(updated, "RES:PM1");
  assert.equal(returned.blocos.some((block) => block.ot === "RES:PM1"), false);
  assert.equal(returned.horas_extras.length, 0);
  assert.equal(returned.requisitos["RES:PM1"].selecionada, false);
});

test("labor helper is excluded when absent on any OT date", () => {
  const plan = fixture();
  plan.requisitos["RES:PM1"] = { ...plan.requisitos["RES:PM1"], duracao: 2, pessoas: 1 };
  plan.blocos = [
    { id: "pm-1", ot: "RES:PM1", dia: plan.inicio, inicio: 0, horas: 1, executantes: ["A"] },
    { id: "pm-2", ot: "RES:PM1", dia: plan.fim, inicio: 0, horas: 1, executantes: ["A"] },
  ];
  plan.pessoas[1].dias = [plan.inicio];
  const labor = [{ especialidade: "180", orgid: "BR", quantidade: 2, horas_normais: "2" }];
  assert.deepEqual(laborHelperCandidates(plan, "RES:PM1", labor), []);
});
