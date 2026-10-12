// AI-Assisted Credit Analysis - browser app (vanilla JS, no build step).
// All AI/document text is inserted with textContent (never innerHTML) to avoid script injection.

const $main = document.getElementById("main");
const $nav = document.getElementById("steps");
const $name = document.getElementById("analyst-name");
const state = { status: null, deal: null, charts: [], reviewFilter: "All", activeStatement: null };

const STEPS = [
  ["intake", "1. Deal intake & data"],
  ["extraction", "2. Extraction"],
  ["dashboard", "3. Financial dashboard"],
  ["risks", "4. Risks & mitigants"],
  ["memo", "5. Credit memo"],
  ["review", "6. Review & export"],
];
const UNIT_LABEL = { percent: "Percent (%)", multiple: "Multiple (x)", days: "Days", amount: "Amount (unit not stated in database)" };
const PALETTE = ["#1f4e79", "#b35c00", "#2e7d32", "#7b1fa2", "#00838f"];

// --------------------------------------------------------------------------- helpers
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const tag = (text, kind = "info") => h("span", { class: `tag ${kind}` }, text);
const statusKind = (s) => ({ Approved: "ok", Flagged: "bad", Pending: "warn" }[s] || "muted");
const labelKind = (l) => ({ Sourced: "ok", ASSUMPTION: "warn", "NOT VERIFIED": "bad" }[l] || "muted");
const analyst = () => $name.value.trim();

function announce(msg) {
  const s = document.getElementById("status");
  s.textContent = "";
  setTimeout(() => (s.textContent = msg), 30);
}

function toast(msg, ok = false) {
  const t = document.getElementById("toast");
  t.replaceChildren(h("button", { class: "small secondary", onclick: () => (t.hidden = true), "aria-label": "Dismiss message" }, "Close"), msg);
  t.className = ok ? "toast ok" : "toast";
  t.hidden = false;
  if (ok) setTimeout(() => (t.hidden = true), 5000);
}

class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || `Request failed (${status})`);
    this.status = status; this.body = body || {};
  }
}

async function api(method, path, body, isForm = false) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) opts.body = body;
    else { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  }
  const res = await fetch(`/api${path}`, opts);
  const ctype = res.headers.get("content-type") || "";
  const data = ctype.includes("application/json") ? await res.json() : null;
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

function errText(e) {
  if (!(e instanceof ApiError)) return String(e.message || e);
  let msg = e.message;
  const d = e.body.details;
  if (Array.isArray(d) && d.length) {
    msg += "\n" + d.slice(0, 12).map((x) => "- " + (typeof x === "string" ? x : x.reason ? `${x.statement_id}: ${x.reason}` : JSON.stringify(x))).join("\n");
  }
  return msg;
}

async function busy(button, label, fn) {
  const holder = h("span", { class: "busy" }, label);
  button.disabled = true;
  button.after(holder);
  announce(label);
  try { return await fn(); }
  catch (e) { toast(errText(e)); announce("Error: " + e.message); throw e; }
  finally { button.disabled = false; holder.remove(); }
}

function needName() {
  if (!analyst()) {
    toast("Enter your analyst name at the top of the page first (1 to 100 characters).");
    $name.setAttribute("aria-invalid", "true");
    $name.focus();
    return true;
  }
  $name.removeAttribute("aria-invalid");
  return false;
}

function destroyCharts() { state.charts.forEach((c) => c.destroy()); state.charts = []; }

function evButton(id, statementId, onOpen) {
  return h("button", { class: "ev", type: "button", title: `Open source for ${id}`, onclick: () => onOpen(id, statementId) }, id);
}

async function download(path, body, button) {
  await busy(button, "Generating PDF...", async () => {
    const res = await fetch(`/api${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
    const blob = await res.blob();
    const cd = res.headers.get("content-disposition") || "";
    const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
    const a = h("a", { href: URL.createObjectURL(blob), download: m ? decodeURIComponent(m[1]) : "document.pdf" });
    document.body.append(a); a.click(); a.remove();
    announce("PDF downloaded");
  });
}

// --------------------------------------------------------------------------- shell
async function loadStatus() {
  state.status = await api("GET", "/status");
  document.getElementById("notice").textContent = state.status.notice;
  const b = document.getElementById("llm-status");
  if (state.status.llm_configured) { b.className = "tag ok"; b.textContent = `AI: ${state.status.provider} / ${state.status.model}`; }
  else { b.className = "tag bad"; b.textContent = `AI not configured: set ${state.status.missing_settings.join(", ")} in .env`; }
}

function sectionState(deal, key) {
  if (!deal) return "";
  const s = deal.sections;
  switch (key) {
    case "intake": return deal.financial.status === "loaded" ? `${deal.documents.length} document(s), CSV loaded` : `${deal.documents.length} document(s), CSV not loaded`;
    case "extraction": return `2A ${s.s2a.status.replace("_", " ")}, 2B ${s.s2b.status.replace("_", " ")}`;
    case "dashboard": return s.s3.status === "not_run" ? "AI analysis not run" : `${s.s3.status}${deal.s3_approved ? ", approved" : ", not approved"}`;
    case "risks": return s.s4.status.replace("_", " ");
    case "memo": return s.s5.status.replace("_", " ");
    case "review": return deal.memo_counts ? `${deal.memo_counts.Pending} pending, ${deal.memo_counts.Approved} approved, ${deal.memo_counts.Flagged} flagged` : "no memo yet";
  }
  return "";
}

function renderNav(screen) {
  const deal = state.deal;
  if (!deal) {
    $nav.replaceChildren(h("ol", {}, h("li", {}, h("a", { href: "#/", "aria-current": screen === "home" ? "page" : null }, "All deals")),
      h("li", {}, h("a", { href: "#/new", "aria-current": screen === "new" ? "page" : null }, "New deal"))));
    return;
  }
  $nav.replaceChildren(
    h("p", { class: "deal-title" }, deal.intake["DI-BORROWER"].display),
    h("ol", {}, STEPS.map(([key, label]) => h("li", {},
      h("a", { href: `#/deal/${deal.deal_id}/${key}`, "aria-current": key === screen ? "page" : null }, label,
        h("span", { class: "state" }, sectionState(deal, key)))))),
    h("p", {}, h("a", { href: "#/" }, "Back to all deals")));
}

async function refreshDeal() {
  if (state.deal) state.deal = await api("GET", `/deals/${state.deal.deal_id}`);
}

async function route() {
  destroyCharts();
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  try {
    if (parts[0] === "deal" && parts[1]) {
      state.deal = await api("GET", `/deals/${parts[1]}`);
      const screen = parts[2] || "intake";
      renderNav(screen);
      await ({ intake: screenIntake, extraction: screenExtraction, dashboard: screenDashboard, risks: screenRisks,
        memo: screenMemo, review: screenReview }[screen] || screenIntake)();
    } else if (parts[0] === "new") {
      state.deal = null; renderNav("new"); screenNewDeal();
    } else {
      state.deal = null; renderNav("home"); await screenHome();
    }
  } catch (e) {
    $main.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Something went wrong"), h("p", {}, errText(e))));
  }
  $main.focus();
}

async function rerender() {
  const y = window.scrollY;
  await refreshDeal();
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  renderNav(parts[2] || "intake");
  destroyCharts();
  await ({ intake: screenIntake, extraction: screenExtraction, dashboard: screenDashboard, risks: screenRisks,
    memo: screenMemo, review: screenReview }[parts[2] || "intake"])();
  window.scrollTo(0, y);
}

// --------------------------------------------------------------------------- home + new deal
async function screenHome() {
  const deals = await api("GET", "/deals");
  $main.replaceChildren(
    h("h2", {}, "Credit analyses"),
    h("div", { class: "row" }, h("a", { href: "#/new", class: "button-link" }, "Start a new deal")),
    h("div", { class: "card", style: "margin-top:12px" },
      deals.length ? h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Borrower"), h("th", {}, "Facility"), h("th", {}, "Created"))),
        h("tbody", {}, deals.map((d) => h("tr", {}, h("td", {}, h("a", { href: `#/deal/${d.deal_id}/intake` }, d.borrower)),
          h("td", {}, d.facility_type), h("td", {}, d.created_at.replace("T", " ").slice(0, 16))))))
        : h("p", { class: "empty" }, "No deals yet. Start a new deal to enter a loan request.")));
}

function field(id, label, input, hint) {
  return h("div", { class: "field" }, h("label", { for: id }, label), input, hint ? h("span", { class: "hint", id: `${id}-hint` }, hint) : null,
    h("span", { class: "err", id: `${id}-err`, "aria-live": "polite" }));
}

function showFieldErrors(form, fields) {
  form.querySelectorAll(".err").forEach((e) => (e.textContent = ""));
  form.querySelectorAll("[aria-invalid]").forEach((e) => e.removeAttribute("aria-invalid"));
  let first = null;
  for (const f of fields || []) {
    const input = form.querySelector(`#f-${f.field}`);
    const err = form.querySelector(`#f-${f.field}-err`);
    if (input) { input.setAttribute("aria-invalid", "true"); input.setAttribute("aria-describedby", `f-${f.field}-err`); first = first || input; }
    if (err) err.textContent = f.reason;
  }
  if (first) first.focus();
}

function screenNewDeal() {
  const inp = (id, attrs = {}) => h("input", { id: `f-${id}`, name: id, type: "text", ...attrs });
  const ta = (id, attrs = {}) => h("textarea", { id: `f-${id}`, name: id, ...attrs });
  const form = h("form", { class: "card", novalidate: true },
    h("div", { class: "grid2" },
      field("f-borrower", "Borrower / company name *", inp("borrower", { required: true, maxlength: 200, value: "Intel Corporation" })),
      field("f-facility_type", "Facility type *", inp("facility_type", { required: true, maxlength: 100, list: "facility-types", placeholder: "e.g. Term loan" })),
      field("f-amount", "Requested amount *", inp("amount", { required: true, inputmode: "decimal", placeholder: "e.g. 500000000" }), "Numbers only, up to 2 decimals"),
      field("f-currency", "Currency *", inp("currency", { required: true, maxlength: 3, value: "USD" }), "3-letter code"),
      field("f-tenor", "Tenor *", inp("tenor", { required: true, maxlength: 100, placeholder: "e.g. 5 years" }))),
    h("datalist", { id: "facility-types" }, ["Term loan", "Revolving credit facility", "Bridge loan", "Syndicated loan", "Trade finance line"].map((v) => h("option", { value: v }))),
    h("div", { class: "grid2", style: "margin-top:12px" },
      field("f-purpose", "Purpose of loan *", ta("purpose", { required: true, maxlength: 2000 })),
      field("f-repayment", "Repayment structure *", ta("repayment", { required: true, maxlength: 2000, placeholder: "e.g. Bullet at maturity / quarterly amortisation" })),
      field("f-collateral", "Collateral / security (optional)", ta("collateral", { maxlength: 2000 }), "Left blank = \"None provided\"")),
    h("div", { class: "row", style: "margin-top:14px" }, h("button", { type: "submit" }, "Create deal")));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    const missing = ["borrower", "facility_type", "amount", "currency", "purpose", "tenor", "repayment"]
      .filter((k) => !String(data[k] || "").trim()).map((k) => ({ field: k, reason: "This field is required" }));
    if (missing.length) { showFieldErrors(form, missing); return; }
    try {
      const deal = await api("POST", "/deals", data);
      location.hash = `#/deal/${deal.deal_id}/intake`;
    } catch (e) {
      showFieldErrors(form, e.body?.fields);
      toast(errText(e));
    }
  });
  $main.replaceChildren(h("h2", {}, "Section 1: Deal intake"),
    h("p", {}, "Enter the loan request. The analysis assesses whether the borrower can support this specific request."), form);
}

// --------------------------------------------------------------------------- Section 1: deal + documents + CSV
async function screenIntake() {
  const deal = state.deal;
  const intakeTable = h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Reference"), h("th", {}, "Field"), h("th", {}, "Value"))),
    h("tbody", {}, Object.entries(deal.intake).map(([k, v]) => h("tr", {}, h("td", {}, h("code", {}, k)), h("td", {}, v.label), h("td", {}, v.display)))));

  const upForm = h("form", { class: "grid2", novalidate: true },
    field("f-file", "PDF file *", h("input", { id: "f-file", name: "file", type: "file", accept: "application/pdf,.pdf", required: true })),
    field("f-doc_type", "Document type *", h("select", { id: "f-doc_type", name: "doc_type", required: true },
      h("option", { value: "" }, "Choose..."), state.status.doc_types.map((t) => h("option", { value: t }, t)))),
    field("f-period_covered", "Period covered *", h("input", { id: "f-period_covered", name: "period_covered", type: "text", maxlength: 50, placeholder: "e.g. FY2025 or Q2 2026" })),
    field("f-audited", "Audited *", h("select", { id: "f-audited", name: "audited" }, h("option", { value: "" }, "Choose..."), h("option", { value: "Yes" }, "Yes"), h("option", { value: "No" }, "No"))),
    field("f-display_name", "Display name (optional)", h("input", { id: "f-display_name", name: "display_name", type: "text", maxlength: 255, placeholder: "e.g. Intel 2025 10-K" })),
    h("div", { class: "field" }, h("span", {}, "\u00a0"), h("button", { type: "submit" }, "Upload document")));
  upForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const fd = new FormData(upForm);
    const errs = [];
    if (!upForm.querySelector("#f-file").files.length) errs.push({ field: "file", reason: "Choose a PDF file" });
    if (!fd.get("doc_type")) errs.push({ field: "doc_type", reason: "Choose a document type" });
    const p = String(fd.get("period_covered") || "").trim();
    if (!p || p.length > 50) errs.push({ field: "period_covered", reason: "Enter 1 to 50 characters" });
    if (!fd.get("audited")) errs.push({ field: "audited", reason: "Choose Yes or No" });
    if (errs.length) { showFieldErrors(upForm, errs); return; }
    showFieldErrors(upForm, []);
    const btn = upForm.querySelector("button[type=submit]");
    try {
      const res = await busy(btn, "Uploading and reading pages...", () => api("POST", `/deals/${deal.deal_id}/documents`, fd, true));
      toast(`Uploaded ${res.document.doc_id} (${res.document.page_count} pages).` + (res.warnings.length ? "\n" + res.warnings.join("\n") : ""), !res.warnings.length);
      await rerender();
    } catch (e) { showFieldErrors(upForm, e.body?.fields); }
  });
  const docTable = deal.documents.length
    ? h("table", {}, h("thead", {}, h("tr", {}, ["doc_id", "Name", "Type", "Period", "Audited", "Pages", "Notes"].map((x) => h("th", {}, x)))),
      h("tbody", {}, deal.documents.map((d) => h("tr", {}, h("td", {}, d.doc_id), h("td", {}, d.display_name), h("td", {}, d.doc_type),
        h("td", {}, d.period_covered), h("td", {}, d.audited ? "Yes" : "No"), h("td", {}, String(d.page_count)),
        h("td", {}, d.extraction_excluded ? tag("No extractable text: excluded", "bad") : d.no_text_pages.length ? tag(`${d.no_text_pages.length} page(s) without text`, "warn") : "")))))
    : h("p", { class: "empty" }, "No documents uploaded yet. Upload the 10-K, 10-Q, annual report or audited statements.");

  // financial database
  const fin = h("div", {});
  const csvInput = h("input", { id: "f-csv", type: "file", accept: ".csv,text/csv" });
  const loadBtn = h("button", { type: "button" }, deal.financial.status === "loaded" ? "Reload financial database" : "Load financial database");
  const upCsvBtn = h("button", { type: "button", class: "secondary" }, "Upload replacement CSV");
  upCsvBtn.addEventListener("click", async () => {
    if (!csvInput.files.length) { toast("Choose a .csv file first."); csvInput.focus(); return; }
    const fd = new FormData(); fd.append("file", csvInput.files[0]);
    await busy(upCsvBtn, "Uploading CSV...", () => api("POST", `/deals/${deal.deal_id}/financial/upload`, fd, true)).catch(() => null);
    toast("CSV uploaded for this deal. Now load it.", true);
    await rerender();
  });
  loadBtn.addEventListener("click", async () => {
    try {
      let res = await busy(loadBtn, "Loading financial database...", () => api("POST", `/deals/${deal.deal_id}/financial/load`, { confirm: null }));
      if (res.status === "needs_confirmation") {
        const ok = window.confirm(res.message + "\n\nOK = the whole file belongs to this borrower. Cancel = stop loading.");
        res = await busy(loadBtn, "Loading financial database...", () => api("POST", `/deals/${deal.deal_id}/financial/load`, { confirm: ok }));
      }
      toast("Financial database loaded.", true);
      await rerender();
    } catch (e) { /* toast shown */ }
  });
  fin.append(
    h("p", {}, "Financial figures and credit metrics come only from the financial database (CSV), loaded with Python and Pandas. Nothing is calculated by the AI."),
    h("p", {}, "Source: ", h("b", {}, deal.financial.source ? `${deal.financial.source} (uploaded for this deal)` : `${state.status.default_csv} (default)`),
      deal.financial.status === "loaded" ? h("span", {}, " ", tag("Loaded", "ok")) : h("span", {}, " ", tag("Not loaded", "warn"))),
    h("div", { class: "row" }, loadBtn, h("label", { for: "f-csv" }, "Replacement CSV (optional):"), csvInput, upCsvBtn));
  if (deal.financial.status === "loaded") {
    const ds = await api("GET", `/deals/${deal.deal_id}/financial`);
    fin.append(
      h("p", {}, `Periods (oldest to newest): ${ds.periods.map((p) => p.label).join(", ")}. Metrics: ${ds.metrics.length}.`),
      h("h4", {}, `Values flagged for review (${ds.flagged_values.length})`),
      ds.flagged_values.length ? h("table", {}, h("thead", {}, h("tr", {}, ["Evidence ID", "Metric", "Period", "Value", "Flags"].map((x) => h("th", {}, x)))),
        h("tbody", {}, ds.flagged_values.map((f) => h("tr", {}, h("td", {}, h("code", {}, f.evidence_id)), h("td", {}, f.metric), h("td", {}, f.period),
          h("td", {}, f.display), h("td", {}, f.flags.map((x) => tag(x, "warn"))))))) : h("p", {}, "None."),
      h("h4", {}, "Information gaps"), h("ul", {}, ds.information_gaps.map((g) => h("li", {}, g))));
  }

  $main.replaceChildren(
    h("h2", {}, "Section 1: Deal intake and data"),
    h("div", { class: "card" }, h("h3", {}, "Loan request"), intakeTable),
    h("div", { class: "card" }, h("h3", {}, "Documents"), upForm, h("div", { style: "margin-top:12px" }, docTable)),
    h("div", { class: "card" }, h("h3", {}, "Financial database (Section 2D)"), fin),
    h("p", {}, h("a", { href: `#/deal/${deal.deal_id}/extraction` }, "Next: Section 2 extraction")));
}

// --------------------------------------------------------------------------- source viewer
async function renderSource(container, evId, statementId) {
  container.replaceChildren(h("span", { class: "busy" }, `Loading ${evId}...`));
  try {
    const q = statementId ? `?statement_id=${encodeURIComponent(statementId)}` : "";
    const s = await api("GET", `/deals/${state.deal.deal_id}/evidence/${encodeURIComponent(evId)}${q}`);
    const rows = [];
    const row = (k, v) => rows.push(h("tr", {}, h("th", { scope: "row" }, k), h("td", {}, v)));
    if (s.type === "csv") {
      row("Evidence ID", s.evidence_id); row("Source", `Financial database: ${s.file_name}`); row("Metric (as in CSV)", s.metric_label);
      row("Period column", s.column_header); row("Value", s.display); row("Anomaly flags", s.flags.join(", "));
      container.replaceChildren(h("h3", {}, `Source for ${evId}`), h("table", {}, h("tbody", {}, rows)));
    } else if (s.type === "deal_intake") {
      row("Evidence ID", s.evidence_id); row("Source", "Deal intake (entered by the analyst)"); row(s.label, s.value);
      container.replaceChildren(h("h3", {}, `Source for ${evId}`), h("table", {}, h("tbody", {}, rows)));
    } else {
      row("Evidence ID", s.evidence_id); row("Document", `${s.doc_id} ${s.doc_name}`); row("Page", String(s.page)); row("Section", s.section_heading);
      row("Extracted statement", s.statement); row("Supporting text", `\u201c${s.excerpt}\u201d`);
      row("Passage on page", s.location_status === "Located" ? tag("Located (highlighted below)", "ok") : tag(s.location_status, "bad"));
      container.replaceChildren(h("h3", {}, `Source for ${evId}`), h("table", {}, h("tbody", {}, rows)),
        s.image ? h("img", { src: s.image, alt: `Page ${s.page} of ${s.doc_name}${s.location_status === "Located" ? " with the supporting passage highlighted" : ""}`, style: "margin-top:10px" })
          : h("p", { class: "muted" }, "The source document or page is unavailable."));
    }
    announce(`Source for ${evId} shown`);
    return s;
  } catch (e) {
    container.replaceChildren(h("p", { class: "tag bad" }, errText(e)));
    return null;
  }
}

function sourceDialog(evId) {
  const body = h("div", {});
  const dlg = h("dialog", { "aria-label": `Source for ${evId}`, style: "max-width:900px;width:90vw" },
    h("div", { class: "row" }, h("span", { class: "spacer" }), h("button", { type: "button", class: "secondary", onclick: () => dlg.close() }, "Close")), body);
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
  renderSource(body, evId, null);
}

// --------------------------------------------------------------------------- Section 2
async function screenExtraction() {
  const deal = state.deal;
  const data = await api("GET", `/deals/${deal.deal_id}/section2`);
  const run = (scopes, label) => {
    const b = h("button", { type: "button", class: scopes.length === 2 ? "" : "secondary" }, label);
    b.addEventListener("click", async () => {
      try {
        const res = await busy(b, "Extracting with the AI and locating passages with PyMuPDF. This can take a few minutes...",
          () => api("POST", `/deals/${deal.deal_id}/section2/run`, { scopes }));
        const msgs = Object.values(res.messages).filter(Boolean);
        toast("Extraction complete." + (msgs.length ? "\n" + msgs.join("\n") : ""), !msgs.length);
        await rerender();
      } catch (e) { /* shown */ }
    });
    return b;
  };
  const sec = deal.sections;
  const group = (scope, title, key) => {
    const s2 = data.s2[scope];
    const st = sec[key];
    const head = h("div", { class: "row" }, h("h3", { style: "margin:0" }, title), tag(st.status.replace("_", " "), st.status === "completed" ? "ok" : st.status === "stale" ? "warn" : "muted"));
    if (st.last_error) head.append(tag("Last run failed", "bad"));
    if (!s2) return h("div", { class: "card" }, head, h("p", { class: "empty" }, "Not run yet."));
    const rows = [];
    for (const f of s2.fields) {
      const ids = f.evidence_ids;
      if (!ids.length) rows.push(h("tr", {}, h("td", {}, f.label), h("td", {}, "None"), h("td", { colspan: 4 }, tag("Not available", "muted")), h("td", {}, f.issues.filter((x) => x !== "Not available").map((x) => tag(x, "bad")))));
      ids.forEach((id, i) => {
        const e = data.evidence[id];
        if (!e) return;
        rows.push(h("tr", {}, h("td", {}, i === 0 ? f.label : ""), h("td", {}, evButton(id, null, sourceDialog)), h("td", {}, e.statement),
          h("td", {}, e.doc_name), h("td", {}, String(e.page)), h("td", {}, e.location_status === "Located" ? tag("Located", "ok") : tag("Not located: review", "bad")),
          h("td", {}, e.issues.map((x) => tag(x, "bad")))));
      });
      if (f.rejected.length) rows.push(h("tr", {}, h("td", {}), h("td", { colspan: 6 }, h("details", {}, h("summary", {}, `${f.rejected.length} rejected item(s) for ${f.label}`),
        h("ul", {}, f.rejected.map((r) => h("li", {}, `${r.statement} (${r.doc_id} p.${r.page}): ${r.reason}`)))))));
    }
    return h("div", { class: "card" }, head, s2.message ? h("p", { class: "tag warn" }, s2.message) : null,
      h("table", {}, h("thead", {}, h("tr", {}, ["Field", "Evidence ID", "Statement", "Document", "Page", "Passage", "Issues"].map((x) => h("th", {}, x)))), h("tbody", {}, rows)));
  };
  $main.replaceChildren(
    h("h2", {}, "Section 2: Extract and organise the relevant information"),
    h("div", { class: "card" },
      h("p", {}, "The AI reads the uploaded documents and extracts business information (2A) and debt and financing information (2B). Each item gets an Evidence ID and its supporting passage is checked on the cited page with PyMuPDF. Financial figures are not extracted by the AI; they come from the financial database."),
      deal.documents.length ? h("div", { class: "row" }, run(["business", "debt"], "Run extraction (2A and 2B)"), run(["business"], "Re-run 2A only"), run(["debt"], "Re-run 2B only"))
        : h("p", { class: "tag warn" }, "Upload at least one PDF in Section 1 first.")),
    group("business", "2A Business information", "s2a"),
    group("debt", "2B Debt and financing information", "s2b"),
    h("p", {}, h("a", { href: `#/deal/${deal.deal_id}/dashboard` }, "Next: Section 3 financial dashboard")));
}

// --------------------------------------------------------------------------- Section 3
const pointLabels = {
  id: "pointLabels",
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    chart.data.datasets.forEach((ds, i) => {
      const meta = chart.getDatasetMeta(i);
      if (meta.hidden) return;
      meta.data.forEach((pt, j) => {
        if (ds.data[j] === null || ds.data[j] === undefined) return;
        const text = ds.displays[j] + (ds.flags[j].length ? " \u26a0" : "");
        ctx.save(); ctx.font = "600 11px 'Segoe UI', sans-serif"; ctx.fillStyle = "#1b1f24"; ctx.textAlign = "center";
        ctx.fillText(text, pt.x, pt.y - 9); ctx.restore();
      });
    });
  },
};

function panelCharts(panel, periods) {
  const wrap = h("div", {});
  const byUnit = {};
  panel.metrics.forEach((m) => (byUnit[m.unit] = byUnit[m.unit] || []).push(m));
  let colour = 0;
  for (const [unit, metrics] of Object.entries(byUnit)) {
    const canvas = h("canvas", { role: "img", "aria-label": `${panel.title} chart: ${metrics.map((m) => m.label).join(", ")}. Values are listed in the data table below.` });
    wrap.append(h("p", { class: "small muted", style: "margin:4px 0" }, UNIT_LABEL[unit] || unit), h("div", { class: "chart-box" }, canvas));
    const datasets = metrics.map((m) => {
      const c = PALETTE[colour++ % PALETTE.length];
      return { label: m.label, data: m.series.map((p) => p.value), displays: m.series.map((p) => p.display), flags: m.series.map((p) => p.flags),
        borderColor: c, backgroundColor: c, spanGaps: false, tension: 0, pointRadius: 4,
        pointStyle: m.series.map((p) => (p.flags.length ? "triangle" : "circle")), pointRadiusFlags: 6 };
    });
    state.charts.push(new Chart(canvas, {
      type: "line", data: { labels: periods, datasets },
      options: { responsive: true, maintainAspectRatio: false, animation: false, layout: { padding: { top: 18 } },
        plugins: { legend: { position: "bottom" }, tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.dataset.displays[ctx.dataIndex]}${ctx.dataset.flags[ctx.dataIndex].length ? " (flags: " + ctx.dataset.flags[ctx.dataIndex].join(", ") + ")" : ""}` } } },
        scales: { y: { title: { display: true, text: UNIT_LABEL[unit] || unit }, grace: "10%" } } },
      plugins: [pointLabels],
    }));
  }
  return wrap;
}

function dataTable(panel, periods) {
  if (!panel.metrics.length) return null;
  return h("details", {}, h("summary", {}, `Data table: ${panel.title}`),
    h("table", {}, h("caption", { class: "small muted" }, "Values exactly as stored in the financial database, oldest to newest"),
      h("thead", {}, h("tr", {}, h("th", {}, "Period"), panel.metrics.map((m) => h("th", {}, m.label)))),
      h("tbody", {}, periods.map((p, i) => h("tr", {}, h("th", { scope: "row" }, p), panel.metrics.map((m) => {
        const pt = m.series[i];
        return h("td", {}, pt ? pt.display : "Not available in database", pt && pt.flags.length ? h("div", {}, pt.flags.map((f) => tag(f, "warn"))) : null);
      }))))));
}

function s3Statement(st, approved) {
  const box = h("div", { class: `stmt ${st.status}`, id: `st-${st.id}` });
  const meta = h("div", { class: "meta" }, h("code", {}, st.id), tag(st.label, labelKind(st.label)),
    tag(st.verification.mark, st.verification.mark === "Numbers verified" ? "ok" : "bad"), tag(st.status, statusKind(st.status)),
    st.refs.map((r) => evButton(r, null, sourceDialog)));
  box.append(h("div", {}, st.text), meta);
  if (st.text !== st.original_text) box.append(h("div", { class: "small muted" }, "Edited. Original: ", st.original_text));
  if (st.verification.unmatched.length) box.append(h("div", { class: "unmatched" }, "Not matched: " + st.verification.unmatched.map((u) => `${u.value} (${u.reason})`).join("; ")));
  if (st.comments.length) box.append(h("ul", { class: "small" }, st.comments.map((c) => h("li", {}, `${c.analyst_name}: ${c.text}`))));
  const act = async (action, text, btn) => {
    if (needName()) return;
    try {
      await busy(btn, "Saving...", () => api("POST", `/deals/${state.deal.deal_id}/section3/statements/${st.id}/action`, { action, analyst_name: analyst(), text }));
      announce(`${st.id} ${action} saved`);
      await rerender();
      document.getElementById(`st-${st.id}`)?.querySelector("button")?.focus();
    } catch (e) { /* shown */ }
  };
  const editor = (kind) => {
    const ta = h("textarea", { "aria-label": kind === "edit" ? `Edit ${st.id}` : `Comment on ${st.id}`, maxlength: kind === "edit" ? 5000 : 2000 }, kind === "edit" ? st.text : "");
    const save = h("button", { type: "button", class: "small" }, kind === "edit" ? "Save edit" : "Save comment");
    save.addEventListener("click", () => act(kind, ta.value, save));
    const ed = h("div", { class: "editor" }, ta, h("div", { class: "row" }, save, h("button", { type: "button", class: "small secondary", onclick: () => ed.remove() }, "Cancel")));
    box.querySelector(".editor")?.remove();
    box.append(ed); ta.focus();
  };
  const actions = h("div", { class: "actions" });
  const ap = h("button", { type: "button", class: "small" }, "Approve"); ap.addEventListener("click", () => act("approve", null, ap));
  const fl = h("button", { type: "button", class: "small secondary" }, "Flag"); fl.addEventListener("click", () => act("flag", null, fl));
  actions.append(ap, fl, h("button", { type: "button", class: "small secondary", onclick: () => editor("comment") }, "Comment"),
    h("button", { type: "button", class: "small secondary", onclick: () => editor("edit") }, "Edit"));
  box.append(actions);
  return box;
}

async function screenDashboard() {
  const deal = state.deal;
  if (deal.financial.status !== "loaded") {
    $main.replaceChildren(h("h2", {}, "Section 3: Financial trend dashboard"), h("p", { class: "empty" }, "The financial database CSV must be loaded first (Section 1)."));
    return;
  }
  const [dash, s3] = await Promise.all([api("GET", `/deals/${deal.deal_id}/dashboard`), api("GET", `/deals/${deal.deal_id}/section3`)]);
  const has = s3 && s3.statements;
  const stmts = has ? s3.statements : [];
  const runBtn = h("button", { type: "button" }, has ? "Re-run AI analysis" : "Run AI financial analysis");
  runBtn.addEventListener("click", async () => {
    try { await busy(runBtn, "The AI is analysing trends; the backend is checking every figure...", () => api("POST", `/deals/${deal.deal_id}/section3/run`)); toast("Section 3 analysis ready for review.", true); await rerender(); } catch (e) { }
  });
  const approveBtn = h("button", { type: "button" }, "Approve financial analysis");
  approveBtn.addEventListener("click", async () => {
    if (needName()) return;
    try { await busy(approveBtn, "Approving...", () => api("POST", `/deals/${deal.deal_id}/section3/approve`, { analyst_name: analyst() })); toast("Financial analysis approved. Section 4 can now run.", true); await rerender(); } catch (e) { }
  });
  const counts = { Pending: 0, Approved: 0, Flagged: 0 };
  stmts.forEach((s) => counts[s.status]++);
  const mismatches = stmts.filter((s) => s.verification.mark === "Number mismatch").length;
  const pendingVerified = stmts.filter((s) => s.status === "Pending" && s.verification.mark === "Numbers verified").length;
  const pendingMismatch = stmts.filter((s) => s.status === "Pending" && s.verification.mark === "Number mismatch").length;
  const bulk = (action, label, n, question) => {
    const b = h("button", { type: "button", class: "secondary", disabled: n === 0 }, `${label} (${n})`);
    b.addEventListener("click", async () => {
      if (needName() || !window.confirm(question)) return;
      try {
        const r = await busy(b, "Saving...", () => api("POST", `/deals/${deal.deal_id}/section3/bulk`, { action, analyst_name: analyst() }));
        toast(`${r.changed} statement(s) updated. Each one is recorded in the audit trail under your name.`, true);
        await rerender();
      } catch (e) { }
    });
    return b;
  };
  const bulkRow = has && counts.Pending ? h("div", { class: "row", style: "margin-top:8px" },
    h("span", { class: "small" }, h("b", {}, "Bulk review: ")),
    bulk("approve_verified", "Approve all pending with \u201cNumbers verified\u201d", pendingVerified,
      `Approve ${pendingVerified} pending statement(s) whose figures Python matched to the database?\n\nThis confirms you have read them and agree with the interpretation, not just the numbers. Each approval is recorded under your name.`),
    bulk("flag_mismatches", "Flag all pending with \u201cNumber mismatch\u201d", pendingMismatch,
      `Flag ${pendingMismatch} pending statement(s) whose figures did not match the database?`)) : null;
  const s3state = deal.sections.s3;
  const top = h("div", { class: "card" },
    h("p", {}, "Charts use the financial database values directly. The AI commentary beside each chart is checked by Python: every figure must match the cited data and every comparison must match the backend's comparison records."),
    h("div", { class: "row" }, runBtn,
      has ? h("span", {}, tag(`${counts.Pending} pending`, "warn"), " ", tag(`${counts.Approved} approved`, "ok"), " ", tag(`${counts.Flagged} flagged`, "bad"), " ",
        tag(`${mismatches} number mismatch(es)`, mismatches ? "bad" : "ok")) : null,
      h("span", { class: "spacer" }),
      has ? (deal.s3_approved ? tag(`Approved by ${s3.approval?.analyst_name || "analyst"}`, "ok") : approveBtn) : null),
    s3state.status === "stale" ? h("p", { class: "tag warn" }, "Out of date: an earlier section was re-run. Re-run the AI analysis.") : null,
    s3state.last_error ? h("details", {}, h("summary", {}, "Last run failed"), h("ul", {}, s3state.last_error.map((x) => h("li", {}, x)))) : null,
    has && !deal.s3_approved ? h("p", { class: "small muted" }, "To approve, every statement must be Approved or Flagged, and any statement with a number mismatch must be corrected or flagged. Read the commentary beside each chart first; use the bulk buttons for the remaining routine statements.") : null,
    bulkRow);

  const panels = dash.panels.map((p) => {
    const latest = h("div", { class: "latest" }, p.metrics.map((m) => h("div", { class: "metric" }, `${m.label} (${m.latest.period}): `, h("b", {}, m.latest.display),
      m.latest.flags.length ? h("div", {}, m.latest.flags.map((f) => tag(f, "warn"))) : null,
      h("div", { class: "small" }, m.latest_comparison ? `${m.latest_comparison.from_period} to ${m.latest_comparison.to_period}: ${m.latest_comparison.change_display} (${m.latest_comparison.direction === "~" ? "stable" : m.latest_comparison.direction})` : "No comparison available",
        m.sustained ? ` - ${m.sustained}` : ""))));
    const commentary = has ? stmts.filter((s) => s.group === `panel:${p.key}`).map((s) => s3Statement(s)) : [h("p", { class: "empty" }, "The Section 3 analysis has not been run.")];
    return h("section", { class: "card", "aria-labelledby": `panel-${p.key}` },
      h("h3", { id: `panel-${p.key}` }, p.title),
      h("div", { class: "panel" },
        h("div", {}, panelCharts(p, dash.periods), latest,
          p.not_available.length ? h("p", { class: "small" }, h("b", {}, "Not available in database: "), p.not_available.join(", ")) : null, dataTable(p, dash.periods)),
        h("div", {}, h("h4", { style: "margin-top:0" }, "AI commentary"), commentary)));
  });

  const extra = [];
  if (has) {
    extra.push(h("div", { class: "card" }, h("h3", {}, "Divergence patterns (Project Details)"),
      h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Pattern"), h("th", {}, "Result"), h("th", {}, "Missing metrics"))),
        h("tbody", {}, s3.divergences.map((d) => h("tr", {}, h("td", {}, `${d.pattern_id}: ${d.description}`), h("td", {}, d.result), h("td", {}, d.missing_metrics.join(", ") || "-")))))));
    const cross = stmts.filter((s) => s.group === "cross");
    extra.push(h("div", { class: "card" }, h("h3", {}, "Relationships between database metrics"), cross.length ? cross.map((s) => s3Statement(s)) : h("p", { class: "muted" }, "None reported.")));
    const dims = ["profitability", "cash_generation", "leverage", "liquidity", "debt_servicing"];
    extra.push(h("div", { class: "card" }, h("h3", {}, "Repayment capacity"),
      dims.map((d) => h("div", {}, h("h4", {}, d.replace("_", " ").replace(/^./, (c) => c.toUpperCase())),
        h("div", { class: "grid2" },
          h("div", {}, h("p", { class: "small" }, h("b", {}, "Supports repayment")), stmts.filter((s) => s.group === `repayment:${d}:supports`).map((s) => s3Statement(s))),
          h("div", {}, h("p", { class: "small" }, h("b", {}, "Weakens repayment")), stmts.filter((s) => s.group === `repayment:${d}:weakens`).map((s) => s3Statement(s))))))));
  }
  $main.replaceChildren(h("h2", {}, "Section 3: Financial trend dashboard and AI analysis"), top, panels, extra,
    h("p", {}, h("a", { href: `#/deal/${deal.deal_id}/risks` }, "Next: Section 4 risks and mitigants")));
}

// --------------------------------------------------------------------------- Section 4
async function screenRisks() {
  const deal = state.deal;
  const s4 = await api("GET", `/deals/${deal.deal_id}/section4`);
  const runBtn = h("button", { type: "button", disabled: !deal.s3_approved }, s4.risks ? "Re-run risk analysis" : "Identify key risks");
  runBtn.addEventListener("click", async () => {
    try { await busy(runBtn, "The AI is identifying material risks...", () => api("POST", `/deals/${deal.deal_id}/section4/run`)); await rerender(); } catch (e) { }
  });
  const st = deal.sections.s4;
  const head = h("div", { class: "card" },
    h("p", {}, "Uses the approved Section 3 analysis, the extracted business and debt information and the loan request."),
    h("div", { class: "row" }, runBtn, deal.s3_approved ? null : tag("Section 3 approval is required first", "warn")),
    st.status === "stale" ? h("p", { class: "tag warn" }, "Out of date: an earlier section changed. Re-run the risk analysis.") : null,
    st.last_error ? h("details", {}, h("summary", {}, "Last run failed"), h("ul", {}, st.last_error.map((x) => h("li", {}, x)))) : null);
  const body = [];
  body.push(h("p", { class: "disclaimer" }, "Suggestions for the analyst's consideration only, not automatic lending decisions."));
  if (s4.risks) {
    body.push(h("table", {}, h("thead", {}, h("tr", {}, ["Identified Risk", "Evidence", "Possible Mitigant", "Proposed Term / Monitoring Condition"].map((x) => h("th", { scope: "col" }, x)))),
      h("tbody", {}, s4.risks.length ? s4.risks.map((r) => h("tr", {},
        h("td", {}, h("b", {}, `${r.rank}. ${r.identified_risk}`), h("div", { class: "small" }, r.category), h("div", {}, tag(`Impact: ${r.impact}`, r.impact === "High" ? "bad" : "warn"), " ", tag(`Likelihood: ${r.likelihood}`, "info")), h("code", { class: "small" }, r.risk_id)),
        h("td", {}, h("div", {}, r.evidence.text), h("div", { class: "meta" }, r.evidence.refs.map((x) => evButton(x, null, sourceDialog))),
          tag(r.verification.mark, r.verification.mark === "Numbers verified" ? "ok" : "bad"),
          r.verification.unmatched.length ? h("div", { class: "unmatched" }, "Not matched: " + r.verification.unmatched.map((u) => u.value).join(", ")) : null,
          h("div", { class: "small muted" }, "Time horizon: ", r.time_horizon),
          r.business_context ? h("div", { class: "small" }, "Context: ", r.business_context.text, " ", r.business_context.refs.map((x) => evButton(x, null, sourceDialog))) : null),
        h("td", {}, h("ul", {}, r.mitigants.map((m) => h("li", {}, m)))),
        h("td", {}, h("ul", {}, r.terms.map((t) => h("li", {}, tag(t.term_type, "info"), " ", t.text, " ", tag(t.label, labelKind(t.label)))))))) :
        h("tr", {}, h("td", { colspan: 4 }, "No risks supported by the evidence provided.")))));
    if (s4.limitations.length) body.push(h("h4", {}, "Limitations"), h("ul", {}, s4.limitations.map((l) => h("li", {}, l))));
  } else body.push(h("p", { class: "empty" }, "Not run yet."));
  $main.replaceChildren(h("h2", {}, "Section 4: Identify key risks and suggest mitigants"), head, h("div", { class: "card" }, body),
    h("p", {}, h("a", { href: `#/deal/${deal.deal_id}/memo` }, "Next: Section 5 credit memo")));
}

// --------------------------------------------------------------------------- Sections 5 and 6
function memoStatement(st, review, openSource) {
  const box = h("div", { class: `stmt ${st.status}${state.activeStatement === st.id ? " active" : ""}`, id: `m-${st.id}` });
  box.append(h("div", {}, st.text),
    h("div", { class: "meta" }, h("code", {}, st.id), tag(st.label, labelKind(st.label)), tag(st.status, statusKind(st.status)),
      tag(st.verification.mark, st.verification.mark === "Numbers verified" ? "ok" : "bad"),
      st.source === "backend" ? tag("Backend-generated", "muted") : null,
      st.refs.length ? st.refs.map((r) => evButton(r, st.id, openSource)) : h("span", { class: "muted" }, "No references")));
  if (st.note) box.append(h("div", { class: "small", style: "margin-top:4px" }, "Note: ", st.note));
  if (st.verification.unmatched.length) box.append(h("div", { class: "unmatched" }, "Not matched: " + st.verification.unmatched.map((u) => `${u.value} (${u.reason})`).join("; ")));
  if (st.text !== st.original_text) box.append(h("div", { class: "small muted" }, "Corrected. AI original: ", st.original_text));
  if (review && state.status.support_check_enabled) {
    box.append(h("div", { class: "small", style: "margin-top:4px" }, st.support ? [tag(st.support.assessment, st.support.assessment === "Supported" ? "ok" : st.support.assessment === "Not supported" ? "bad" : "warn"),
      " ", st.support.reason, " ", h("span", { class: "muted" }, "(AI preliminary check; analyst verification required)")] : h("span", { class: "muted" }, "AI support check: Not checked")));
  }
  if (!review) return box;
  const act = async (action, text, btn) => {
    if (needName()) return;
    try {
      await busy(btn, "Saving...", () => api("POST", `/deals/${state.deal.deal_id}/memo/statements/${st.id}/action`, { action, analyst_name: analyst(), text }));
      state.activeStatement = st.id;
      announce(`${st.id}: ${action} saved`);
      await rerender();
      document.querySelector(`#m-${st.id} button`)?.focus();
    } catch (e) { }
  };
  const editor = (kind) => {
    const ta = h("textarea", { "aria-label": kind === "correct" ? `Correct ${st.id}` : `Flag note for ${st.id}`, maxlength: kind === "correct" ? 2000 : 500 }, kind === "correct" ? st.text : "");
    const save = h("button", { type: "button", class: "small" }, kind === "correct" ? "Save correction" : "Flag with note");
    save.addEventListener("click", () => act(kind === "correct" ? "correct" : "flag", ta.value, save));
    const ed = h("div", { class: "editor" }, ta, h("div", { class: "row" }, save, h("button", { type: "button", class: "small secondary", onclick: () => ed.remove() }, "Cancel")));
    box.querySelector(".editor")?.remove(); box.append(ed); ta.focus();
  };
  const ap = h("button", { type: "button", class: "small" }, "Approve"); ap.addEventListener("click", () => act("approve", null, ap));
  box.append(h("div", { class: "actions" }, ap,
    h("button", { type: "button", class: "small secondary", onclick: () => editor("flag") }, "Flag"),
    h("button", { type: "button", class: "small secondary", onclick: () => editor("correct") }, "Correct")));
  return box;
}

function memoBody(s5, review, openSource, filter = "All") {
  const sections = [];
  const bySection = {};
  s5.statements.forEach((s) => ((bySection[s.section] = bySection[s.section] || []).push(s)));
  for (const num of Object.keys(bySection).map(Number).sort((a, b) => a - b)) {
    const sts = bySection[num].filter((s) => filter === "All" || s.status === filter);
    if (!sts.length) continue;
    const subs = [];
    let current = null;
    for (const s of sts) {
      if (s.subsection !== current) { subs.push(h("h4", {}, s.subsection_title)); current = s.subsection; }
      subs.push(memoStatement(s, review, openSource));
    }
    sections.push(h("section", { class: "memo-section" }, h("h3", {}, `${num}. ${bySection[num][0].section_title}`), subs));
  }
  return sections.length ? sections : [h("p", { class: "empty" }, "No statements match this filter.")];
}

async function screenMemo() {
  const deal = state.deal;
  const s5 = await api("GET", `/deals/${deal.deal_id}/section5`);
  const runBtn = h("button", { type: "button", disabled: deal.sections.s4.status !== "completed" }, s5.statements ? "Regenerate memo" : "Generate credit memo");
  runBtn.addEventListener("click", async () => {
    if (s5.statements && !window.confirm("Regenerating replaces the memo and resets all Section 6 reviews. Continue?")) return;
    try { await busy(runBtn, "The AI is writing the memo; the backend is checking every reference and figure...", () => api("POST", `/deals/${deal.deal_id}/section5/run`)); await rerender(); } catch (e) { }
  });
  const st = deal.sections.s5;
  $main.replaceChildren(h("h2", {}, "Section 5: Credit memo with evidence"),
    h("div", { class: "card" }, h("p", {}, "The memo uses only Sections 1-4 and cites existing Evidence IDs. Information gaps and flagged database values are added by the backend. There is no AI recommendation; the analyst decides."),
      h("div", { class: "row" }, runBtn, deal.sections.s4.status === "completed" ? null : tag("Section 4 must be completed first", "warn"),
        s5.statements ? h("a", { href: `#/deal/${deal.deal_id}/review` }, "Go to Section 6 review") : null),
      st.status === "stale" ? h("p", { class: "tag warn" }, "Out of date: an earlier section changed. Regenerate the memo.") : null,
      st.last_error ? h("details", {}, h("summary", {}, "Last run failed"), h("ul", {}, st.last_error.map((x) => h("li", {}, x)))) : null),
    s5.statements ? h("div", { class: "card" }, memoBody(s5, false, (id) => sourceDialog(id))) : h("p", { class: "empty" }, "No memo yet."));
}

async function screenReview() {
  const deal = state.deal;
  const s5 = await api("GET", `/deals/${deal.deal_id}/section5`);
  if (!s5.statements) {
    $main.replaceChildren(h("h2", {}, "Section 6: Analyst review and source verification"), h("p", { class: "empty" }, "Generate the memo in Section 5 first."));
    return;
  }
  const sourcePanel = h("div", { class: "card source-panel", "aria-live": "polite" }, h("h3", {}, "Source"), h("p", { class: "muted" }, "Select an Evidence ID on a statement to see its source here."));
  const openSource = async (evId, sid) => {
    state.activeStatement = sid;
    document.querySelectorAll(".stmt.active").forEach((e) => e.classList.remove("active"));
    document.getElementById(`m-${sid}`)?.classList.add("active");
    const before = s5.statements.find((s) => s.id === sid)?.status;
    await renderSource(sourcePanel, evId, sid);
    state.lastSource = evId;
    const fresh = await api("GET", `/deals/${deal.deal_id}/section5`);
    const after = fresh.statements.find((s) => s.id === sid)?.status;
    if (before !== after) { toast(`${sid} was flagged automatically: the source could not be located.`); await rerender(); }
  };
  if (state.lastSource) renderSource(sourcePanel, state.lastSource, null);
  const counts = { All: s5.statements.length, Pending: 0, Approved: 0, Flagged: 0 };
  s5.statements.forEach((s) => counts[s.status]++);
  const filters = h("div", { class: "row filters", role: "group", "aria-label": "Filter statements by status" },
    ["All", "Pending", "Approved", "Flagged"].map((f) => h("button", { type: "button", class: "small", "aria-pressed": String(state.reviewFilter === f),
      onclick: async () => { state.reviewFilter = f; await rerender(); } }, `${f} (${counts[f]})`)));
  const memoBtn = h("button", { type: "button" }, "Download final Credit Memo PDF");
  memoBtn.addEventListener("click", () => { if (!needName()) download(`/deals/${deal.deal_id}/exports/memo`, { analyst_name: analyst() }, memoBtn).catch(() => null); });
  const auditBtn = h("button", { type: "button", class: "secondary" }, "Download Audit Trail PDF");
  auditBtn.addEventListener("click", () => download(`/deals/${deal.deal_id}/exports/audit`, {}, auditBtn).catch(() => null));
  const tools = h("div", { class: "row" }, memoBtn, auditBtn,
    counts.Pending ? tag(`${counts.Pending} statement(s) still Pending: the final memo needs every statement Approved or Flagged`, "warn") : tag("Review complete", "ok"));
  if (state.status.support_check_enabled) {
    const sc = h("button", { type: "button", class: "secondary" }, "Run AI support check");
    sc.addEventListener("click", async () => { try { await busy(sc, "Running the advisory support check...", () => api("POST", `/deals/${deal.deal_id}/support-check/run`)); await rerender(); } catch (e) { } });
    tools.append(sc);
  }
  $main.replaceChildren(h("h2", {}, "Section 6: Analyst review and source verification"),
    h("p", { class: "disclaimer" }, "A citation to an existing page does not confirm accuracy. Compare the statement with the source before approving."),
    h("div", { class: "card" }, tools, h("div", { style: "margin-top:10px" }, filters)),
    h("div", { class: "review" }, h("div", { class: "card" }, memoBody(s5, true, openSource, state.reviewFilter)), sourcePanel));
}

// --------------------------------------------------------------------------- app lifetime
// The backend stops itself when no tab has the app open, so closing the tab closes everything.
let backendGone = false;
function showStopped() {
  if (backendGone) return;
  backendGone = true;
  const n = document.getElementById("notice");
  n.textContent = "The app has stopped. Double-click start.bat to open it again.";
  n.style.background = "#fde7e7"; n.style.color = "#9c1c1c";
}
const beat = () => fetch("/api/heartbeat", { method: "POST" }).then((r) => { if (!r.ok) throw new Error(); }).catch(showStopped);
beat();
setInterval(beat, 10000);
window.addEventListener("pagehide", () => navigator.sendBeacon("/api/closing"));
document.getElementById("close-app").addEventListener("click", async () => {
  if (!window.confirm("Close the app? The backend stops and any AI step still running is cancelled. Saved work is kept.")) return;
  try { await fetch("/api/shutdown", { method: "POST" }); } catch (e) { }
  backendGone = true;
  document.body.replaceChildren(h("main", { style: "padding:40px;font:16px 'Segoe UI',sans-serif" },
    h("h1", {}, "The app has been closed."),
    h("p", {}, "You can close this browser tab. To open the app again, double-click start.bat.")));
  window.close();
});

// --------------------------------------------------------------------------- start
$name.value = localStorage.getItem("analystName") || "";
$name.addEventListener("input", () => localStorage.setItem("analystName", $name.value));
window.addEventListener("hashchange", route);
loadStatus().then(route).catch((e) => { $main.replaceChildren(h("p", {}, "Could not reach the backend: " + e.message)); });
