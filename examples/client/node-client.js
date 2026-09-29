#!/usr/bin/env node
/* Minimal Node.js (>= 18, built-in fetch) example: create a PDF and an XML from a JSON file.
 *
 *   node examples/client/node-client.js tests/fixtures/sample_request.json
 *
 * Environment: API_URL (default http://localhost:8090), API_KEY (default dev-key-change-me)
 */
const fs = require("node:fs");
const path = require("node:path");

const API_URL = (process.env.API_URL || "http://localhost:8090").replace(/\/$/, "");
const API_KEY = process.env.API_KEY || "dev-key-change-me";

async function call(endpoint, body) {
  const res = await fetch(`${API_URL}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${endpoint} -> HTTP ${res.status}: ${await res.text()}`);
  return res;
}

async function main() {
  const file = process.argv[2] || path.join(__dirname, "..", "..", "tests", "fixtures", "sample_request.json");
  const body = JSON.parse(fs.readFileSync(file, "utf8"));

  // Optional: attach a logo file given as third argument
  if (process.argv[3]) {
    const logoPath = process.argv[3];
    const ext = path.extname(logoPath).toLowerCase();
    const type = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml" }[ext];
    body.seller.logo = { media_type: type, data_base64: fs.readFileSync(logoPath).toString("base64") };
    delete body.seller.logo_url;
  }

  const outDir = path.join(process.cwd(), "out");
  fs.mkdirSync(outDir, { recursive: true });
  const name = body.invoice.number.replace(/[^A-Za-z0-9._-]+/g, "_");

  const totals = await (await call("/v1/invoices/totals", body)).json();
  console.log("totals:", totals.line_total, "net,", totals.tax_total, "VAT,", totals.grand_total, totals.currency, "gross");

  const xml = Buffer.from(await (await call("/v1/invoices/xml", body)).arrayBuffer());
  fs.writeFileSync(path.join(outDir, `${name}.xml`), xml);
  console.log("wrote", path.join(outDir, `${name}.xml`), xml.length, "bytes");

  const pdf = Buffer.from(await (await call("/v1/invoices/pdf", body)).arrayBuffer());
  fs.writeFileSync(path.join(outDir, `${name}.pdf`), pdf);
  console.log("wrote", path.join(outDir, `${name}.pdf`), pdf.length, "bytes");
}

main().catch((e) => { console.error(e.message); process.exit(1); });
