const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const cache = new Map();
function load(name) {
  const file = path.join(__dirname, "..", "utils", `${name}.ts`);
  if (cache.has(file)) return cache.get(file);
  const js = ts.transpileModule(fs.readFileSync(file, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const m = { exports: {} };
  new Function("require", "module", "exports", js)((request) => {
    if (request.startsWith("@/utils/")) return load(request.split("/").pop());
    throw Error(`Unexpected runtime dependency: ${request}`);
  }, m, m.exports);
  cache.set(file, m.exports);
  return m.exports;
}
const { buildDashboard, daysBetween, localDate, numericField, orderInPeriod } = load("pcmDashboard");
const { cellText, hasExistingPlanningInfo } = load("orderFilters");
function order(wonum, dados = {}, status = "PREPARED") {
  return { wonum, siteid: "RES", status, maintenanceshop: "RES-TC-NF", sincronizado_em: "2026-10-22T19:00:00Z", dados: { lead: "", ...dados } };
}
const member = { orgid: "BR", matricula: "TEST", funcao: "180", jornada: "adm", inicio_ciclo: null, ajuste_horas: 0 };
const plan = { setores: ["RES-TC-NF"], inicio: "2026-11-02", fim: "2026-11-06", executantes: [member] };
const labor = { total: 4, profissionais: [{ orgid: "BR", matricula: "TEST", especialidades: [{ codigo: "180", descricao: "Mecanico" }] }] };

test("SQL planning status wins and legacy orders remain unverified", () => {
  const legacy = order("LEGACY");
  delete legacy.dados.lead;
  assert.equal(cellText(legacy, "planning_status"), "Não verificada");
  assert.equal(hasExistingPlanningInfo(legacy), true);

  const freshlyCollected = order("FRESH");
  assert.equal(cellText(freshlyCollected, "planning_status"), "Não planejada");
  assert.equal(hasExistingPlanningInfo(freshlyCollected), false);

  assert.equal(cellText({ ...freshlyCollected, planning_status: "Parcial" }, "planning_status"), "Parcial");
});

test("missing estimates remain unknown, zero is a valid estimate, no fake criticality", () => {
  assert.equal(numericField(order("1"), "estlabhrs"), null);
  assert.equal(numericField(order("1", { estlabhrs: 0 }), "estlabhrs"), 0);
  assert.equal(numericField(order("1", { estlabhrs: -2 }), "estlabhrs"), null);
  const data = buildDashboard([order("1", { estlabhrs: 10 }), order("2")], plan, labor, null);
  assert.equal(data.neededHours, 10);
  assert.equal(data.missingHours, 1);
  assert.equal(data.backlogDays, null);
});
test("capacity and executive metrics use saved personnel, function and inclusive dates", () => {
  const data = buildDashboard([order("1", { estlabhrs: 60 })], plan, labor, null);
  assert.equal(data.availableHours, 30);
  assert.equal(data.availability, 25);
  assert.equal(data.backlogDays, 10);
  assert.equal(data.disciplines[0].hours, 30);
  assert.equal(data.daily.length, 5);
  assert.ok(data.daily.every(row => row.capacity === 6));
});
test("absences update both total capacity and the exact calendar day", () => {
  const absent = { ...plan, executantes: [{ ...member, ausencias: ["2026-11-04"] }] };
  const data = buildDashboard([], absent, labor, null);
  assert.equal(data.availableHours, 24);
  assert.equal(data.daily.find(row => row.date === "2026-11-04").capacity, 0);
  assert.equal(data.daily.find(row => row.date === "2026-11-05").capacity, 6);
  assert.equal(data.daily.reduce((sum, row) => sum + row.capacity, 0), 24);
});
test("six-hour selected dates feed executive total and daily capacity, not the shift calendar", () => {
  const selected = { ...plan, inicio: "2026-11-01", fim: "2026-11-08", executantes: [{
    ...member, jornada: "equipe", equipe: 1, capacidade: "dias_6h",
    dias_disponiveis: ["2026-11-01", "2026-11-03", "2026-11-07"],
  }] };
  const data = buildDashboard([], selected, labor, null);
  assert.equal(data.availableHours, 18);
  assert.equal(data.daily.find(row => row.date === "2026-11-01").capacity, 6);
  assert.equal(data.daily.find(row => row.date === "2026-11-02").capacity, 0);
  assert.equal(data.daily.reduce((sum, row) => sum + row.capacity, 0), 18);
  assert.equal(data.disciplines[0].hours, 18);
});
test("period portfolio includes target or scheduled dates inside and intervals crossing the horizon", () => {
  const range = { inicio: "2026-11-02", fim: "2026-11-06" };
  const rows = [
    order("target-start", { targstartdate: "2026-11-01T00:00:00-03:00", targcompdate: "2026-11-03T00:00:00-03:00", estlabhrs: 3 }),
    order("target-end-only", { targstartdate: "2026-11-09", targcompdate: "2026-11-06", estlabhrs: 4 }),
    order("scheduled-start", { schedstart: "2026-11-04T12:00:00Z", estlabhrs: 5 }),
    order("scheduled-end-only", { schedfinish: "2026-11-02", estlabhrs: 6 }),
    order("crosses-entire-period", { schedstart: "2026-10-30", schedfinish: "2026-11-10", estlabhrs: 7 }),
    order("outside", { targstartdate: "2026-11-07", targcompdate: "2026-11-08", schedstart: "2026-11-07", schedfinish: "2026-11-08", estlabhrs: 100 }),
    order("no-dates", { estlabhrs: 200 }),
    order("invalid-range", { targstartdate: "2026-11-05", targcompdate: "2026-11-01", schedstart: "2026-11-09", schedfinish: "2026-11-01" }),
    order("closed", { targstartdate: "2026-11-03", estlabhrs: 500 }, "CLOSE"),
  ];
  assert.deepEqual(rows.map(row => orderInPeriod(row, range.inicio, range.fim)),
    [true, true, true, true, true, false, false, true, true]);
  const data = buildDashboard(rows, null, null, null, range, true);
  assert.equal(data.sectorPending.length, 8);
  assert.equal(data.pending.length, 6);
  assert.equal(data.neededHours, 25);
  assert.equal(data.pm.count + data.corrective.count, 0);
  assert.equal(buildDashboard(rows, null, null, null).pending.length, 8);
  const noPeriod = buildDashboard(rows, null, null, null, null, true);
  assert.equal(noPeriod.pending.length, 0);
  assert.equal(noPeriod.periodFilterActive, false);
});
test("missing or no-longer-active personnel prevent reporting a confirmed capacity", () => {
  assert.equal(buildDashboard([], null, labor, null).availableHours, null);
  assert.equal(buildDashboard([], plan, { total: 0, profissionais: [] }, null).availableHours, null);
  assert.equal(buildDashboard([], { ...plan, executantes: [] }, labor, null).availableHours, null);
  assert.equal(buildDashboard([], plan, { ...labor, verificacao_nf: { necessaria: true, verificada: false } }, null).availableHours, null);
});
test("portfolio excludes terminal statuses and counts unique equipment", () => {
  const data = buildDashboard([
    order("1", { worktype: "S", description: "PM3 manutenção", assetnum: "PUMP", estlabhrs: 3 }),
    order("2", { worktype: "I", description: " PM2 qualidade ", assetnum: "PUMP", estlabhrs: 4 }),
    order("3", { worktype: "E", estlabhrs: 2 }),
    order("4", { worktype: "S", estlabhrs: 90 }, "CLOSE"),
  ], plan, labor, null);
  assert.equal(data.pending.length, 3);
  assert.equal(data.pm.count, 2);
  assert.equal(data.pm.hours, 7);
  assert.equal(data.pm.assets, 1);
  assert.equal(data.corrective.hours, 2);
  assert.equal(data.corrective.missingAssets, 1);
});
test("preventive PM table only accepts I/S orders whose description starts with PM", () => {
  const rows = [
    order("PM1", { worktype: "I", description: "PM1 ordem de segurança", targstartdate: "2026-11-03", estlabhrs: 2 }),
    order("PM2", { worktype: "S", description: " PM2 ordem de qualidade", targstartdate: "2026-11-03", estlabhrs: 3 }),
    order("PM3", { worktype: "I", description: "pM3 manutenção", targstartdate: "2026-11-03", estlabhrs: 5 }),
    order("NO-PM", { worktype: "S", description: "Inspeção preventiva", targstartdate: "2026-11-03", estlabhrs: 100 }),
    order("PREFIX-NOT", { worktype: "I", description: "Rotina PM3 manutenção", targstartdate: "2026-11-03", estlabhrs: 200 }),
    order("PM-LEAD", { worktype: "I", description: "PM1 planejada", targstartdate: "2026-11-03", lead: "B114376", estlabhrs: 8 }),
    order("PM-SCHEDULED", { worktype: "S", description: "PM2 planejada", targstartdate: "2026-11-03", schedstart: "2026-11-03T08:00:00-03:00", estlabhrs: 10 }),
    order("PM-FULL", { worktype: "I", description: "PM3 planejada", targstartdate: "2026-11-03", lead: "B114376", schedstart: "2026-11-03T08:00:00-03:00", estlabhrs: 12 }),
    order("E-PM", { worktype: "E", description: "PM3 manutenção corretiva", targstartdate: "2026-11-03", estlabhrs: 7 }),
  ];
  const data = buildDashboard(rows, null, null, null, { inicio: "2026-11-02", fim: "2026-11-06" }, true);
  assert.deepEqual(data.pm.rows.map((row) => row.wonum), ["PM1", "PM2", "PM3"]);
  assert.equal(data.pm.count, 3);
  assert.equal(data.pm.hours, 10);
  assert.equal(data.pmExcluded, 2);
  assert.equal(data.pmAlreadyPlannedExcluded, 3);
  assert.deepEqual(data.pmAllRows.map((row) => cellText(row, "planning_status")), [
    "Não planejada", "Não planejada", "Não planejada", "Parcial", "Parcial", "Planejada",
  ]);
  assert.deepEqual(data.corrective.rows.map((row) => row.wonum), ["E-PM"]);
});
test("corrective backlog is not restricted by target or scheduled dates", () => {
  const data = buildDashboard([
    order("E-no-date", { worktype: "E", estlabhrs: 2 }),
    order("E-future", { worktype: "E", targstartdate: "2027-01-01", estlabhrs: 3 }),
    order("PM-outside", { worktype: "S", description: "PM3 atividade", targstartdate: "2027-01-01", estlabhrs: 10 }),
    order("E-closed", { worktype: "E", estlabhrs: 30 }, "CLOSE"),
  ], null, null, null, { inicio: "2026-10-26", fim: "2026-10-30" }, true);
  assert.deepEqual(data.corrective.rows.map(o => o.wonum), ["E-no-date", "E-future"]);
  assert.equal(data.pm.count, 0);
  assert.equal(data.neededHours, 5);
  assert.equal(data.pending.length, 2);
});
test("daily load only uses scheduled starts, not targets; timezone is Brasilia", () => {
  assert.equal(localDate("2026-11-03T01:00:00Z"), "2026-11-02");
  const data = buildDashboard([
    order("1", { schedstart: "2026-11-03T01:00:00Z", schedfinish: "2026-11-04T14:00:00Z", estlabhrs: 8 }),
    order("2", { targstartdate: "2026-11-02T10:00:00-03:00", estlabhrs: 10 }),
    order("3", { schedstart: "2026-11-03T10:00:00Z", schedfinish: "2026-11-01T10:00:00Z", estlabhrs: 2 }),
  ], plan, labor, null);
  assert.equal(data.daily[0].demand, 8);
  assert.equal(data.gantt.length, 1);
  assert.equal(data.daily[0].orders, 1);
});
test("global adjustments count in total but are not silently spread across days", () => {
  const data = buildDashboard([], { ...plan, executantes: [{ ...member, ajuste_horas: -6 }] }, labor, null);
  assert.equal(data.availableHours, 24);
  assert.equal(data.adjustments, -6);
  assert.equal(data.daily.reduce((sum, row) => sum + row.capacity, 0), 30);
});
test("official calendar exceptions cannot become zero capacity by default", () => {
  const calendar = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "database", "catalogos", "turnos-2026.json"), "utf8"));
  const shifted = { ...plan, inicio: "2026-11-01", fim: "2026-11-08", executantes: [{ ...member, jornada: "equipe", equipe: 1, ajustes_datas: {} }] };
  assert.equal(buildDashboard([], shifted, labor, calendar).availableHours, null);
  shifted.executantes[0].ajustes_datas = { "2026-11-03": 6, "2026-11-05": 7 };
  assert.equal(buildDashboard([], shifted, labor, calendar).availableHours, 45);
  assert.equal(daysBetween("2026-12-31", "2027-01-01").length, 2);
});
