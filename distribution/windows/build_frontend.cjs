const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "../..");
const build = process.argv[2] ? path.resolve(process.argv[2]) : path.join(root, "build/windows");
const mode = process.argv[3] || "static";
if (!new Set(["static", "standalone"]).has(mode)) throw new Error(`Unknown frontend build mode: ${mode}`);
const frontend = path.join(build, "frontend-source");
const destination = path.join(build, "payload/frontend");
fs.mkdirSync(frontend, { recursive: true });
for (const name of fs.readdirSync(frontend)) {
  if (name !== "node_modules") fs.rmSync(path.join(frontend, name), { recursive: true, force: true });
}
for (const name of ["components", "config", "data", "lib", "pages", "providers", "public", "services", "styles", "utils",
  "next.config.ts", "next-env.d.ts", "package.json", "package-lock.json", "postcss.config.js", "tailwind.config.ts",
  "tsconfig.json", "tsconfig.desktop.json"]) {
  const source = path.join(root, "frontend", name);
  if (fs.existsSync(source)) fs.cpSync(source, path.join(frontend, name), { recursive: true });
}
const environment = { ...process.env, BMA_DESKTOP_BUILD: "1", BMA_DESKTOP_OUTPUT: mode,
  NEXT_TELEMETRY_DISABLED: "1", NODE_USE_SYSTEM_CA: "1" };
environment.PATH = `${path.dirname(process.execPath)};${process.env.PATH || ""}`;
if (mode === "static") fs.rmSync(path.join(frontend, "pages/api"), { recursive: true, force: true });
for (const command of ["npm.cmd ci --include=dev --no-audit --no-fund", "npm.cmd run build"]) {
  const result = spawnSync(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", command], {
    cwd: frontend, env: environment, stdio: "inherit", windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}
const exported = path.join(frontend, ".next-desktop");
fs.rmSync(destination, { recursive: true, force: true });
if (mode === "standalone") {
  const standalone = path.join(exported, "standalone");
  if (!fs.existsSync(path.join(standalone, "server.js"))) throw new Error("Next standalone server was not produced");
  fs.cpSync(standalone, destination, { recursive: true, dereference: true });
  fs.cpSync(path.join(exported, "static"), path.join(destination, ".next-desktop/static"), { recursive: true, dereference: true });
  fs.cpSync(path.join(frontend, "public"), path.join(destination, "public"), { recursive: true, dereference: true });
} else {
  if (!fs.existsSync(path.join(exported, "planejamento/index.html"))) throw new Error("Next static interface was not produced");
  fs.cpSync(exported, destination, { recursive: true, dereference: true });
}
const forbidden = [];
function inspect(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) inspect(target);
    else if (entry.name.startsWith(".env")) forbidden.push(target);
  }
}
inspect(destination);
if (forbidden.length) throw new Error(`Environment files in frontend payload: ${forbidden.join(", ")}`);
console.log(`${mode === "static" ? "Static" : "Standalone"} desktop frontend ready: ${destination}`);