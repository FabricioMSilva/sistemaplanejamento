import type { NextApiRequest, NextApiResponse } from "next";
import http from "node:http";

export const config = { api: { bodyParser: false, responseLimit: false } };

export default function desktopProxy(request: NextApiRequest, response: NextApiResponse) {
  const token = process.env.BMA_DESKTOP_TOKEN;
  const port = process.env.BMA_BACKEND_PORT;
  const host = `127.0.0.1:${process.env.PORT}`;
  if (!token || !port) {
    response.status(404).end();
    return;
  }
  if (request.headers.host !== host || request.headers["sec-fetch-site"] === "cross-site"
    || (request.headers.origin && request.headers.origin !== `http://${host}`)) {
    response.status(403).json({ detail: "Origem nao autorizada." });
    return;
  }
  const path = request.query.path;
  if (!Array.isArray(path) || path[0] !== "api" || path.some((part) => !/^[a-zA-Z0-9_-]+$/.test(part))) {
    response.status(400).end();
    return;
  }
  const headers: http.OutgoingHttpHeaders = { "x-planning-token": token };
  for (const name of ["content-type", "content-length", "accept"]) {
    if (request.headers[name]) headers[name] = request.headers[name];
  }
  const query = request.url?.includes("?") ? request.url.slice(request.url.indexOf("?")) : "";
  const upstream = http.request({
    hostname: "127.0.0.1", port: Number(port), path: `/${path.join("/")}${query}`,
    method: request.method, headers, timeout: 15 * 60 * 1000,
  }, (result) => {
    response.statusCode = result.statusCode ?? 502;
    for (const name of ["content-type", "content-disposition", "cache-control"]) {
      if (result.headers[name]) response.setHeader(name, result.headers[name]);
    }
    result.on("error", () => response.destroy());
    result.pipe(response);
  });
  upstream.on("timeout", () => upstream.destroy(new Error("Backend timeout")));
  upstream.on("error", () => {
    if (!response.headersSent) response.status(502).json({ detail: "Servico local indisponivel. Reabra o Planning & Scheduling." });
    else response.destroy();
  });
  response.on("close", () => { if (!response.writableFinished) upstream.destroy(); });
  request.pipe(upstream);
}