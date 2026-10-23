const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const source = fs.readFileSync(path.join(__dirname, "..", "utils", "laborPlanning.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const moduleValue = { exports: {} };
new Function("module", "exports", compiled)(moduleValue, moduleValue.exports);
const { periodoValido, horasExecutante, configuracaoInicial, chaveExecutante, equipeDefinida, reutilizarEquipe, formatPlanningDate, parsePlanningDate, diasUteis, configurarDiasDisponiveis } = moduleValue.exports;
const member = (overrides = {}) => ({
  orgid: "BR", matricula: "TEST", funcao: "210", jornada: "adm",
  inicio_ciclo: null, ajuste_horas: 0, ...overrides,
});

test("explicit available dates always count six hours, independently of shift, rest or special day", () => {
  for (const jornada of ["adm", "equipe", "16-00"]) {
    const config = member({ capacidade: "dias_6h", jornada, equipe: 1,
      dias_disponiveis: ["2026-11-01", "2026-11-03", "2026-11-07"] });
    assert.deepEqual(horasExecutante("2026-11-01", "2026-11-08", config), { dias: 3, base: 18, horas: 18 });
    assert.equal(horasExecutante("2026-11-03", "2026-11-03", config).horas, 6);
    assert.equal(horasExecutante("2026-11-02", "2026-11-02", config).horas, 0);
    assert.equal(horasExecutante("2026-11-01", "2026-11-08", { ...config, dias_disponiveis: [] }).horas, 0);
    for (const change of [{ dias_disponiveis: null }, { ajuste_horas: 1 },
      { dias_disponiveis: ["2026-02-30"] }, { dias_disponiveis: ["2026-11-02", "2026-11-02"] }]) {
      assert.equal(horasExecutante("2026-11-01", "2026-11-08", { ...config, ...change }), null);
    }
  }
});

test("new drafts start weekdays; saved explicit days restore and new periods reset dates", () => {
  const start = "2026-11-01", end = "2026-11-08";
  assert.deepEqual(diasUteis(start, end), ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]);
  const draft = configurarDiasDisponiveis(member({ jornada: "", ajuste_horas: -3,
    ausencias: ["2026-11-02"], ajustes_datas: { "2026-11-03": 8 } }), start, end);
  assert.equal(draft.jornada, "adm");
  assert.equal(horasExecutante(start, end, draft).horas, 32);
  assert.equal(draft.ajuste_horas, 0);
  assert.deepEqual(draft.ajustes_datas, {});
  const explicit = { ...draft, dias_disponiveis: ["2026-11-01", "2026-11-07"] };
  const plan = { inicio: start, fim: end, setores: ["RES-TC-NF"], executantes: [explicit] };
  assert.deepEqual(reutilizarEquipe(plan, start, end)[0].dias_disponiveis, explicit.dias_disponiveis);
  assert.deepEqual(reutilizarEquipe(plan, "2026-11-09", "2026-11-15")[0].dias_disponiveis,
    ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]);
  assert.equal(configurarDiasDisponiveis({ ...explicit, dias_disponiveis: null }, start, end).dias_disponiveis.length, 5);
});

test("current drafts use eight hours for one marked day without adding previous adjustments", () => {
  const draft = configurarDiasDisponiveis(member({ ajuste_horas: 8 }), "2026-10-26", "2026-10-26");
  assert.equal(draft.capacidade, "dias_8h");
  assert.equal(horasExecutante("2026-10-26", "2026-10-26", draft).horas, 8);
  assert.equal(horasExecutante("2026-10-26", "2026-10-26", { ...draft, jornada: "equipe", equipe: 1 }).horas, 8);
  assert.equal(horasExecutante("2026-10-26", "2026-10-26", { ...draft, dias_disponiveis: [] }).horas, 0);
});

test("planning date fields always display dd/mm/yyyy and only emit valid ISO dates", () => {
  assert.equal(formatPlanningDate("2026-10-26"), "26/10/2026");
  assert.equal(parsePlanningDate("26/10/2026"), "2026-10-26");
  for (const value of ["10/26/2026", "31/02/2026", "1/2/2026", "", "26/10/26", "01/01/0000"]) {
    assert.equal(parsePlanningDate(value), "");
  }
  assert.equal(formatPlanningDate("2026-02-30"), "");
});

test("absences remove only scheduled work, override specials and do not double count rest", () => {
  assert.deepEqual(horasExecutante("2026-11-01", "2026-11-08",
    member({ ausencias: ["2026-11-02", "2026-11-08"] })), { dias: 4, base: 24, horas: 24 });
  assert.equal(horasExecutante("2026-11-01", "2026-11-08", member({
    jornada: "08-16", inicio_ciclo: "2026-11-01", ausencias: ["2026-11-02", "2026-11-07"],
  })).horas, 40);
  const calendar = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "database", "catalogos", "turnos-2026.json"), "utf8"));
  assert.equal(horasExecutante("2026-11-01", "2026-11-08", member({
    jornada: "equipe", equipe: 1, ajustes_datas: {}, ausencias: ["2026-11-03", "2026-11-05"],
  }), calendar).horas, 32);
  assert.equal(horasExecutante("2026-11-02", "2026-11-02", member({
    ausencias: ["2026-11-02", "2026-11-05"],
  })).horas, 0);
});

test("reuse preserves same-period absences but clears stale period adjustments", () => {
  const plan = {
    inicio: "2026-11-01", fim: "2026-11-08", setores: ["RES-TC-NF"],
    executantes: [member({ ausencias: ["2026-11-02"], ajustes_datas: { "2026-11-03": 6 }, ajuste_horas: -1 })],
  };
  assert.deepEqual(reutilizarEquipe(plan, plan.inicio, plan.fim), plan.executantes);
  const other = reutilizarEquipe(plan, "2026-11-09", "2026-11-13")[0];
  assert.deepEqual(other.ausencias, []);
  assert.deepEqual(other.ajustes_datas, {});
  assert.equal(other.ajuste_horas, 0);
  assert.equal(other.funcao, plan.executantes[0].funcao);
});

test("planning unlocks only for a nonempty saved team matching period and sectors", () => {
  const plan = { inicio: "2026-11-01", fim: "2026-11-08", setores: ["RES-TC-NF"], executantes: [member()] };
  const ready = (value, inicio = plan.inicio, fim = plan.fim, setores = plan.setores) =>
    equipeDefinida(value, inicio, fim, setores);
  assert.equal(ready(null), false);
  assert.equal(ready({ ...plan, executantes: [] }), false);
  assert.equal(ready(plan), true);
  assert.equal(ready(plan, "2026-11-02"), false);
  assert.equal(ready(plan, plan.inicio, "2026-11-09"), false);
  assert.equal(ready(plan, plan.inicio, plan.fim, ["RES-TC-NC"]), false);
  assert.equal(ready(plan, "", ""), false);
  assert.equal(ready(plan, plan.inicio, plan.fim, []), false);
  assert.equal(ready(plan, plan.inicio, plan.fim, ["res-tc-nf"]), true);
  assert.equal(ready({ ...plan, setores: ["RES-TC-NC", "RES-TC-NF"] },
    plan.inicio, plan.fim, ["RES-TC-NF", "RES-TC-NC"]), true);
});

test("valid inclusive dates, reversed ranges and calendar-invalid dates", () => {
  assert.equal(periodoValido("2026-11-01", "2026-11-01"), true);
  for (const [start, end] of [["", ""], ["2026-11-02", "2026-11-01"], ["2026-02-30", "2026-03-01"]]) {
    assert.equal(periodoValido(start, end), false);
  }
});
test("administrative six-hour weekday schedule and adjustments", () => {
  assert.deepEqual(horasExecutante("2026-11-01", "2026-11-08", member()), { dias: 5, base: 30, horas: 30 });
  assert.equal(horasExecutante("2026-11-01", "2026-11-01", member()).horas, 0);
  assert.equal(horasExecutante("2026-11-02", "2026-11-02", member()).horas, 6);
  assert.equal(horasExecutante("2026-11-01", "2026-11-08", member({ ajuste_horas: -6 })).horas, 24);
});
test("all three shifts use eight-hour six-on two-off cycles including weekends", () => {
  for (const jornada of ["08-16", "16-00", "00-08"]) {
    const person = member({ jornada, inicio_ciclo: "2026-11-01" });
    assert.equal(horasExecutante("2026-11-01", "2026-11-08", person).horas, 48);
    assert.equal(horasExecutante("2026-11-07", "2026-11-08", person).horas, 0);
    assert.equal(horasExecutante("2026-10-31", "2026-10-31", person).horas, 0);
  }
});
test("all phases and month/year transitions match day-by-day counting", () => {
  const cycle = Date.parse("2026-11-01T00:00:00Z");
  const day = 86400000;
  for (let offset = -10; offset <= 10; offset++) {
    for (const length of [1, 2, 6, 7, 8, 9, 31, 366]) {
      const start = cycle + offset * day;
      const end = start + (length - 1) * day;
      const format = (value) => new Date(value).toISOString().slice(0, 10);
      let admin = 0, shift = 0;
      for (let i = 0; i < length; i++) {
        const weekday = new Date(start + i * day).getUTCDay();
        if (weekday !== 0 && weekday !== 6) admin++;
        if (((offset + i) % 8 + 8) % 8 < 6) shift++;
      }
      assert.equal(horasExecutante(format(start), format(end), member()).dias, admin);
      assert.equal(horasExecutante(format(start), format(end),
        member({ jornada: "08-16", inicio_ciclo: "2026-11-01" })).dias, shift);
    }
  }
});
test("incomplete or invalid configurations do not produce success-shaped zero hours", () => {
  for (const change of [
    { jornada: "" }, { funcao: "" }, { jornada: "08-16" },
    { jornada: "08-16", inicio_ciclo: "2026-02-30" },
    { ajuste_horas: NaN }, { ajuste_horas: -31 },
  ]) {
    assert.equal(horasExecutante("2026-11-01", "2026-11-08", member(change)), null);
  }
});
test("primary function preferred, ambiguous functions and journey require user input", () => {
  const person = { orgid: "BR", matricula: "TEST", especialidades: [
    { codigo: "210", principal: false }, { codigo: "300", principal: true },
  ] };
  assert.equal(configuracaoInicial(person).funcao, "300");
  assert.equal(configuracaoInicial(person).jornada, "");
  assert.equal(configuracaoInicial({ ...person, especialidades: person.especialidades.map(c => ({ ...c, principal: false })) }).funcao, "");
  assert.notEqual(chaveExecutante(person), chaveExecutante({ ...person, orgid: "US" }));
});

test("official team rotation, holidays and manual exceptions", () => {
  const calendar = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "database", "catalogos", "turnos-2026.json"), "utf8"));
  const team = member({ jornada: "equipe", equipe: 1 });
  assert.equal(Object.keys(calendar.dias).length, 365);
  assert.equal(calendar.dias["2026-11-03"]["1"].turno, "B");
  assert.equal(calendar.dias["2026-11-11"]["1"].turno, "A");
  assert.equal(calendar.dias["2026-11-19"]["1"].turno, "C");
  assert.equal(horasExecutante("2026-11-01", "2026-11-08", team, calendar), null);
  assert.equal(horasExecutante("2026-11-01", "2026-11-08",
    { ...team, ajustes_datas: { "2026-11-03": 6, "2026-11-05": 7 } }, calendar).horas, 45);
  assert.equal(horasExecutante("2026-12-25", "2026-12-25", team, calendar), null);
  assert.equal(horasExecutante("2026-12-25", "2026-12-25",
    { ...team, ajustes_datas: { "2026-12-25": 0 } }, calendar).horas, 0);
  assert.equal(horasExecutante("2027-01-01", "2027-01-01", team, calendar), null);
});
