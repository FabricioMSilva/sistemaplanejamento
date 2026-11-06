const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const ts = require("typescript");

const file = path.join(__dirname, "../pages/api/desktop/[...path].ts");
const compiled = ts.transpileModule(fs.readFileSync(file, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true },
}).outputText;
const loaded = { exports: {} };
new Function("require", "module", "exports", compiled)(require, loaded, loaded.exports);
const proxy = loaded.exports.default;

test("desktop proxy streams JSON, queries, uploads and files but rejects untrusted origins", async () => {
  const saved = { token: process.env.BMA_DESKTOP_TOKEN, backend: process.env.BMA_BACKEND_PORT, port: process.env.PORT };
  const requests = [];
  const backend = http.createServer((request, response) => {
    let body = "";
    request.on("data", (part) => { body += part; });
    request.on("end", () => {
      requests.push({ url: request.url, token: request.headers["x-planning-token"], body });
      response.setHeader("content-type", "application/json");
      response.setHeader("content-disposition", 'attachment; filename="check.json"');
      response.end(JSON.stringify({ ok: true, body }));
    });
  });
  const frontend = http.createServer((request, response) => {
    response.status = (status) => { response.statusCode = status; return response; };
    response.json = (value) => { response.setHeader("content-type", "application/json"); response.end(JSON.stringify(value)); };
    const url = new URL(request.url, "http://localhost");
    request.query = { path: url.pathname.replace("/api/desktop/", "").split("/") };
    proxy(request, response);
  });
  try {
    await new Promise((resolve) => backend.listen(0, "127.0.0.1", resolve));
    await new Promise((resolve) => frontend.listen(0, "127.0.0.1", resolve));
    process.env.BMA_DESKTOP_TOKEN = "test-nonce";
    process.env.BMA_BACKEND_PORT = String(backend.address().port);
    process.env.PORT = String(frontend.address().port);
    const base = `http://127.0.0.1:${frontend.address().port}`;
    const response = await fetch(`${base}/api/desktop/api/pcm/planos?setor=RES-TC-NF`);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("content-disposition"), 'attachment; filename="check.json"');
    assert.deepEqual(await response.json(), { ok: true, body: "" });
    assert.equal(requests[0].url, "/api/pcm/planos?setor=RES-TC-NF");
    assert.equal(requests[0].token, "test-nonce");
    const upload = await fetch(`${base}/api/desktop/api/processar`, {
      method: "POST", headers: { "content-type": "application/octet-stream", origin: base }, body: "uploaded bytes",
    });
    assert.equal((await upload.json()).body, "uploaded bytes");
    for (const headers of [{ origin: "https://untrusted.invalid" }, { "sec-fetch-site": "cross-site" }]) {
      const denied = await fetch(`${base}/api/desktop/api/pcm/planos`, { headers });
      assert.equal(denied.status, 403, JSON.stringify(headers));
      await denied.text();
    }
    const invalidHost = await new Promise((resolve, reject) => {
      http.get(`${base}/api/desktop/api/pcm/planos`, { headers: { host: "untrusted.invalid" } }, (response) => {
        response.resume();
        response.on("end", () => resolve(response.statusCode));
      }).on("error", reject);
    });
    assert.equal(invalidHost, 403);
    const invalid = await fetch(`${base}/api/desktop/not-api/private`);
    assert.equal(invalid.status, 400);
    await invalid.text();
    assert.equal(requests.length, 2);
    delete process.env.BMA_DESKTOP_TOKEN;
    const disabled = await fetch(`${base}/api/desktop/api/pcm/planos`);
    assert.equal(disabled.status, 404);
    await disabled.text();
  } finally {
    for (const [key, value] of Object.entries({ BMA_DESKTOP_TOKEN: saved.token, BMA_BACKEND_PORT: saved.backend, PORT: saved.port })) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    backend.closeAllConnections();
    frontend.closeAllConnections();
    await Promise.all([backend, frontend].map((server) => new Promise((resolve) => server.close(resolve))));
  }
});

test("installer is strictly per-user and does not request elevation", () => {
  const installer = fs.readFileSync(path.join(__dirname, "../../distribution/windows/installer.iss"), "utf8");
  assert.match(installer, /^PrivilegesRequired=lowest$/m);
  assert.match(installer, /^DefaultDirName=\{localappdata\}/m);
  assert.doesNotMatch(installer, /PrivilegesRequiredOverridesAllowed|runas|\{common|HKLM|\{pf/i);
});

test("updates keep installation identity, protect user data and reject older releases", () => {
  const installer = fs.readFileSync(path.join(__dirname, "../../distribution/windows/installer.iss"), "utf8");
  assert.match(installer, /^AppId=\{\{75337384-744F-48DD-A84C-880A41DF5A2A\}$/m);
  assert.match(installer, /^UsePreviousAppDir=yes$/m);
  assert.match(installer, /^UsePreviousTasks=yes$/m);
  assert.match(installer, /^CloseApplications=no$/m);
  assert.match(installer, /^AppMutex=Local\\Michelin\.PlanningScheduling$/m);
  assert.match(installer, /ComparePackedVersion\(InstalledPacked, SetupPacked\) > 0/);
  const cleanup = installer.split("[InstallDelete]")[1].split("[Files]")[0];
  assert.doesNotMatch(cleanup, /localappdata|database|uploads|FirefoxProfile|logs|\{app\}\\\*/i);
  const directories = [...cleanup.matchAll(/Name: "\{app\}\\([^"]+)"/g)].map((match) => match[1]);
  assert.deepEqual(directories, ["_internal", "frontend", "runtime", "browser", "licenses"]);
});