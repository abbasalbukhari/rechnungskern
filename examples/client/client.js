/* Plain JavaScript client for the E-Rechnung service (no build step, no framework).
 *
 * Shows how an external application calls the API:
 *   POST {API}/v1/invoices/totals  -> JSON with computed amounts
 *   POST {API}/v1/invoices/html    -> HTML preview
 *   POST {API}/v1/invoices/xml     -> XRechnung / Factur-X XML (download)
 *   POST {API}/v1/invoices/pdf     -> hybrid PDF/A-3 (download)
 *   POST {API}/v1/validate         -> Mustang validation report (multipart upload)
 * Every call sends the header  X-API-Key.
 */

const $ = (id) => document.getElementById(id);

// Default API URL: same origin when served from the service (/client/), else localhost.
$("apiUrl").value = location.origin.startsWith("http") ? location.origin : "http://localhost:8090";

const today = new Date();
const plus30 = new Date(today.getTime() + 30 * 86400000);
const iso = (d) => d.toISOString().slice(0, 10);
$("issueDate").value = iso(today);
$("dueDate").value = iso(plus30);
$("deliveryDate").value = iso(today);

let logoPayload = null; // { media_type, data_base64 }

$("logoFile").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  if (!file) { logoPayload = null; return; }
  const buf = await file.arrayBuffer();
  let binary = "";
  new Uint8Array(buf).forEach((b) => (binary += String.fromCharCode(b)));
  logoPayload = { media_type: file.type, data_base64: btoa(binary) };
  setStatus(`Logo geladen: ${file.name} (${Math.round(file.size / 1024)} KB)`, true);
});

// ---------- item rows ----------
const itemsEl = $("items");

function addItemRow(item = {}) {
  const row = document.createElement("div");
  row.className = "row3";
  row.innerHTML = `
    <input class="i-name" placeholder="Bezeichnung" value="${item.name ?? ""}">
    <input class="i-qty" type="number" step="0.0001" value="${item.quantity ?? 1}">
    <select class="i-unit">
      <option value="C62">Stück</option><option value="HUR">Stunde</option><option value="DAY">Tag</option>
      <option value="KGM">kg</option><option value="MTR">m</option><option value="LS">Pauschale</option>
    </select>
    <input class="i-price" type="number" step="0.01" value="${item.unit_price ?? "0.00"}">
    <select class="i-vat"><option value="19">19</option><option value="7">7</option><option value="0">0</option></select>
    <input class="i-disc" type="number" step="0.01" placeholder="0" value="${item.discount ?? ""}">
  `;
  row.querySelector(".i-unit").value = item.unit ?? "C62";
  row.querySelector(".i-vat").value = item.tax_rate ?? "19";
  const del = document.createElement("button");
  del.type = "button"; del.className = "secondary small"; del.textContent = "×";
  del.onclick = () => row.remove();
  row.appendChild(del);
  itemsEl.appendChild(row);
}

$("addItem").onclick = () => addItemRow();
addItemRow({ name: "Beratung Digitalisierung", quantity: 8, unit: "HUR", unit_price: "120.00", tax_rate: "19" });
addItemRow({ name: "Software-Lizenz Pro", quantity: 2, unit: "C62", unit_price: "450.00", tax_rate: "19", discount: 10 });
addItemRow({ name: "Fachbuch E-Rechnung", quantity: 3, unit: "C62", unit_price: "39.90", tax_rate: "7" });

// ---------- build request body ----------
function buildRequest() {
  const items = [...itemsEl.querySelectorAll(".row3")].map((row) => {
    const rate = row.querySelector(".i-vat").value;
    const item = {
      name: row.querySelector(".i-name").value,
      quantity: row.querySelector(".i-qty").value,
      unit: row.querySelector(".i-unit").value,
      unit_price: Number(row.querySelector(".i-price").value).toFixed(2),
      tax_rate: rate,
      tax_category: rate === "0" ? "Z" : "S",
    };
    const disc = row.querySelector(".i-disc").value;
    if (disc && Number(disc) > 0) item.allowances = [{ percent: disc, reason: "Rabatt" }];
    return item;
  });

  const footerCols = $("footerText").value.split("|").map((s) => s.trim()).filter(Boolean).slice(0, 3);
  const profile = $("profile").value;

  const body = {
    profile,
    language: $("language").value,
    invoice: {
      number: $("number").value,
      type_code: "380",
      issue_date: $("issueDate").value,
      due_date: $("dueDate").value || undefined,
      delivery_date: $("deliveryDate").value || undefined,
      currency: "EUR",
      buyer_reference: $("buyerReference").value || undefined,
      order_reference: $("orderReference").value || undefined,
      notes: $("noteText").value ? [{ text: $("noteText").value }] : [],
    },
    seller: {
      name: $("sellerName").value,
      address: { line1: $("sellerStreet").value, postcode: $("sellerZip").value, city: $("sellerCity").value, country: "DE" },
      vat_id: $("sellerVat").value || undefined,
      contact: {
        name: $("sellerContactName").value || undefined,
        phone: $("sellerContactPhone").value || undefined,
        email: $("sellerContactEmail").value || undefined,
      },
      electronic_address: $("sellerContactEmail").value ? { scheme: "EM", id: $("sellerContactEmail").value } : undefined,
      bank: $("sellerIban").value ? { iban: $("sellerIban").value, bic: $("sellerBic").value || undefined, account_holder: $("sellerName").value } : undefined,
      logo: logoPayload || undefined,
    },
    buyer: {
      name: $("buyerName").value,
      customer_id: $("buyerCustomerId").value || undefined,
      address: { line1: $("buyerStreet").value, postcode: $("buyerZip").value, city: $("buyerCity").value, country: "DE" },
      vat_id: $("buyerVat").value || undefined,
      electronic_address: $("buyerEmail").value
        ? { scheme: profile === "XRECHNUNG" && $("buyerReference").value ? "0204" : "EM", id: profile === "XRECHNUNG" && $("buyerReference").value ? $("buyerReference").value : $("buyerEmail").value }
        : undefined,
    },
    items,
    payment: { means_code: "58", terms_text: $("termsText").value || undefined },
    layout: {
      header_text: $("headerText").value || undefined,
      intro_text: $("introText").value || undefined,
      closing_text: $("closingText").value || undefined,
      footer_columns: footerCols,
      accent_color: $("accent").value,
    },
  };
  $("requestJson").textContent = JSON.stringify(body, (k, v) => (v === undefined ? undefined : v), 2);
  return body;
}

// ---------- API calls ----------
function api(path) {
  return $("apiUrl").value.replace(/\/$/, "") + path;
}

async function post(path, body) {
  const res = await fetch(api(path), {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": $("apiKey").value },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = await res.text();
    try { detail = JSON.stringify(JSON.parse(detail).detail, null, 2); } catch (_) { /* keep raw */ }
    throw new Error(`HTTP ${res.status}\n${detail}`);
  }
  return res;
}

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

function filenameFrom(res, fallback) {
  const cd = res.headers.get("Content-Disposition") || "";
  const m = cd.match(/filename="?([^";]+)"?/);
  return m ? m[1] : fallback;
}

function setStatus(msg, ok) {
  const el = $("status");
  el.textContent = msg;
  el.className = "status " + (ok ? "ok" : "err");
}

function showResponse(obj) {
  $("responseBox").textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
}

async function run(label, fn) {
  setStatus(label + " …", true);
  try {
    await fn();
    setStatus(label + " ✓", true);
  } catch (e) {
    setStatus(label + " fehlgeschlagen", false);
    showResponse(String(e.message || e));
  }
}

$("btnTotals").onclick = () => run("Summen", async () => {
  const res = await post("/v1/invoices/totals", buildRequest());
  const t = await res.json();
  showResponse(t);
  const rows = [
    ["Netto", t.line_total],
    ...t.vat_breakdown.map((b) => [`USt ${b.category} ${b.rate} % auf ${b.taxable_amount}`, b.tax_amount]),
    ["Brutto", t.grand_total],
    ["Zahlbetrag", t.due],
  ];
  $("totalsBox").innerHTML = `<table class="totals">${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v} ${t.currency}</td></tr>`).join("")}</table>`;
});

$("btnHtml").onclick = () => run("HTML-Vorschau", async () => {
  const res = await post("/v1/invoices/html", buildRequest());
  const html = await res.text();
  const frame = $("preview");
  frame.hidden = false;
  frame.srcdoc = html;
  showResponse(`${html.length} Zeichen HTML`);
});

$("btnXml").onclick = () => run("XML", async () => {
  const res = await post("/v1/invoices/xml", buildRequest());
  const blob = await res.blob();
  showResponse(await blob.text());
  download(blob, filenameFrom(res, "invoice.xml"));
});

$("btnPdf").onclick = () => run("PDF", async () => {
  const res = await post("/v1/invoices/pdf", buildRequest());
  const blob = await res.blob();
  showResponse(`PDF: ${blob.size} Bytes`);
  download(blob, filenameFrom(res, "invoice.pdf"));
  const frame = $("preview");
  frame.hidden = false;
  frame.removeAttribute("srcdoc");
  frame.src = URL.createObjectURL(blob);
});

$("btnValidate").onclick = () => run("PDF validieren", async () => {
  const res = await post("/v1/invoices/pdf", buildRequest());
  const blob = await res.blob();
  const form = new FormData();
  form.append("file", blob, "invoice.pdf");
  const v = await fetch(api("/v1/validate"), { method: "POST", headers: { "X-API-Key": $("apiKey").value }, body: form });
  const report = await v.json();
  if (!v.ok) throw new Error(JSON.stringify(report, null, 2));
  showResponse({ valid: report.valid, status: report.status, messages: report.messages });
  if (!report.valid) throw new Error("Validator meldet Fehler, siehe Antwort");
});

buildRequest();
