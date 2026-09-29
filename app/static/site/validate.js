/* E-invoice validator page – uploads the file to /v1/public/validate and renders the Mustang report. */
(() => {
  "use strict";
  const LANG = document.documentElement.lang === "en" ? "en" : "de";
  const T = {
    de: { busy: "Datei wird geprüft … (einige Sekunden)", valid: "Gültig – die Datei erfüllt alle geprüften Regeln.", invalid: "Ungültig – der Validator meldet {e} Fehler und {w} Warnungen.", warn_only: "Gültig mit {w} Warnung(en).",
      summary: "Erkannte Rechnungsdaten", number: "Rechnungsnummer", date: "Rechnungsdatum", seller: "Rechnungssteller", buyer: "Rechnungsempfänger", total: "Gesamtbetrag", due: "Fällig am", profile: "Profil", lines: "Positionen", syntax: "Syntax", iban: "IBAN", ref: "Leitweg-ID / Referenz",
      messages: "Meldungen", level: "Stufe", rule: "Regel", message: "Meldung", location: "Stelle", none: "Keine Meldungen.", report: "Prüfbericht (XML) herunterladen", again: "Weitere Datei prüfen",
      err_network: "Der Server ist nicht erreichbar.", err_rate: "Zu viele Prüfungen – bitte in {s} Sekunden erneut versuchen.", err_type: "Bitte eine PDF- oder XML-Datei auswählen.", err_size: "Die Datei ist größer als 25 MB.", err_generic: "Fehler {code}: {d}", no_xml: "In dieser PDF wurde keine E-Rechnungs-XML gefunden (kein ZUGFeRD/Factur-X)." },
    en: { busy: "Checking file … (a few seconds)", valid: "Valid – the file fulfils all checked rules.", invalid: "Invalid – the validator reports {e} error(s) and {w} warning(s).", warn_only: "Valid with {w} warning(s).",
      summary: "Detected invoice data", number: "Invoice number", date: "Invoice date", seller: "Seller", buyer: "Buyer", total: "Total amount", due: "Due date", profile: "Profile", lines: "Line items", syntax: "Syntax", iban: "IBAN", ref: "Buyer reference",
      messages: "Messages", level: "Level", rule: "Rule", message: "Message", location: "Location", none: "No messages.", report: "Download report (XML)", again: "Check another file",
      err_network: "The server cannot be reached.", err_rate: "Too many checks – please retry in {s} seconds.", err_type: "Please choose a PDF or XML file.", err_size: "The file is larger than 25 MB.", err_generic: "Error {code}: {d}", no_xml: "No e-invoice XML was found in this PDF (not a ZUGFeRD/Factur-X file)." },
  }[LANG];
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtMoney = (v, cur) => (v == null ? "–" : Number(v).toLocaleString(LANG === "de" ? "de-DE" : "en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " " + (cur || ""));
  const fmtDate = (d) => (d && /^\d{4}-\d{2}-\d{2}$/.test(d) ? (LANG === "de" ? d.split("-").reverse().join(".") : d) : d || "–");
  const shortProfile = (p) => { if (!p) return "–"; if (/xrechnung/i.test(p)) return "XRechnung " + ((/xrechnung_(\d+\.\d+)/i.exec(p) || [])[1] || ""); if (/en16931/i.test(p)) return "EN 16931 (ZUGFeRD / Factur-X)"; const m = /:([a-z]+)$/i.exec(p); return m ? "Factur-X " + m[1].toUpperCase() : p; };
  const ruleId = (m) => { const r = /\[([A-Z]{2,4}-[A-Z]{0,3}-?\d+[A-Za-z0-9-]*)\]/.exec(m.message || ""); return r ? r[1] : m.type || ""; };

  const drop = $("drop"), input = $("file"), result = $("result");
  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) validate(f); });
  input.addEventListener("change", () => { if (input.files[0]) validate(input.files[0]); input.value = ""; });

  function toast(text) { const t = $("toast"); t.textContent = text; t.classList.add("show"); clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.remove("show"), 4000); }

  async function validate(file) {
    const name = file.name.toLowerCase();
    if (!(name.endsWith(".pdf") || name.endsWith(".xml"))) { toast(T.err_type); return; }
    if (file.size > 25 * 1024 * 1024) { toast(T.err_size); return; }
    result.innerHTML = `<div class="result-banner" style="background:var(--card);color:var(--muted);border:1px solid var(--line)">${esc(T.busy)}</div>`;
    const fd = new FormData(); fd.append("file", file, file.name);
    let res, data;
    try { res = await fetch("/v1/public/validate", { method: "POST", body: fd }); }
    catch (_) { result.innerHTML = `<div class="result-banner invalid">${esc(T.err_network)}</div>`; return; }
    try { data = await res.json(); } catch (_) { data = { detail: await res.text() }; }
    if (!res.ok) {
      const msg = res.status === 429 ? T.err_rate.replace("{s}", (/in (\d+)s/.exec(String(data.detail)) || [])[1] || "60") : T.err_generic.replace("{code}", res.status).replace("{d}", typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
      result.innerHTML = `<div class="result-banner invalid">${esc(msg)}</div>`; return;
    }
    render(data, file.name);
  }

  function render(r, filename) {
    const errors = r.messages.filter((m) => m.level === "error"), warnings = r.messages.filter((m) => m.level === "warning");
    let banner;
    if (r.valid && !warnings.length) banner = `<div class="result-banner valid">✔ ${esc(T.valid)}</div>`;
    else if (r.valid) banner = `<div class="result-banner valid">✔ ${esc(T.warn_only.replace("{w}", warnings.length))}</div>`;
    else banner = `<div class="result-banner invalid">✖ ${esc(T.invalid.replace("{e}", errors.length).replace("{w}", warnings.length))}</div>`;

    let summary = "";
    const s = r.summary;
    if (s && s.number) {
      const kv = [[T.number, s.number], [T.date, fmtDate(s.issue_date)], [T.seller, s.seller], [T.buyer, s.buyer], [T.total, fmtMoney(s.grand_total, s.currency)], [T.due, fmtDate(s.due_date)], [T.profile, shortProfile(s.profile)], [T.lines, s.line_count], [T.iban, s.iban], [T.ref, s.buyer_reference], [T.syntax, s.syntax]];
      summary = `<h2 style="font-size:18px;margin:20px 0 6px">${esc(T.summary)}</h2><div class="kv">${kv.filter(([, v]) => v != null && v !== "" && v !== "–").map(([k, v]) => `<div><span>${esc(k)}</span>${esc(v)}</div>`).join("")}</div>`;
    } else if (filename.toLowerCase().endsWith(".pdf") && !r.summary) summary = `<p class="muted">${esc(T.no_xml)}</p>`;

    const rows = r.messages.map((m) => `<tr><td class="lvl-${esc(m.level)}">${esc(m.level)}</td><td><code>${esc(ruleId(m))}</code></td><td>${esc((m.message || "").replace(/\s*\[ID [^\]]+\]\s*from [^)]+\)?$/, ""))}${m.location ? `<div class="muted" style="font-size:12px;word-break:break-all">${esc(m.location.replace(/\[namespace-uri\(\)='[^']+'\]/g, ""))}</div>` : ""}</td></tr>`).join("");
    const table = r.messages.length ? `<table class="msgs"><thead><tr><th>${esc(T.level)}</th><th>${esc(T.rule)}</th><th>${esc(T.message)}</th></tr></thead><tbody>${rows}</tbody></table>` : `<p class="muted">${esc(T.none)}</p>`;

    result.innerHTML = `${banner}${summary}<h2 style="font-size:18px;margin:20px 0 6px">${esc(T.messages)} (${r.messages.length})</h2>${table}
      <div class="btn-row" style="margin-top:16px"><button class="btn secondary small" id="dl">${esc(T.report)}</button><button class="btn small" id="again">${esc(T.again)}</button></div>`;
    $("dl").onclick = () => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([r.report], { type: "application/xml" })); a.download = filename.replace(/\.(pdf|xml)$/i, "") + "-pruefbericht.xml"; a.click(); };
    $("again").onclick = () => { result.innerHTML = ""; window.scrollTo({ top: 0, behavior: "smooth" }); input.click(); };
    result.scrollIntoView({ behavior: "smooth", block: "start" });
  }
})();
