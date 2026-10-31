// AI-Assisted Credit Analysis - browser app (vanilla JS, no build step).
// All AI/document text is inserted with textContent (never innerHTML) to avoid script injection.

const $main = document.getElementById("main");
const $nav = document.getElementById("steps");
const $name = document.getElementById("analyst-name");
const state = { status: null, deal: null, charts: [], reviewFilter: "All", activeStatement: null,
  attentionOnly: localStorage.getItem("attentionOnly") === "1", s3Tab: "trends", showMore: {} };

const STEPS = [
  ["intake", "1. Deal intake & data"],
  ["extraction", "2. Extraction"],
  ["dashboard", "3. Financial dashboard"],
  ["risks", "4. Risks & mitigants"],
  ["memo", "5. Credit memo"],
  ["review", "6. Review & export"],
];
const UNIT_LABEL = { percent: "Percent (%)", multiple: "Multiple (x)", days: "Days", amount: "Amount (unit not stated in database)" };
const unitLabel = (unit, amountUnit) => (unit === "amount" && amountUnit ? `Amount (${amountUnit})` : UNIT_LABEL[unit] || unit);
// Navy + gold led palette; later colours stay in the same cool/warm family so multi-line charts read as one set.
const PALETTE = ["#0f2d4e", "#c79214", "#4a7aa7", "#9c6b1f", "#6b8f9c"];

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
// Sleek, consistent display of the raw backend label (matches the PDF's title-case wording).
const labelText = (l) => ({ Sourced: "Sourced", ASSUMPTION: "Assumption", "NOT VERIFIED": "Not verified" }[l] || l);
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
    msg += "\n" + d.slice(0, 12).map((x) => "- " + (typeof x === "string" ? x : x.reason ? `${x.position ? `${x.position} (${x.statement_id})` : x.statement_id}: ${x.reason}` : JSON.stringify(x))).join("\n");
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

function nextSection(dealId, screen, label = "Next Section") {
  return h("nav", { class: "next-nav", "aria-label": "Section navigation" },
    h("a", { class: "button-link next-btn", href: `#/deal/${dealId}/${screen}` }, label, h("span", { class: "next-arrow", "aria-hidden": "true" }, "\u2192")));
}

// --------------------------------------------------------------------------- decluttering helpers
// A statement needs the analyst's attention while Pending, or while it has a number mismatch that is not Flagged
// (approving does not clear a mismatch).
const needsAttention = (s) => s.status === "Pending" || (s.verification && s.verification.mark === "Number mismatch" && s.status !== "Flagged");
const isDone = (s) => !needsAttention(s);

// One-sentence intro; the longer explanation sits behind "How this works".
function lead(text, ...more) {
  return h("div", { class: "lead" }, h("p", {}, text),
    more.length ? h("details", { class: "howto" }, h("summary", {}, "How this works"),
      h("div", { class: "howto-body" }, more.filter(Boolean).map((m) => (typeof m === "string" ? h("p", {}, m) : m)))) : null);
}

// The single "what to do now" bar at the top of each section. kind: todo | ok | warn | blocked
function nextStep(kind, text, ...actions) {
  const icon = { todo: "\u2192", ok: "\u2713", warn: "!", blocked: "\u2715" }[kind] || "\u2192";
  return h("div", { class: `next-step ${kind}` }, h("span", { class: "ns-icon", "aria-hidden": "true" }, icon),
    h("div", { class: "ns-text" }, text), h("div", { class: "ns-actions" }, actions.filter(Boolean)));
}

// Hides everything already reviewed inside containers marked .attn-scope (CSS), without re-rendering.
function attentionToggle(n) {
  const label = () => (state.attentionOnly ? `Show everything` : `Show only what needs attention (${n})`);
  const b = h("button", { type: "button", class: "small secondary", "aria-pressed": String(state.attentionOnly) }, label());
  b.addEventListener("click", () => {
    state.attentionOnly = !state.attentionOnly;
    localStorage.setItem("attentionOnly", state.attentionOnly ? "1" : "0");
    $main.classList.toggle("attention-only", state.attentionOnly);
    b.setAttribute("aria-pressed", String(state.attentionOnly));
    b.textContent = label();
    announce(state.attentionOnly ? "Showing only items that need attention" : "Showing everything");
  });
  return b;
}

// Only badges that ask for attention; a quiet tick when the numbers check out.
function stmtBadges(st) {
  const out = [];
  if (st.status === "Pending") out.push(tag("Pending", "warn"));
  if (st.status === "Flagged") out.push(tag("Flagged", "bad"));
  if (st.verification && st.verification.mark === "Number mismatch") out.push(tag("Number mismatch", "bad"));
  else if (st.verification) out.push(h("span", { class: "ok-mark", title: "Python matched every figure to its source" }, "\u2713 numbers verified"));
  if (st.label !== "Sourced") out.push(tag(labelText(st.label), labelKind(st.label)));
  if (st.source === "backend") out.push(tag("Backend-generated", "muted"));
  return out;
}

function stmtRef(st) {
  return h("span", { class: "stmt-ref", title: st.position_path || "Short ID used in the audit trail" },
    st.position ? `${st.position} \u00b7 ` : "", st.id);
}

// Evidence IDs folded into "N sources"; open = show the chips straight away.
function sourceList(refs, sid, onOpen, open = false) {
  if (!refs.length) return h("span", { class: "small muted" }, "No references");
  return h("details", { class: "srcs", open: open || null },
    h("summary", {}, `${refs.length} source${refs.length > 1 ? "s" : ""}`), h("span", { class: "srcs-list" }, refs.map((r) => evButton(r, sid, onOpen))));
}

// Primary action stays visible; the rest go in a "More" menu. more: [[label, (button) => ...], ...]
function actionBar(primary, more, hint) {
  const menu = more.length ? h("details", { class: "more-menu" }, h("summary", { "aria-label": "More actions" }, "More \u25be"),
    h("div", { class: "more-list" }, more.map(([label, fn]) => {
      const b = h("button", { type: "button", class: "small secondary" }, label);
      b.addEventListener("click", () => fn(b));
      return b;
    }))) : null;
  return h("div", { class: "actions" }, primary, menu, hint ? h("span", { class: "small muted" }, hint) : null);
}

// Approved, nothing outstanding: shown as one line that expands. Otherwise a normal card.
function stmtShell(st, idPrefix) {
  const collapse = st.status === "Approved" && isDone(st);
  const cls = `stmt ${st.status}${isDone(st) ? " done" : ""}${state.activeStatement === st.id ? " active" : ""}${collapse ? " collapsed" : ""}`;
  if (!collapse) return { box: h("div", { class: cls, id: `${idPrefix}${st.id}` }, h("div", { class: "stmt-text" }, st.text)), collapse };
  return { box: h("details", { class: cls, id: `${idPrefix}${st.id}` },
    h("summary", { class: "stmt-sum" }, h("span", { class: "tick", "aria-label": "Approved" }, "\u2713"), h("span", { class: "clamp" }, st.text))), collapse };
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
    case "intake": return `${deal.documents.length} document(s)`;
    case "extraction": {
      const fin = deal.financial.status === "connected" || deal.financial.status === "loaded" ? "database connected" : deal.financial.status === "error" ? "database error" : "database not connected";
      return `2A ${s.s2a.status.replace("_", " ")}, 2B ${s.s2b.status.replace("_", " ")}, ${fin}`;
    }
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
  $main.classList.toggle("attention-only", state.attentionOnly);
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  try {
    if (parts[0] === "deal" && parts[1]) {
      state.deal = await api("GET", `/deals/${parts[1]}`);
      const screen = parts[2] || "intake";
      if (screen === "dashboard" && parts[3]) state.s3Tab = parts[3];  // e.g. #/deal/<id>/dashboard/repayment
      renderNav(screen);
      await ({ intake: screenIntake, extraction: screenExtraction, dashboard: screenDashboard, risks: screenRisks,
        memo: screenMemo, review: screenReview }[screen] || screenIntake)();
    } else if (parts[0] === "new") {
      state.deal = null; renderNav("new"); screenNewDeal();
    } else if (parts[0] === "edit" && parts[1]) {
      state.deal = null; renderNav("new"); await screenEditDeal(parts[1]);
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
  const deleteDeal = async (d, btn) => {
    if (!window.confirm(`Delete the deal for "${d.borrower}"?\n\nThis permanently removes its documents, extracted evidence, analysis, memo and audit trail. This cannot be undone.`)) return;
    try {
      await busy(btn, "Deleting...", () => api("DELETE", `/deals/${d.deal_id}`));
      toast(`Deal for "${d.borrower}" deleted.`, true);
      await screenHome();
    } catch (e) { /* toast shown */ }
  };
  const rows = deals.map((d) => h("tr", {},
    h("td", {}, h("a", { href: `#/deal/${d.deal_id}/intake` }, d.borrower)),
    h("td", {}, d.facility_type),
    h("td", {}, d.created_at.replace("T", " ").slice(0, 16)),
    h("td", { class: "actions-cell" },
      h("a", { href: `#/edit/${d.deal_id}`, class: "button-link small-link" }, "Edit"),
      h("button", { type: "button", class: "small danger", onclick: (ev) => deleteDeal(d, ev.currentTarget) }, "Delete"))));
  $main.replaceChildren(
    h("h2", {}, "Credit analyses"),
    h("div", { class: "row" }, h("a", { href: "#/new", class: "button-link" }, "Start a new deal")),
    h("div", { class: "card", style: "margin-top:12px" },
      deals.length ? h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Borrower"), h("th", {}, "Facility"), h("th", {}, "Created"), h("th", {}, "Actions"))),
        h("tbody", {}, rows))
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

function dealForm(values, submitLabel, onSubmit) {
  const v = values || {};
  const inp = (id, attrs = {}) => h("input", { id: `f-${id}`, name: id, type: "text", value: v[id] ?? "", ...attrs });
  const ta = (id, attrs = {}) => h("textarea", { id: `f-${id}`, name: id, ...attrs }, v[id] ?? "");
  const form = h("form", { class: "card", novalidate: true },
    h("div", { class: "grid2" },
      field("f-borrower", "Borrower / company name *", inp("borrower", { required: true, maxlength: 200 })),
      field("f-facility_type", "Facility type *", inp("facility_type", { required: true, maxlength: 100, list: "facility-types", placeholder: "e.g. Term loan" })),
      field("f-amount", "Requested amount *", inp("amount", { required: true, inputmode: "decimal", placeholder: "e.g. 500000000" }), "Numbers only, up to 2 decimals"),
      field("f-currency", "Currency *", inp("currency", { required: true, maxlength: 3 }), "3-letter code"),
      field("f-tenor", "Tenor *", inp("tenor", { required: true, maxlength: 100, placeholder: "e.g. 5 years" }))),
    h("datalist", { id: "facility-types" }, ["Term loan", "Revolving credit facility", "Bridge loan", "Syndicated loan", "Trade finance line"].map((x) => h("option", { value: x }))),
    h("div", { class: "grid2", style: "margin-top:12px" },
      field("f-purpose", "Purpose of loan *", ta("purpose", { required: true, maxlength: 2000 })),
      field("f-repayment", "Repayment structure *", ta("repayment", { required: true, maxlength: 2000, placeholder: "e.g. Bullet at maturity / quarterly amortisation" })),
      field("f-collateral", "Collateral / security (optional)", ta("collateral", { maxlength: 2000 }), "Left blank = \"None provided\"")),
    h("div", { class: "row", style: "margin-top:14px" }, h("button", { type: "submit" }, submitLabel),
      h("a", { href: "#/", class: "button-link secondary-link" }, "Cancel")));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    const missing = ["borrower", "facility_type", "amount", "currency", "purpose", "tenor", "repayment"]
      .filter((k) => !String(data[k] || "").trim()).map((k) => ({ field: k, reason: "This field is required" }));
    if (missing.length) { showFieldErrors(form, missing); return; }
    try { await onSubmit(data); }
    catch (e) { showFieldErrors(form, e.body?.fields); toast(errText(e)); }
  });
  return form;
}

function screenNewDeal() {
  const form = dealForm({ borrower: "Intel Corporation", currency: "USD" }, "Create deal", async (data) => {
    const deal = await api("POST", "/deals", data);
    location.hash = `#/deal/${deal.deal_id}/intake`;
  });
  $main.replaceChildren(h("h2", {}, "Section 1: Deal intake"),
    h("p", {}, "Enter the loan request. The analysis assesses whether the borrower can support this specific request."), form);
}

async function screenEditDeal(dealId) {
  const deal = await api("GET", `/deals/${dealId}`);
  const i = deal.intake;
  const values = {
    borrower: i["DI-BORROWER"].display,
    facility_type: i["DI-FACILITY_TYPE"].display,
    amount: i["DI-AMOUNT"].amount,
    currency: i["DI-AMOUNT"].currency,
    tenor: i["DI-TENOR"].display,
    purpose: i["DI-PURPOSE"].display,
    repayment: i["DI-REPAYMENT"].display,
    collateral: i["DI-COLLATERAL"].display === "None provided" ? "" : i["DI-COLLATERAL"].display,
  };
  const form = dealForm(values, "Save changes", async (data) => {
    await api("PUT", `/deals/${dealId}`, data);
    toast("Deal updated.", true);
    location.hash = `#/deal/${dealId}/intake`;
  });
  $main.replaceChildren(h("h2", {}, "Edit deal"),
    h("p", {}, "Update the loan request. Changing the borrower re-connects the financial database; any analysis already run will be marked out of date so you can re-run it."),
    form);
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

  const fin = deal.financial.status;
  const step = !deal.documents.length
    ? nextStep("todo", "Upload the borrower's filings (10-K, 10-Q, annual report) as PDFs below.")
    : fin === "error"
      ? nextStep("warn", `Documents uploaded, but the financial database could not be connected: ${deal.financial.error || "unknown error"}`,
        h("a", { class: "button-link", href: `#/deal/${deal.deal_id}/extraction` }, "Fix in Section 2"))
      : nextStep("ok", `${deal.documents.length} document${deal.documents.length > 1 ? "s" : ""} uploaded and the financial database is connected. Next: run the extraction.`,
        h("a", { class: "button-link", href: `#/deal/${deal.deal_id}/extraction` }, "Go to Section 2"));
  $main.replaceChildren(
    h("h2", {}, "Section 1: Deal intake and data"),
    step,
    h("details", { class: "card", open: !deal.documents.length || null }, h("summary", {}, h("b", {}, "Loan request"), " ",
      h("span", { class: "small muted" }, `${deal.intake["DI-FACILITY_TYPE"].display}, ${deal.intake["DI-AMOUNT"].display}, ${deal.intake["DI-TENOR"].display}`)),
      h("div", { style: "margin-top:10px" }, intakeTable),
      h("p", { class: "small" }, h("a", { href: `#/edit/${deal.deal_id}` }, "Edit the loan request"))),
    h("div", { class: "card" }, h("h3", {}, "Documents"), docTable, h("details", { class: "upload", open: !deal.documents.length || null },
      h("summary", {}, "Upload a document"), h("div", { style: "margin-top:10px" }, upForm))),
    nextSection(deal.deal_id, "extraction"));
}

// --------------------------------------------------------------------------- Section 2C: financial database display (auto-connected)
function reconnectButton(deal) {
  const b = h("button", { type: "button", class: "secondary" }, "Reconnect financial database");
  b.addEventListener("click", async () => {
    if (needName()) return;
    if (!window.confirm("Re-read the financial database for this borrower?\n\nUse this after the workbook has been updated. Saved forecast assumptions are reset, and Sections 3-5 are marked out of date.")) return;
    try {
      const d = await busy(b, "Reconnecting...", () => api("POST", `/deals/${deal.deal_id}/financial/reconnect`, { analyst_name: analyst() }));
      toast(d.financial.status === "connected" ? "Financial database reconnected." : `Could not connect: ${d.financial.error}`, d.financial.status === "connected");
      await rerender();
    } catch (e) { }
  });
  return b;
}

async function financialCard(deal) {
  const fin = deal.financial || {};
  if (fin.status === "error") {
    return h("div", { class: "card" }, h("h3", {}, "2C Financial data (external database)"),
      h("p", { class: "tag bad" }, `Could not connect to the financial database${fin.file_name ? ` (${fin.file_name})` : ""}: ${fin.error || "unknown error"}`),
      h("p", { class: "small muted" }, "The connection is attempted automatically when the deal is created or the borrower is changed. Check the borrower name (Edit deal) and the database file, then reconnect."),
      reconnectButton(deal));
  }
  if (fin.status !== "connected" && fin.status !== "loaded") {
    return h("div", { class: "card" }, h("h3", {}, "2C Financial data (external database)"),
      h("p", { class: "empty" }, "The financial database is not connected for this deal."), reconnectButton(deal));
  }
  const ds = await api("GET", `/deals/${deal.deal_id}/financial`);
  // Connected: a one-line summary that opens to the detail (the figures are reviewed in Section 3).
  return h("details", { class: "card" },
    h("summary", {}, h("b", {}, "2C Financial data"), " ", h("span", { class: "ok-mark" }, "\u2713 connected"), " ",
      h("span", { class: "small muted" }, `${ds.company || ""}${ds.sheet ? ` (sheet ${ds.sheet})` : ""}, ${ds.metrics.length} metrics, ${ds.periods.length} quarters, ${ds.flagged_values.length} values flagged`)),
    h("p", { style: "margin-top:10px" }, "Fetched automatically from ", h("b", {}, fin.file_name || ds.file_name),
      ". Values are the database's own figures and ratios, exactly as the workbook defines them; nothing is calculated or extracted by the AI."),
    ds.company ? h("p", { class: "small" }, `Amounts in ${ds.currency_unit || "units not stated"}. Companies in the database: ${(ds.companies_in_database || []).join(", ")}.`) : null,
    ds.calculation_note ? h("p", { class: "small muted" }, ds.calculation_note) : null,
    h("p", { class: "small" }, `Periods (oldest to newest): ${ds.periods.map((p) => p.label + (p.calendar_quarter ? ` (${p.calendar_quarter})` : "")).join(", ")}.`),
    h("div", { class: "row" }, reconnectButton(deal)),
    h("h4", {}, `Values flagged for review (${ds.flagged_values.length})`),
    ds.flagged_values.length ? h("table", {}, h("thead", {}, h("tr", {}, ["Evidence ID", "Metric", "Period", "Value", "Flags"].map((x) => h("th", {}, x)))),
      h("tbody", {}, ds.flagged_values.map((f) => h("tr", {}, h("td", {}, h("code", {}, f.evidence_id)), h("td", {}, f.metric), h("td", {}, f.period),
        h("td", {}, f.display), h("td", {}, f.flags.map((x) => tag(x, "warn"))))))) : h("p", {}, "None."),
    h("h4", {}, "Information gaps"),
    ds.information_gaps.length ? h("ul", {}, ds.information_gaps.map((g) => h("li", {}, g))) : h("p", {}, "None."));
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
      row("Evidence ID", s.evidence_id); row("Source", `Financial database: ${s.file_name}${s.cell ? `, cell ${s.cell}` : ""}`); row("Metric (as in the database)", s.metric_label);
      row("Period column", s.column_header); row("Value", s.display + (s.unit_label ? ` ${s.unit_label}` : ""));
      if (s.formula) row("Workbook formula", h("code", {}, "=" + s.formula));
      if (s.basis) row("Basis (company-specific)", s.basis);
      row("Anomaly flags", s.flags.join(", "));
      container.replaceChildren(h("h3", {}, `Source for ${evId}`), h("table", {}, h("tbody", {}, rows)));
    } else if (s.type === "forecast" || s.type === "forecast_assumption" || s.type === "forecast_threshold") {
      row("Evidence ID", s.evidence_id);
      row("Source", s.type === "forecast" ? "Backend forecast (Python), calculated from the database and the assumptions below"
        : s.type === "forecast_threshold" ? "Threshold entered by the analyst" : "Forecast assumption");
      row("Detail", s.description);
      const st = s.assumptions_status || {};
      row("Assumptions", st.state === "saved" ? `Saved by ${st.saved_by} at ${st.saved_at}` : "Database-average defaults (not saved by the analyst)");
      if (s.assumptions) row("Scenario assumptions", h("ul", { style: "margin:0;padding-left:18px" }, s.assumptions.map((a) => h("li", {}, `${a.label}: ${a.display} (${a.source})`))));
      container.replaceChildren(h("h3", {}, `Source for ${evId}`), h("p", { class: "disclaimer" }, "A forecast is a projection from stated assumptions, not a reported result."),
        h("table", {}, h("tbody", {}, rows)));
    } else if (s.type === "deal_intake") {
      row("Evidence ID", s.evidence_id); row("Source", "Deal intake (entered by the analyst)"); row(s.label, s.value);
      container.replaceChildren(h("h3", {}, `Source for ${evId}`), h("table", {}, h("tbody", {}, rows)));
    } else {
      row("Evidence ID", s.evidence_id); row("Document", `${s.doc_id} ${s.doc_name}`); row("Page", String(s.page)); row("Section", s.section_heading);
      row("Generated Statement", s.statement); row("Extracted Text", `\u201c${s.excerpt}\u201d`);
      row("Passage on page", s.location_status === "Located" ? tag("Located (highlighted below)", "ok") : tag(s.location_status, "bad"));
      container.replaceChildren(h("h3", {}, `Source for ${evId}`), h("table", {}, h("tbody", {}, rows)),
        s.image ? h("img", { src: s.image, alt: `Page ${s.page} of ${s.doc_name}${s.location_status === "Located" ? " with the extracted text highlighted" : ""}`, style: "margin-top:10px" })
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
  const s2Action = async (evId, action, text, btn) => {
    if (needName()) return;
    try {
      await busy(btn, "Saving...", () => api("POST", `/deals/${deal.deal_id}/section2/evidence/${encodeURIComponent(evId)}/action`, { action, analyst_name: analyst(), text }));
      announce(`${evId} ${action} saved`);
      await rerender();
    } catch (e) { /* shown */ }
  };
  const s2EvRow = (f, e, id, showLabel) => {
    const located = e.location_status === "Located";
    const actions = h("td", { class: "s2-actions" });
    const st = e.status || "Pending";
    const tr = h("tr", { class: st === "Pending" || !located ? "" : "done" },
      h("td", {}, showLabel ? f.label : ""),
      h("td", {}, evButton(id, null, sourceDialog)),
      h("td", { class: "stmt-cell" }, h("div", {}, e.statement),
        e.original_statement && e.statement !== e.original_statement ? h("div", { class: "small muted" }, "Edited. AI original: ", e.original_statement) : null,
        e.status === "Flagged" && e.note ? h("div", { class: "flag-note" }, "Flag note: ", e.note) : null),
      h("td", {}, e.doc_name),
      h("td", {}, String(e.page)),
      h("td", {}, located ? h("span", { class: "ok-mark", title: "The extracted text was found on the cited page" }, "\u2713 found") : tag("Not found: check", "bad"),
        e.issues && e.issues.length ? h("div", { class: "small muted", style: "margin-top:2px" }, e.issues.join("; ")) : null),
      h("td", {}, st === "Approved" ? h("span", { class: "ok-mark" }, "\u2713 Approved") : tag(st, statusKind(st))),
      actions);
    const editor = (kind) => {
      actions.querySelector(".editor")?.remove();
      const ta = h("textarea", { "aria-label": kind === "edit" ? `Edit ${id}` : `Flag note for ${id}`, maxlength: kind === "edit" ? 2000 : 500 }, kind === "edit" ? e.statement : "");
      const save = h("button", { type: "button", class: "small" }, kind === "edit" ? "Save edit" : "Flag with note");
      save.addEventListener("click", (ev) => s2Action(id, kind === "edit" ? "edit" : "flag", ta.value, ev.currentTarget));
      const ed = h("div", { class: "editor" }, ta, h("div", { class: "row" }, save, h("button", { type: "button", class: "small secondary", onclick: () => ed.remove() }, "Cancel")));
      actions.append(ed); ta.focus();
    };
    const primary = [];
    if (st !== "Approved") {
      const ap = h("button", { type: "button", class: "small" }, "Approve");
      ap.addEventListener("click", (ev) => s2Action(id, "approve", null, ev.currentTarget));
      primary.push(ap);
    }
    const more = [...(st !== "Flagged" ? [["Flag", () => editor("flag")]] : []), ["Edit", () => editor("edit")]];
    actions.append(actionBar(primary, more));
    return tr;
  };
  const group = (scope, title, key) => {
    const s2 = data.s2[scope];
    const st = sec[key];
    const head = h("div", { class: "row" }, h("h3", { style: "margin:0" }, title), tag(st.status.replace("_", " "), st.status === "completed" ? "ok" : st.status === "stale" ? "warn" : "muted"));
    if (st.last_error) head.append(tag("Last run failed", "bad"));
    if (!s2) return h("div", { class: "card" }, head, h("p", { class: "empty" }, "Not run yet."));
    const rows = [];
    for (const f of s2.fields) {
      const ids = f.evidence_ids;
      if (!ids.length) rows.push(h("tr", {}, h("td", {}, f.label), h("td", {}, "None"), h("td", { colspan: 6 }, tag("Not available", "muted"))));
      ids.forEach((id, i) => {
        const e = data.evidence[id];
        if (!e) return;
        rows.push(s2EvRow(f, e, id, i === 0));
      });
      if (f.rejected.length) rows.push(h("tr", {}, h("td", {}), h("td", { colspan: 7 }, h("details", {}, h("summary", {}, `${f.rejected.length} rejected item(s) for ${f.label}`),
        h("ul", {}, f.rejected.map((r) => h("li", {}, `${r.statement} (${r.doc_id} p.${r.page}): ${r.reason}`)))))));
    }
    const cols = ["13%", "9%", "30%", "12%", "5%", "9%", "8%", "14%"].map((w) => h("col", { style: `width:${w}` }));
    return h("div", { class: "card attn-scope" }, head,
      s2.message ? h("p", { class: "tag warn" }, s2.message) : null,
      h("div", { class: "table-wrap" },
        h("table", { class: "s2-table" }, h("colgroup", {}, cols),
          h("thead", {}, h("tr", {}, ["Field", "Evidence ID", "Generated Statement", "Document", "Page", "Passage", "Status", "Actions"].map((x) => h("th", {}, x)))),
          h("tbody", {}, rows))));
  };
  const finCard = await financialCard(deal);
  const docEv = Object.values(data.evidence || {}).filter((e) => e.type === "document");
  const pendingEv = docEv.filter((e) => (e.status || "Pending") === "Pending").length;
  const bulkBtn = h("button", { type: "button", class: "secondary", disabled: pendingEv === 0 }, `Approve all pending (${pendingEv})`);
  bulkBtn.addEventListener("click", async () => {
    if (needName() || !window.confirm(`Approve ${pendingEv} pending extraction item(s)?\n\nThis confirms you accept them as extracted. Each approval is recorded in the audit trail under your name.`)) return;
    try {
      const r = await busy(bulkBtn, "Saving...", () => api("POST", `/deals/${deal.deal_id}/section2/bulk`, { action: "approve_pending", analyst_name: analyst() }));
      toast(`${r.changed} item(s) approved. Each is recorded in the audit trail under your name.`, true);
      await rerender();
    } catch (e) { /* shown */ }
  });
  const notFound = docEv.filter((e) => e.location_status !== "Located").length;
  const extracted = sec.s2a.status !== "not_run" || sec.s2b.status !== "not_run";
  const stale = [sec.s2a, sec.s2b].some((x) => x.status === "stale");
  const attnN = docEv.filter((e) => (e.status || "Pending") === "Pending" || e.location_status !== "Located").length;
  let step;
  if (!deal.documents.length) step = nextStep("blocked", "Upload at least one PDF in Section 1 first.", h("a", { class: "button-link", href: `#/deal/${deal.deal_id}/intake` }, "Go to Section 1"));
  else if (!extracted) step = nextStep("todo", "Run the extraction. The AI reads the relevant pages; this takes a few minutes.", run(["business", "debt"], "Run extraction (2A and 2B)"));
  else if (pendingEv) step = nextStep("todo", [h("b", {}, `${pendingEv} item${pendingEv > 1 ? "s" : ""} to review`),
    notFound ? `, ${notFound} whose text was not found on the page (check those first).` : ". Compare each statement with its source, then approve."],
    bulkBtn, attentionToggle(attnN));
  else step = nextStep("ok", "Every extracted item is reviewed. Next: the financial dashboard.", h("a", { class: "button-link", href: `#/deal/${deal.deal_id}/dashboard` }, "Go to Section 3"));
  $main.replaceChildren(
    h("h2", {}, "Section 2: Extract and organise the relevant information"),
    h("div", { class: "card" },
      lead("The AI extracts business (2A) and debt (2B) facts from the PDFs; Python checks each quoted passage is really on the cited page.",
        "Each item gets an Evidence ID. Click it to see the page with the passage highlighted. Approve each item you accept, or Edit its statement (editing re-checks the passage and resets it to Pending). Items you approve here show as \u201cApproved in Section 2\u201d in the memo review.",
        "Financial figures (2C) are not extracted by the AI; they are fetched automatically from the financial database."),
      step,
      extracted && deal.documents.length ? h("div", { class: "row small", style: "margin-top:8px" }, h("span", { class: "spacer" }),
        ...[run(["business", "debt"], stale ? "Re-run extraction (out of date)" : "Re-run extraction"), run(["business"], "Re-run 2A only"), run(["debt"], "Re-run 2B only")]
          .map((b) => { b.className = "small secondary"; return b; })) : null),
    group("business", "2A Business information", "s2a"),
    group("debt", "2B Debt and financing information", "s2b"),
    finCard,
    nextSection(deal.deal_id, "dashboard"));
}

// --------------------------------------------------------------------------- Section 3
const pointLabels = {
  id: "pointLabels",
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    chart.data.datasets.forEach((ds, i) => {
      const meta = chart.getDatasetMeta(i);
      if (meta.hidden) return;
      // Label only the latest value; every other value is in the tooltip and the data table.
      let last = -1;
      ds.data.forEach((v, j) => { if (v !== null && v !== undefined) last = j; });
      meta.data.forEach((pt, j) => {
        if (j !== last) return;
        const text = ds.displays[j] + (ds.flags[j].length ? " \u26a0" : "");
        ctx.save(); ctx.font = "600 11px 'Segoe UI', sans-serif"; ctx.fillStyle = "#0f2d4e"; ctx.textAlign = "center";
        ctx.textAlign = "left"; ctx.fillStyle = ds.borderColor || "#0f2d4e";
        ctx.fillText(text, Math.min(pt.x + 7, chart.chartArea.right - ctx.measureText(text).width), pt.y - 8); ctx.restore();
      });
    });
  },
};

// Supporting rows (Revenue Growth Y/Y, EBITDA LTM, EBITDA excl. impairment) are hidden until "Show more metrics".
const visibleMetrics = (panel) => panel.metrics.filter((m) => !m.memo || state.showMore[panel.key]);

function panelCharts(panel, periods) {
  const wrap = h("div", {});
  const byUnit = {};
  visibleMetrics(panel).forEach((m) => { const k = m.unit === "amount" ? `amount|${m.unit_label || ""}` : m.unit; (byUnit[k] = byUnit[k] || []).push(m); });
  let colour = 0;
  for (const [unitKey, metrics] of Object.entries(byUnit)) {
    const unit = unitKey.split("|")[0];
    const axis = unitLabel(unit, metrics[0].unit_label);
    const canvas = h("canvas", { role: "img", "aria-label": `${panel.title} chart: ${metrics.map((m) => m.label).join(", ")}. Values are listed in the data table below.` });
    wrap.append(h("p", { class: "chart-unit" }, axis), h("div", { class: "chart-box" }, canvas));
    const datasets = metrics.map((m) => {
      const c = PALETTE[colour++ % PALETTE.length];
      return { label: m.label, data: m.series.map((p) => p.value), displays: m.series.map((p) => p.display), flags: m.series.map((p) => p.flags),
        borderColor: c, backgroundColor: c, pointBackgroundColor: c, pointBorderColor: "#ffffff", pointBorderWidth: 1.5,
        borderWidth: 2.5, spanGaps: false, tension: .25, pointRadius: 3.5, pointHoverRadius: 6,
        pointStyle: m.series.map((p) => (p.flags.length ? "triangle" : "circle")), pointRadiusFlags: 6 };
    });
    const AXIS = "#5a6676", GRID = "rgba(15,45,78,.08)", NAVY = "#0f2d4e";
    state.charts.push(new Chart(canvas, {
      type: "line", data: { labels: periods, datasets },
      options: { responsive: true, maintainAspectRatio: false, animation: false, layout: { padding: { top: 18, right: 54 } },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { color: NAVY, usePointStyle: true, pointStyle: "circle", padding: 14, font: { size: 12 } } },
          tooltip: { backgroundColor: NAVY, titleColor: "#fff", bodyColor: "#fff", borderColor: "#c79214", borderWidth: 1, padding: 10, cornerRadius: 6, displayColors: true,
            callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.dataset.displays[ctx.dataIndex]}${ctx.dataset.flags[ctx.dataIndex].length ? " (flags: " + ctx.dataset.flags[ctx.dataIndex].join(", ") + ")" : ""}` } } },
        scales: {
          x: { grid: { color: GRID, drawTicks: false }, border: { color: GRID }, ticks: { color: AXIS, font: { size: 11 } } },
          y: { title: { display: true, text: axis, color: AXIS, font: { size: 11 } }, grace: "10%",
               grid: { color: GRID, drawTicks: false }, border: { display: false }, ticks: { color: AXIS, font: { size: 11 } } } } },
      plugins: [pointLabels],
    }));
  }
  return wrap;
}

function dataTable(panel, periods) {
  if (!panel.metrics.length) return null;
  return h("details", { class: "data-table" }, h("summary", {}, `Data table: ${panel.title}`),
    h("table", {}, h("caption", { class: "small muted" }, "Values exactly as stored in the financial database, oldest to newest"),
      h("thead", {}, h("tr", {}, h("th", {}, "Period"), panel.metrics.map((m) => h("th", { title: m.basis || null }, m.label, m.unit_label ? h("div", { class: "small muted" }, m.unit_label) : null)))),
      h("tbody", {}, periods.map((p, i) => h("tr", {}, h("th", { scope: "row" }, p), panel.metrics.map((m) => {
        const pt = m.series[i];
        return h("td", {}, pt ? pt.display : "Not available in database", pt && pt.flags.length ? h("div", {}, pt.flags.map((f) => tag(f, "warn"))) : null);
      }))))));
}

function s3Statement(st) {
  const { box, collapse } = stmtShell(st, "st-");
  const bodyEl = collapse ? h("div", { class: "stmt-body" }, h("div", { class: "stmt-text" }, st.text)) : box;
  if (collapse) box.append(bodyEl);
  const mismatch = st.verification.mark === "Number mismatch";
  bodyEl.append(h("div", { class: "meta" }, stmtBadges(st), sourceList(st.refs, null, sourceDialog, mismatch), stmtRef(st)));
  if (st.text !== st.original_text) bodyEl.append(h("div", { class: "small muted" }, "Edited. AI original: ", st.original_text));
  if (st.verification.unmatched.length) bodyEl.append(h("div", { class: "unmatched" }, "Not matched: " + st.verification.unmatched.map((u) => `${u.value} (${u.reason})`).join("; ")));
  if (st.comments.length) bodyEl.append(h("ul", { class: "small" }, st.comments.map((c) => h("li", {}, `${c.analyst_name}: ${c.text}`))));
  const act = async (action, text, btn) => {
    if (needName()) return;
    try {
      await busy(btn, "Saving...", () => api("POST", `/deals/${state.deal.deal_id}/section3/statements/${st.id}/action`, { action, analyst_name: analyst(), text }));
      announce(`${st.id} ${action} saved`);
      await rerender();
      const el = document.getElementById(`st-${st.id}`);
      (el?.querySelector(".actions button") || el?.querySelector("summary"))?.focus();
    } catch (e) { /* shown */ }
  };
  const editor = (kind) => {
    const ta = h("textarea", { "aria-label": kind === "edit" ? `Edit ${st.id}` : `Comment on ${st.id}`, maxlength: kind === "edit" ? 5000 : 2000 }, kind === "edit" ? st.text : "");
    const save = h("button", { type: "button", class: "small" }, kind === "edit" ? "Save edit" : "Save comment");
    save.addEventListener("click", () => act(kind, ta.value, save));
    const ed = h("div", { class: "editor" }, ta, h("div", { class: "row" }, save, h("button", { type: "button", class: "small secondary", onclick: () => ed.remove() }, "Cancel")));
    bodyEl.querySelector(".editor")?.remove();
    bodyEl.append(ed); ta.focus();
  };
  // A mismatch is cleared by Edit or Flag, not Approve, so those become the visible actions.
  const primary = [];
  const more = [];
  const mk = (label, cls, fn) => { const b = h("button", { type: "button", class: `small ${cls}` }, label); b.addEventListener("click", () => fn(b)); return b; };
  if (mismatch && st.status !== "Flagged") {
    primary.push(mk("Edit", "", () => editor("edit")), mk("Flag", "secondary", (b) => act("flag", null, b)));
    more.push(["Comment", () => editor("comment")]);
  } else {
    if (st.status !== "Approved") primary.push(mk("Approve", "", (b) => act("approve", null, b)));
    if (st.status !== "Flagged") more.push(["Flag", (b) => act("flag", null, b)]);
    if (st.status === "Flagged") more.push(["Approve", (b) => act("approve", null, b)]);
    more.push(["Edit", () => editor("edit")], ["Comment", () => editor("comment")]);
  }
  bodyEl.append(actionBar(primary, more, mismatch && st.status !== "Flagged" ? "Fix the figure with Edit, or Flag it" : null));
  return box;
}

// --------------------------------------------------------------------------- Section 3: peer comparison
const PEER_COLOURS = ["#0f2d4e", "#c79214", "#1e6b35", "#9c1c1c", "#6b4aa7", "#4a7aa7", "#9c6b1f"];
const PEER_DEFAULT_METRICS = ["REVENUE_GROWTH", "EBITDA_MARGIN", "DEBT_EBITDA", "INTEREST_COVERAGE", "CURRENT_RATIO"];

async function peerCard(deal) {
  const card = h("section", { class: "card panel-card", "aria-labelledby": "peer-head" },
    h("div", { class: "panel-head" }, h("h3", { id: "peer-head" }, "Peer comparison")));
  const body = h("div", { class: "fc-body" });
  card.append(body);
  let data;
  try { data = await api("GET", `/deals/${deal.deal_id}/peers`); }
  catch (e) { body.append(h("p", { class: "tag warn" }, errText(e))); return card; }

  // borrower first, then the peers in workbook order
  const comps = [...data.companies].sort((a, b) => (b.sheet === data.borrower_sheet) - (a.sheet === data.borrower_sheet));
  const colour = Object.fromEntries(comps.map((c, i) => [c.sheet, PEER_COLOURS[i % PEER_COLOURS.length]]));
  const storeKey = `peers:${deal.deal_id}`;
  let sel;
  try { sel = JSON.parse(localStorage.getItem(storeKey)); } catch (e) { sel = null; }
  if (!sel || typeof sel !== "object") {
    sel = {};
    PEER_DEFAULT_METRICS.forEach((m) => (sel[m] = comps.map((c) => c.sheet)));
  }
  const save = () => localStorage.setItem(storeKey, JSON.stringify(sel));
  const isOn = (m, sheet) => (sel[m] || []).includes(sheet);
  const setOn = (m, sheet, on) => {
    const cur = new Set(sel[m] || []);
    on ? cur.add(sheet) : cur.delete(sheet);
    if (cur.size) sel[m] = [...cur]; else delete sel[m];
  };

  const charts = [];
  const chartsBox = h("div", {});
  const boxes = {};
  const syncBoxes = () => Object.entries(boxes).forEach(([k, el]) => { const [m, s] = k.split("|"); el.checked = isOn(m, s); });
  const changed = () => { save(); syncBoxes(); renderCharts(); };

  // ---- selection matrix: metrics (rows) x companies (columns) ----
  const has = (c, m) => c.metrics[m] && Object.values(c.metrics[m].points).some((p) => p.value !== null || p.display === "n/m");
  const colBtn = (c) => h("button", { type: "button", class: "small secondary", title: `Show or hide every metric for ${c.company}`,
    onclick: () => { const all = data.panels.flatMap((p) => p.metrics.map((m) => m.key)).filter((m) => has(c, m));
      const on = !all.every((m) => isOn(m, c.sheet)); all.forEach((m) => setOn(m, c.sheet, on)); changed(); } }, "All / none");
  const rowBtn = (m) => h("button", { type: "button", class: "link", title: "Show or hide this metric for every company",
    onclick: () => { const avail = comps.filter((c) => has(c, m.key)); const on = !avail.every((c) => isOn(m.key, c.sheet));
      avail.forEach((c) => setOn(m.key, c.sheet, on)); changed(); } }, m.label);
  const matrix = h("table", { class: "peer-matrix" },
    h("thead", {}, h("tr", {}, h("th", {}, "Metric (click a name to toggle the row)"),
      comps.map((c) => h("th", { class: "peer-col" }, h("span", { class: "dot", style: `background:${colour[c.sheet]}` }), ` ${c.sheet}`,
        c.sheet === data.borrower_sheet ? h("div", { class: "small muted" }, "Borrower") : null,
        h("div", { class: "small muted" }, c.currency_unit || ""), colBtn(c))))),
    h("tbody", {}, data.panels.flatMap((p) => [
      h("tr", { class: "peer-group" }, h("th", { colspan: comps.length + 1 }, p.title)),
      ...p.metrics.map((m) => h("tr", {}, h("th", { scope: "row" }, rowBtn(m)),
        comps.map((c) => {
          if (!has(c, m.key)) return h("td", { class: "peer-cell muted small", title: "Not in the database for this company" }, "n/a");
          const cb = h("input", { type: "checkbox", "aria-label": `${m.label} for ${c.company}` });
          cb.checked = isOn(m.key, c.sheet);
          cb.addEventListener("change", () => { setOn(m.key, c.sheet, cb.checked); changed(); });
          boxes[`${m.key}|${c.sheet}`] = cb;
          return h("td", { class: "peer-cell" }, cb);
        })))])));

  const presets = h("div", { class: "row" },
    h("button", { type: "button", class: "secondary small", onclick: () => { sel = {}; PEER_DEFAULT_METRICS.forEach((m) => (sel[m] = comps.map((c) => c.sheet))); changed(); } }, "Key ratios, all companies"),
    h("button", { type: "button", class: "secondary small", onclick: () => { sel = {}; data.panels.forEach((p) => p.metrics.forEach((m) => { if (comps.some((c) => c.sheet === data.borrower_sheet && has(c, m.key))) sel[m.key] = [data.borrower_sheet]; })); changed(); } }, "Borrower only"),
    h("button", { type: "button", class: "secondary small", onclick: () => { sel = {}; changed(); } }, "Clear all"));

  // ---- charts: one per selected metric, one line per selected company ----
  const renderCharts = () => {
    charts.splice(0).forEach((c) => { c.destroy(); state.charts = state.charts.filter((x) => x !== c); });
    const metricOrder = data.panels.flatMap((p) => p.metrics);
    const chosen = metricOrder.filter((m) => (sel[m.key] || []).length);
    if (!chosen.length) { chartsBox.replaceChildren(h("p", { class: "empty" }, "Tick at least one metric and company above to draw a chart.")); return; }
    const grid = h("div", { class: "fc-grid" });
    const tables = [];
    for (const m of chosen) {
      const list = comps.filter((c) => isOn(m.key, c.sheet) && has(c, m.key));
      if (!list.length) continue;
      const first = list[0].metrics[m.key];
      const units = [...new Set(list.map((c) => (first.unit === "amount" ? c.metrics[m.key].unit_label || c.currency_unit : null)))].filter(Boolean);
      const axis = first.unit === "amount" ? `Amount (${units.join(" / ")})` : UNIT_LABEL[first.unit] || first.unit;
      const datasets = list.map((c) => {
        const mm = c.metrics[m.key];
        const pts = data.quarters.map((q) => mm.points[q] || null);
        const unit = mm.unit === "amount" ? ` (${mm.unit_label || c.currency_unit})` : "";
        const mine = c.sheet === data.borrower_sheet;
        return { label: `${c.sheet}${unit}`, data: pts.map((p) => (p ? p.value : null)), pts,
          borderColor: colour[c.sheet], backgroundColor: colour[c.sheet], borderWidth: mine ? 3.5 : 2, pointRadius: mine ? 4.5 : 3,
          pointStyle: pts.map((p) => (p && p.flags.length ? "triangle" : "circle")), tension: .2, spanGaps: false };
      });
      const canvas = h("canvas", { role: "img", "aria-label": `${m.label}: ${list.map((c) => c.sheet).join(", ")}. Values are in the table below.` });
      const chart = new Chart(canvas, {
        type: "line", data: { labels: data.quarters, datasets },
        options: { responsive: true, maintainAspectRatio: false, animation: false,
          plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 } } },
            tooltip: { callbacks: { label: (ctx) => {
              const p = ctx.dataset.pts[ctx.dataIndex];
              if (!p) return `${ctx.dataset.label}: no data`;
              return `${ctx.dataset.label}: ${p.display} (${p.fiscal}${p.release_date ? `, reported ${p.release_date}` : ""})${p.flags.length ? " \u26a0 " + p.flags.join(", ") : ""}`;
            } } } },
          scales: { x: { ticks: { font: { size: 10 }, maxRotation: 45 } }, y: { title: { display: true, text: axis, font: { size: 11 } }, grace: "8%" } } },
      });
      charts.push(chart); state.charts.push(chart);
      const basisNotes = list.filter((c) => c.metrics[m.key].basis).map((c) => `${c.sheet}: ${c.metrics[m.key].basis}`);
      grid.append(h("div", { class: "fc-chart" }, h("p", { class: "chart-unit" }, m.label), h("div", { class: "chart-box" }, canvas),
        basisNotes.length ? h("details", { class: "small" }, h("summary", {}, "How each company defines it"), h("ul", {}, basisNotes.map((b) => h("li", {}, b)))) : null));
      tables.push(h("details", { class: "data-table" }, h("summary", {}, `Data table: ${m.label}`),
        h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, h("th", {}, "Calendar quarter"), list.map((c) => h("th", {}, c.sheet, first.unit === "amount" ? h("div", { class: "small muted" }, c.metrics[m.key].unit_label || c.currency_unit) : null)))),
          h("tbody", {}, data.quarters.map((q) => h("tr", {}, h("th", { scope: "row" }, q), list.map((c) => {
            const p = c.metrics[m.key].points[q];
            return h("td", { title: p ? `${p.fiscal}${p.release_date ? `, reported ${p.release_date}` : ""}${p.cell ? `, cell ${p.cell}` : ""}` : null },
              p ? p.display : "-", p ? h("div", { class: "small muted" }, p.fiscal) : null, p && p.flags.length ? h("div", {}, p.flags.map((f) => tag(f, "warn"))) : null);
          }))))))));
    }
    chartsBox.replaceChildren(grid, ...tables);
  };

  body.append(
    lead("Tick any metric for any company to compare the borrower with its peers.",
      `Values come straight from the database (${data.file_name}); the AI does not see or calculate this comparison.`,
      h("ul", { class: "small muted" },
      h("li", {}, "Quarters are lined up by the calendar date range each fiscal quarter falls in, as stated in the workbook (e.g. NVIDIA Q2-FY2027 and Intel Q2-FY2026 are both CQ2 2026, Apr\u2013Jun). Hover a point to see its fiscal quarter and report date."),
      h("li", {}, "Amounts are in each company's own unit, shown in the legend: USD m, or NT$ bn for TSMC. Ratios and percentages are directly comparable."),
      h("li", {}, "Some ratios are defined differently by company (for example DSCR). Open \u201cHow each company defines it\u201d under a chart."))),
    presets,
    h("div", { class: "table-wrap", style: "margin-top:10px" }, matrix),
    h("h4", {}, "Charts"), chartsBox);
  renderCharts();
  return card;
}

// --------------------------------------------------------------------------- Section 3: forecast and scenarios
const SCEN = [["base", "Base"], ["upside", "Upside"], ["downside", "Downside"]];
const SCEN_COLOUR = { base: "#c79214", upside: "#1e6b35", downside: "#9c1c1c" };
const FC_CHARTS = [
  ["REVENUE", "Revenue"], ["EBITDA", "EBITDA"], ["CFADS", "Cash flow available for debt service (EBITDA - capex)"],
  ["DEBT_SERVICE", "Debt service (interest + principal)"], ["DSCR", "DSCR (cash flow available / debt service)"],
  ["INTEREST_COVERAGE", "Interest coverage (EBITDA / interest)"], ["DEBT_EBITDA", "Debt/EBITDA (LTM)"], ["CASH", "Cash after debt service"],
];
const FC_TABLE = ["REVENUE", "EBITDA", "CAPEX", "CFADS", "INTEREST_EXPENSE", "PRINCIPAL", "DEBT_SERVICE", "DSCR", "INTEREST_COVERAGE",
  "TOTAL_DEBT", "DEBT_EBITDA", "CASH", "FACILITY_BALANCE"];
const THRESHOLD_FOR = { DSCR: "min_dscr", INTEREST_COVERAGE: "min_interest_coverage", DEBT_EBITDA: "max_debt_ebitda", CASH: "min_cash" };

async function forecastCard(deal, aiStatements) {
  let fc;
  try { fc = await api("GET", `/deals/${deal.deal_id}/forecast`); }
  catch (e) { return h("div", { class: "card" }, h("h3", {}, "Forecast and scenario analysis"), h("p", { class: "tag bad" }, errText(e))); }
  const card = h("section", { class: "card panel-card", "aria-labelledby": "fc-head" },
    h("div", { class: "panel-head" }, h("h3", { id: "fc-head" }, "Forecast and scenario analysis")));
  const body = h("div", { class: "fc-body" });
  card.append(body);
  if (!fc.available) {
    body.append(h("p", { class: "tag warn" }, fc.message));
    return card;
  }
  const unit = fc.currency_unit || "";
  const draft = JSON.parse(JSON.stringify(fc.assumptions));
  const charts = [];
  const statusLine = h("div", { class: "row" });
  const fieldErr = h("div", { class: "err", "aria-live": "polite" });
  const results = h("div", {});
  let current = fc;
  let dirty = false;

  const setStatus = () => {
    statusLine.replaceChildren(
      dirty ? tag("Unsaved changes: preview only", "warn")
        : fc.status.state === "saved" ? tag(`Saved by ${fc.status.saved_by} (${String(fc.status.saved_at).replace("T", " ").slice(0, 16)})`, "ok")
          : tag("Defaults from the database averages (not yet saved)", "muted"));
  };

  const inputs = {};
  const numInput = (path, value, { label, ...attrs } = {}) => {
    const el = h("input", { type: "number", step: "any", value: value ?? "", "aria-label": label || path, class: "fc-input", ...attrs });
    el.addEventListener("input", () => {
      const v = el.value.trim();
      const parts = path.split(".");
      let o = draft;
      for (const p of parts.slice(0, -1)) o = o[p];
      o[parts.at(-1)] = v === "" ? null : Number(v);
      dirty = true; setStatus(); schedule();
    });
    inputs[path] = el;
    return el;
  };

  // ---- assumptions table ----
  const stats = fc.history_stats;
  const ref = (p) => {
    const s = stats[p];
    if (p === "facility_rate") return stats.implied_rate_existing_debt != null ? `Implied rate on existing debt: ${stats.implied_rate_existing_debt}% p.a. (latest quarterly interest x 4 / total debt)` : "Set by the analyst";
    if (p === "interest_change") return "0% = latest quarter's interest expense held flat";
    if (!s) return "No history";
    return `Average ${s.mean}% (median ${s.median}%, range ${s.min}% to ${s.max}%, latest ${s.latest}%) over ${s.n} quarters, ${s.from_period} to ${s.to_period}`;
  };
  const srcLine = (s, p) => h("div", { class: "small muted fc-src", id: `src-${s}-${p}` }, (current.sources[s] || {})[p] || "");
  const aTable = h("table", { class: "fc-table" },
    h("caption", { class: "small muted" }, "Per-quarter assumptions in %. Upside and downside default to the base case plus illustrative shocks from config/analysis.toml; change any value."),
    h("thead", {}, h("tr", {}, h("th", {}, "Assumption"), h("th", {}, "Historical reference"), SCEN.map(([, l]) => h("th", {}, `${l} case`)))),
    h("tbody", {}, fc.params.map((p) => h("tr", {},
      h("th", { scope: "row" }, p.label),
      h("td", { class: "small" }, ref(p.key)),
      SCEN.map(([s, l]) => h("td", {}, numInput(`scenarios.${s}.${p.key}`, draft.scenarios[s][p.key], { label: `${l} case: ${p.label}`, min: p.limits[0], max: p.limits[1] }), srcLine(s, p.key)))))));

  // ---- facility, horizon, thresholds ----
  const fac = fc.facility;
  const rep = h("select", { "aria-label": "Facility repayment" },
    h("option", { value: "bullet" }, "Bullet at the end of the tenor"), h("option", { value: "amortising" }, "Equal quarterly instalments"));
  rep.value = draft.facility.repayment;
  rep.addEventListener("change", () => { draft.facility.repayment = rep.value; dirty = true; setStatus(); schedule(); });
  inputs["facility.repayment"] = rep;
  const facAmount = h("b", {}, fac.value != null ? `${fac.value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${unit}` : "Not included");
  const facGrid = h("div", { class: "grid2" },
    h("div", { class: "field" }, h("span", { class: "label-like" }, "Requested facility (from the deal intake)"),
      h("div", {}, facAmount, h("span", { class: "small muted" }, ` = ${fac.deal_amount}`))),
    h("div", { class: "field" }, h("label", {}, "Repayment"), rep),
    h("div", { class: "field" }, h("label", {}, "Tenor (quarters)"), numInput("facility.tenor_quarters", draft.facility.tenor_quarters, { label: "Facility tenor in quarters", min: 1, max: 120, step: 1 })),
    h("div", { class: "field" }, h("label", {}, `Forecast horizon (quarters, 4 to ${fc.max_horizon_quarters})`), numInput("horizon_quarters", draft.horizon_quarters, { label: "Forecast horizon in quarters", min: 4, max: fc.max_horizon_quarters, step: 1 })),
    fac.deal_currency !== fac.company_currency && fac.company_currency
      ? h("div", { class: "field" }, h("label", {}, `Exchange rate (${fac.company_currency} per 1 ${fac.deal_currency})`),
        numInput("facility.fx_rate", draft.facility.fx_rate, { label: "Exchange rate", min: 0 }), h("span", { class: "hint" }, "Needed to include the facility in the forecast"))
      : null);
  const thGrid = h("div", { class: "grid2" }, fc.thresholds_def.map((t) =>
    h("div", { class: "field" }, h("label", {}, `${t.label}${t.unit === "multiple" ? " (x)" : ` (${unit})`}`),
      numInput(`thresholds.${t.key}`, draft.thresholds[t.key], { label: t.label, placeholder: "Leave blank for no highlight" }))));

  // ---- buttons ----
  const saveBtn = h("button", { type: "button" }, "Save assumptions");
  saveBtn.addEventListener("click", async () => {
    if (needName()) return;
    if (!window.confirm("Save these forecast assumptions?\n\nThey are recorded in the audit trail under your name. The AI commentary, risks and memo (Sections 3-5) will be marked out of date so you can re-run them with the new forecast.")) return;
    try {
      await busy(saveBtn, "Saving...", () => api("PUT", `/deals/${deal.deal_id}/forecast`, { assumptions: draft, analyst_name: analyst() }));
      toast("Forecast assumptions saved. Re-run the AI analysis to use them.", true);
      await rerender();
    } catch (e) { showErrors(e); }
  });
  const resetBtn = h("button", { type: "button", class: "secondary" }, "Reset to defaults");
  resetBtn.addEventListener("click", async () => {
    if (needName()) return;
    if (!window.confirm("Discard the saved assumptions and return to the database averages?")) return;
    try {
      await busy(resetBtn, "Resetting...", () => api("DELETE", `/deals/${deal.deal_id}/forecast?analyst_name=${encodeURIComponent(analyst())}`));
      await rerender();
    } catch (e) { }
  });

  const showErrors = (e) => {
    Object.values(inputs).forEach((el) => el.removeAttribute("aria-invalid"));
    const fields = e?.body?.fields || [];
    fields.forEach((f) => {
      const key = f.field.includes(".") && !f.field.startsWith("facility") && !f.field.startsWith("thresholds") ? `scenarios.${f.field}` : f.field;
      inputs[key]?.setAttribute("aria-invalid", "true");
    });
    fieldErr.textContent = fields.length ? fields.map((f) => `${f.field}: ${f.reason}`).join("; ") : e ? errText(e) : "";
  };

  let timer = null;
  const schedule = () => { clearTimeout(timer); timer = setTimeout(preview, 450); };
  const preview = async () => {
    try {
      current = await api("POST", `/deals/${deal.deal_id}/forecast/preview`, { assumptions: draft });
      showErrors(null);
      for (const [s] of SCEN) for (const p of fc.params) {
        const el = document.getElementById(`src-${s}-${p.key}`);
        if (el) el.textContent = current.sources[s][p.key];
      }
      facAmount.textContent = current.facility.value != null ? `${current.facility.value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${unit}` : "Not included";
      renderResults();
    } catch (e) { showErrors(e); }
  };

  // ---- results ----
  const renderResults = () => {
    charts.splice(0).forEach((c) => { c.destroy(); state.charts = state.charts.filter((x) => x !== c); });
    const r = current;
    const th = r.assumptions.thresholds;
    const fmtTh = (key) => { const d = r.thresholds_def.find((t) => t.key === key); return th[key] == null ? null : `${th[key]}${d.unit === "multiple" ? "x" : ` ${unit}`}`; };
    const cell = (pt) => h("td", { class: pt && pt.breach ? "breach" : null, title: pt && pt.breach ? `Breaches ${pt.breach.label} of ${pt.breach.threshold_display}` : pt ? pt.evidence_id : null },
      pt ? pt.display : "-", pt && pt.breach ? " \u26a0" : "");
    const sumCell = (s, key, metric) => {
      const v = r.scenarios[s].summary[key];
      if (!v) return h("td", {}, "-");
      const pt = r.scenarios[s].series[metric].find((p) => p.period === v.period);
      return h("td", { class: pt && pt.breach ? "breach" : null }, v.display, h("div", { class: "small muted" }, v.period), pt && pt.breach ? h("div", { class: "small" }, `\u26a0 ${pt.breach.threshold.startsWith("max") ? "above" : "below"} ${pt.breach.threshold_display}`) : null);
    };
    const summary = h("table", { class: "fc-summary" },
      h("caption", { class: "small muted" }, `Forecast ${r.periods[0]} to ${r.periods.at(-1)} from ${r.start_period}. Amounts in ${unit}. Highlighted cells breach a threshold you entered.`),
      h("thead", {}, h("tr", {}, ["Scenario", "Lowest DSCR", "Lowest interest coverage", "Highest Debt/EBITDA", "Lowest cash after debt service", "Cash at end of horizon", "Quarters where cash flow < debt service"].map((x) => h("th", {}, x)))),
      h("tbody", {}, SCEN.map(([s, l]) => {
        const sm = r.scenarios[s].summary;
        return h("tr", {}, h("th", { scope: "row" }, h("span", { class: "dot", style: `background:${SCEN_COLOUR[s]}` }), ` ${l}`),
          sumCell(s, "min_dscr", "DSCR"), sumCell(s, "min_interest_coverage", "INTEREST_COVERAGE"), sumCell(s, "max_debt_ebitda", "DEBT_EBITDA"),
          sumCell(s, "min_cash", "CASH"), h("td", {}, sm.final_cash.display),
          h("td", { class: sm.shortfall_quarters.length ? "breach" : null }, sm.shortfall_quarters.length ? `${sm.shortfall_quarters.length} of ${r.periods.length} (first ${sm.shortfall_quarters[0]})` : "None"));
      })));
    const breachList = r.breaches.length
      ? h("details", { class: "fc-breaches" }, h("summary", {}, `Threshold breaches (${r.breaches.length})`),
        h("ul", { class: "small" }, r.breaches.slice(0, 200).map((b) => h("li", {}, `${b.scenario}: ${b.metric_label} ${b.display} in ${b.period} vs ${b.threshold_label} ${b.threshold_display} `, h("code", {}, b.evidence_id)))))
      : (Object.values(th).some((v) => v != null) ? h("p", { class: "small ready-line" }, "No threshold is breached in any scenario.") : h("p", { class: "small muted" }, "Enter thresholds above to highlight quarters that breach them."));

    // charts: history (where the workbook uses the same definition) + three scenarios
    const labels = [...(r.history_periods || []), ...r.periods.map((p) => `${p} (F)`)];
    const nh = (r.history_periods || []).length;
    const grid = h("div", { class: "fc-grid" });
    for (const [key, title] of FC_CHARTS) {
      const mdef = r.metrics_def.find((m) => m.key === key);
      const canvas = h("canvas", { role: "img", "aria-label": `${title}: history and base, upside and downside forecasts. Values are in the tables below.` });
      const hist = r.history[key];
      const datasets = [];
      if (hist) {
        datasets.push({ label: "Database (history)", data: [...hist.map((p) => p.value), ...r.periods.map(() => null)], displays: [...hist.map((p) => p.display), ...r.periods.map(() => "")],
          borderColor: "#0f2d4e", backgroundColor: "#0f2d4e", borderWidth: 2.5, pointRadius: 3.5, tension: .2 });
      }
      for (const [s, l] of SCEN) {
        const series = r.scenarios[s].series[key];
        const lead = hist ? hist.map((p, i) => (i === nh - 1 ? p.value : null)) : Array(nh).fill(null);
        datasets.push({ label: `${l} (forecast)`, data: [...lead, ...series.map((p) => p.value)], displays: [...(hist ? hist.map((p) => p.display) : Array(nh).fill("")), ...series.map((p) => p.display)],
          borderColor: SCEN_COLOUR[s], backgroundColor: SCEN_COLOUR[s], borderDash: [6, 4], borderWidth: 2, tension: .2, spanGaps: false,
          pointRadius: [...Array(nh).fill(0), ...series.map((p) => (p.breach ? 5 : 2.5))], pointStyle: [...Array(nh).fill("circle"), ...series.map((p) => (p.breach ? "triangle" : "circle"))] });
      }
      const tKey = THRESHOLD_FOR[key];
      if (tKey && th[tKey] != null) {
        datasets.push({ label: `Your threshold (${fmtTh(tKey)})`, data: labels.map((_, i) => (i >= nh ? th[tKey] : null)), displays: labels.map(() => fmtTh(tKey)),
          borderColor: "#5a6676", borderDash: [2, 3], borderWidth: 1.5, pointRadius: 0 });
      }
      const chart = new Chart(canvas, {
        type: "line", data: { labels, datasets },
        options: { responsive: true, maintainAspectRatio: false, animation: false, spanGaps: false,
          plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 } } },
            tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.dataset.displays[ctx.dataIndex] || "n/m"}` } } },
          scales: { x: { ticks: { font: { size: 10 }, maxRotation: 60, autoSkip: true } },
            y: { title: { display: true, text: unitLabel(mdef.unit, unit), font: { size: 11 } }, grace: "8%" } } },
      });
      charts.push(chart); state.charts.push(chart);
      grid.append(h("div", { class: "fc-chart" }, h("p", { class: "chart-unit" }, title, hist ? "" : " (forecast only)"), h("div", { class: "chart-box" }, canvas)));
    }

    const detail = SCEN.map(([s, l]) => h("details", { class: "data-table" }, h("summary", {}, `${l} case: quarterly forecast table`),
      h("div", { class: "table-wrap" }, h("table", { class: "fc-detail" },
        h("thead", {}, h("tr", {}, h("th", {}, `Metric (${unit} unless stated)`), r.periods.map((p) => h("th", {}, p)))),
        h("tbody", {}, FC_TABLE.map((k) => h("tr", {}, h("th", { scope: "row" }, r.metrics_def.find((m) => m.key === k).label),
          r.scenarios[s].series[k].map((pt) => cell(pt)))))))));

    results.replaceChildren(...[
      r.warnings.length ? h("div", { class: "disclaimer" }, h("ul", { style: "margin:0" }, r.warnings.map((w) => h("li", {}, w)))) : null,
      h("div", { class: "table-wrap" }, summary), breachList, grid, ...detail,
      h("details", { class: "data-table" }, h("summary", {}, "How the forecast is calculated"), h("ul", { class: "small" }, r.notes.map((n) => h("li", {}, n))))].filter(Boolean));
  };

  body.append(
    lead("Projections from the assumptions below, calculated by Python. Change any value and the results update.",
      "The AI calculates nothing. Every forecast value has an FC- Evidence ID that the AI commentary and the memo cite. Figures are projections from stated assumptions, not reported results.",
      "Save the assumptions before running the AI analysis: saving changed values marks Sections 3 to 5 out of date so they are re-run with the new forecast."),
    statusLine,
    h("h4", {}, "Scenario assumptions"), h("div", { class: "table-wrap" }, aTable),
    h("h4", {}, "Requested facility and horizon"), facGrid,
    h("h4", {}, "Your thresholds (optional)"), h("p", { class: "small muted" }, "Forecast quarters that breach a threshold are highlighted. Leave blank for no highlight."), thGrid,
    fieldErr,
    h("div", { class: "row", style: "margin-top:12px" }, saveBtn, resetBtn, h("span", { class: "small muted" }, "Changes preview immediately; save to use them in the AI analysis and memo.")),
    h("h4", {}, "Results"), results,
    h("h4", { class: "commentary-head", style: "margin-top:18px" }, "AI commentary on the forecast"),
    aiStatements.length ? h("div", { class: "attn-scope" }, aiStatements.map((s) => s3Statement(s))) : h("p", { class: "muted small" }, "No AI forecast commentary yet. Save the assumptions, then run the AI financial analysis."));
  setStatus();
  renderResults();
  return card;
}

async function screenDashboard() {
  const deal = state.deal;
  if (deal.financial.status !== "connected" && deal.financial.status !== "loaded") {
    $main.replaceChildren(h("h2", {}, "Section 3: Financial trend dashboard"),
      h("p", { class: "empty" }, deal.financial.status === "error"
        ? `The financial database could not be connected: ${deal.financial.error || "unknown error"}. See Section 2.`
        : "The financial database is not connected for this deal. See Section 2."));
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
  const s3state = deal.sections.s3;
  const attention = stmts.filter(needsAttention);
  const nMismatchOpen = attention.filter((s) => s.verification.mark === "Number mismatch").length;
  const reRun = h("button", { type: "button", class: "secondary small" }, "Re-run AI analysis");
  reRun.addEventListener("click", async () => {
    try { await busy(reRun, "The AI is analysing trends; the backend is checking every figure...", () => api("POST", `/deals/${deal.deal_id}/section3/run`)); toast("Section 3 analysis ready for review.", true); await rerender(); } catch (e) { }
  });

  // ---- one "what to do now" bar ----
  let step;
  if (!has) step = nextStep("todo", "Check the charts and the forecast assumptions (Forecast tab), then run the AI analysis. It takes about a minute.", runBtn);
  else if (s3state.status === "stale") step = nextStep("warn", `${s3state.message || "Out of date: an earlier section changed."} Re-run the AI analysis so the commentary matches.`, runBtn);
  else if (deal.s3_approved) step = nextStep("ok", `Financial analysis approved by ${s3.approval?.analyst_name || "the analyst"}. Continue to Section 4.`,
    h("a", { class: "button-link", href: `#/deal/${deal.deal_id}/risks` }, "Go to Section 4"));
  else if (attention.length) step = nextStep("todo",
    [h("b", {}, `${attention.length} statement${attention.length > 1 ? "s" : ""} need${attention.length > 1 ? "" : "s"} review`),
      ` (${counts.Pending} pending${nMismatchOpen ? `, ${nMismatchOpen} with a number mismatch to Edit or Flag` : ""}). Then approve the financial analysis.`],
    pendingVerified ? bulk("approve_verified", "Approve all verified", pendingVerified,
      `Approve ${pendingVerified} pending statement(s) whose figures Python matched to the database?\n\nThis confirms you have read them and agree with the interpretation, not just the numbers. Each approval is recorded under your name.`) : null,
    pendingMismatch ? bulk("flag_mismatches", "Flag all mismatches", pendingMismatch, `Flag ${pendingMismatch} pending statement(s) whose figures did not match the database?`) : null,
    attentionToggle(attention.length));
  else step = nextStep("todo", "Every statement is reviewed. Approve the financial analysis to unlock Section 4.", approveBtn);

  const top = h("div", { class: "card" },
    lead(`Charts show ${dash.company || "the borrower"}'s figures from the financial database; the AI commentary beside them is checked figure by figure by Python.`,
      `Values come from ${dash.file_name}. ${dash.calculation_note || ""}`,
      "The forecast is calculated by the backend from assumptions you can edit (Forecast tab). Save them before running the AI analysis, because the AI commentary and the memo use them.",
      "To approve the analysis, every statement must be Approved or Flagged, and a statement with a number mismatch must be corrected with Edit or Flagged (approving it does not clear the mismatch)."),
    step,
    has ? h("div", { class: "row small muted", style: "margin-top:8px" },
      `${counts.Approved} approved \u00b7 ${counts.Flagged} flagged \u00b7 ${counts.Pending} pending`, h("span", { class: "spacer" }), reRun) : null,
    s3state.last_error ? h("details", {}, h("summary", {}, "Last run failed"), h("ul", {}, s3state.last_error.map((x) => h("li", {}, x)))) : null);

  // ---- Trends tab: one card per panel ----
  const panels = dash.panels.map((p) => {
    const shown = visibleMetrics(p);
    const hiddenN = p.metrics.length - shown.length;
    const latest = shown.length ? h("div", { class: "latest" }, shown.map((m) => {
      const c = m.latest_comparison;
      // Colour the delta by whether the move is favourable, not just its direction (from the backend:
      // "lower" = lower is better, e.g. Debt/EBITDA, DSO; "neutral" = neither, e.g. capex).
      const lowerBetter = m.better ? m.better === "lower" : m.key === "DEBT_EBITDA" || m.key === "DSO";
      let tone = "flat";
      if (m.better === "neutral") tone = "flat";
      else if (c && c.direction === "up") tone = lowerBetter ? "down" : "up";
      else if (c && c.direction === "down") tone = lowerBetter ? "up" : "down";
      return h("div", { class: "metric" },
        h("div", { class: "metric-label", title: m.basis || null }, m.label, m.unit_label ? ` (${m.unit_label})` : ""),
        h("div", { class: "metric-value" }, h("b", {}, m.latest.display), h("span", { class: "metric-period" }, m.latest.period)),
        m.latest.flags.length ? h("div", { class: "metric-flags" }, m.latest.flags.map((f) => tag(f, "warn"))) : null,
        c ? h("div", { class: `metric-delta ${tone}` }, c.direction === "~" ? "\u2192 stable" : (c.direction === "up" ? "\u2191 " : "\u2193 ") + c.change_display)
          : h("div", { class: "metric-delta flat" }, "no comparison"),
        m.sustained ? h("div", { class: "metric-sustained" }, m.sustained) : null);
    })) : null;
    const group = stmts.filter((s) => s.group === `panel:${p.key}`);
    const open = group.filter(needsAttention).length;
    const moreBtn = p.metrics.some((m) => m.memo) ? h("button", { type: "button", class: "small ghost",
      onclick: async () => { state.showMore[p.key] = !state.showMore[p.key]; await rerender(); } },
      state.showMore[p.key] ? "Show fewer metrics" : `Show ${hiddenN} more metric${hiddenN > 1 ? "s" : ""}`) : null;
    return h("section", { class: "card panel-card", "aria-labelledby": `panel-${p.key}` },
      h("div", { class: "panel-head row" }, h("h3", { id: `panel-${p.key}` }, p.title), h("span", { class: "spacer" }),
        has ? (open ? tag(`${open} to review`, "warn") : tag("\u2713 reviewed", "ok")) : null, moreBtn),
      h("div", { class: "panel" },
        h("div", { class: "panel-data" }, panelCharts(p, dash.periods), latest,
          p.not_available.length ? h("p", { class: "not-avail" }, h("b", {}, "Not available in database: "), p.not_available.join(", ")) : null, dataTable(p, dash.periods)),
        h("div", { class: "panel-commentary attn-scope" }, h("h4", { class: "commentary-head" }, "AI commentary"),
          group.length ? group.map((s) => s3Statement(s)) : h("p", { class: "muted small" }, "No AI commentary yet."),
          group.length && !open ? h("p", { class: "all-done-note" }, "\u2713 Everything in this panel is reviewed.") : null)));
  });
  const divergence = has ? h("details", { class: "card" }, h("summary", {}, h("b", {}, "Divergence patterns (Project Details)"), " ",
    h("span", { class: "small muted" }, `${s3.divergences.filter((d) => (d.observed || []).length).length} observed of ${s3.divergences.length}`)),
    h("table", { style: "margin-top:10px" }, h("thead", {}, h("tr", {}, h("th", {}, "Pattern"), h("th", {}, "Result"), h("th", {}, "Missing metrics"))),
      h("tbody", {}, s3.divergences.map((d) => h("tr", {}, h("td", {}, `${d.pattern_id}: ${d.description}`), h("td", {}, d.result), h("td", {}, d.missing_metrics.join(", ") || "-")))))) : null;

  // ---- Repayment tab ----
  const cross = stmts.filter((s) => s.group === "cross");
  const dims = ["profitability", "cash_generation", "leverage", "liquidity", "debt_servicing"];
  const repayCards = has ? [
    h("div", { class: "card attn-scope" }, h("h3", {}, "Relationships between metrics"), cross.length ? cross.map((s) => s3Statement(s)) : h("p", { class: "muted" }, "None reported."),
      cross.length && !cross.some(needsAttention) ? h("p", { class: "all-done-note" }, "\u2713 All reviewed.") : null),
    h("div", { class: "card attn-scope" }, h("h3", {}, "Repayment capacity"),
      dims.map((d) => {
        const sup = stmts.filter((s) => s.group === `repayment:${d}:supports`), weak = stmts.filter((s) => s.group === `repayment:${d}:weakens`);
        return h("div", { class: `repay-dim${[...sup, ...weak].some(needsAttention) ? "" : " done-group"}` },
          h("h4", {}, d.replace("_", " ").replace(/^./, (c) => c.toUpperCase())),
          h("div", { class: "repay-cols" },
            h("div", { class: "repay-col supports" }, h("p", { class: "repay-head" }, "\u2713 Supports repayment"), sup.map((s) => s3Statement(s))),
            h("div", { class: "repay-col weakens" }, h("p", { class: "repay-head" }, "\u26a0 Weakens repayment"), weak.map((s) => s3Statement(s)))));
      }))] : [h("p", { class: "empty" }, "Run the AI analysis to see the repayment-capacity assessment.")];

  // ---- tabs ----
  const peerBox = await peerCard(deal);
  const fcCard = await forecastCard(deal, stmts.filter((s) => s.group === "forecast"));
  const openIn = (pred) => stmts.filter((s) => pred(s.group) && needsAttention(s)).length;
  const TABS = [
    ["trends", "Trends", [...panels, divergence], openIn((g) => g.startsWith("panel:"))],
    ["peers", "Peers", [peerBox], 0],
    ["forecast", "Forecast", [fcCard], openIn((g) => g === "forecast")],
    ["repayment", "Repayment", repayCards, openIn((g) => g === "cross" || g.startsWith("repayment:"))],
  ];
  if (!TABS.some(([k]) => k === state.s3Tab)) state.s3Tab = "trends";
  const tabBtns = {}, tabPanels = {};
  const select = (key, focus) => {
    state.s3Tab = key;
    for (const [k] of TABS) {
      tabBtns[k].setAttribute("aria-selected", String(k === key)); tabBtns[k].tabIndex = k === key ? 0 : -1;
      tabPanels[k].hidden = k !== key;
    }
    if (focus) tabBtns[key].focus();
    const want = `#/deal/${deal.deal_id}/dashboard/${key}`;
    if (location.hash !== want) history.replaceState(null, "", want);  // keeps the tab on refresh, no reload
    window.dispatchEvent(new Event("resize"));  // charts drawn while hidden pick up their size
  };
  const tablist = h("div", { class: "tabs", role: "tablist", "aria-label": "Section 3 views" });
  TABS.forEach(([k, label, , n], i) => {
    const b = h("button", { type: "button", role: "tab", id: `tab-${k}`, "aria-controls": `tabpanel-${k}`, class: "tab" },
      label, n ? h("span", { class: "tab-count", "aria-label": `${n} to review` }, String(n)) : null);
    b.addEventListener("click", () => select(k));
    b.addEventListener("keydown", (ev) => {
      if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
      const next = TABS[(i + (ev.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length][0];
      select(next, true);
    });
    tabBtns[k] = b; tablist.append(b);
  });
  const panelsEls = TABS.map(([k, , content]) => (tabPanels[k] = h("div", { role: "tabpanel", id: `tabpanel-${k}`, "aria-labelledby": `tab-${k}`, class: "tabpanel" }, content.filter(Boolean))));

  $main.replaceChildren(...[h("h2", {}, "Section 3: Financial dashboard and AI analysis"), top, tablist, ...panelsEls,
    nextSection(deal.deal_id, "risks")].filter(Boolean));
  select(state.s3Tab);
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
  let step;
  if (!deal.s3_approved) step = nextStep("blocked", "Approve the financial analysis in Section 3 first.", h("a", { class: "button-link", href: `#/deal/${deal.deal_id}/dashboard` }, "Go to Section 3"));
  else if (!s4.risks) step = nextStep("todo", "Identify the key risks. The AI uses the approved Section 3 analysis, the extracted facts and the loan request.", runBtn);
  else if (st.status === "stale") step = nextStep("warn", "Out of date: an earlier section changed. Re-run the risk analysis.", runBtn);
  else step = nextStep("ok", `${s4.risks.length} risk${s4.risks.length === 1 ? "" : "s"} identified. Read them, then generate the memo.`,
    h("a", { class: "button-link", href: `#/deal/${deal.deal_id}/memo` }, "Go to Section 5"));
  if (s4.risks && st.status !== "stale") { runBtn.className = "small secondary"; }
  const head = h("div", { class: "card" },
    lead("Ranked credit risks with evidence, mitigants and proposed terms. These are suggestions for you to consider, not lending decisions.",
      "Each risk's evidence is number-checked by Python. Any covenant with a numeric threshold is labelled Assumption with \u201cIllustrative; analyst to calibrate against credit policy.\u201d"),
    step,
    s4.risks && st.status !== "stale" ? h("div", { class: "row", style: "margin-top:8px" }, h("span", { class: "spacer" }), runBtn) : null,
    st.last_error ? h("details", {}, h("summary", {}, "Last run failed"), h("ul", {}, st.last_error.map((x) => h("li", {}, x)))) : null);
  const body = [];
  if (s4.risks) {
    body.push(h("table", {}, h("thead", {}, h("tr", {}, ["Identified Risk", "Evidence", "Possible Mitigant", "Proposed Term / Monitoring Condition"].map((x) => h("th", { scope: "col" }, x)))),
      h("tbody", {}, s4.risks.length ? s4.risks.map((r) => h("tr", {},
        h("td", {}, h("b", {}, `${r.rank}. ${r.identified_risk}`), h("div", { class: "small" }, r.category), h("div", {}, tag(`Impact: ${r.impact}`, r.impact === "High" ? "bad" : "warn"), " ", tag(`Likelihood: ${r.likelihood}`, "info")), h("code", { class: "small" }, r.risk_id)),
        h("td", {}, h("div", {}, r.evidence.text), h("div", { class: "meta" },
            r.verification.mark === "Numbers verified" ? h("span", { class: "ok-mark" }, "\u2713 numbers verified") : tag(r.verification.mark, "bad"),
            sourceList(r.evidence.refs, null, sourceDialog)),
          r.verification.unmatched.length ? h("div", { class: "unmatched" }, "Not matched: " + r.verification.unmatched.map((u) => u.value).join(", ")) : null,
          h("div", { class: "small muted" }, "Time horizon: ", r.time_horizon),
          r.business_context ? h("div", { class: "small" }, "Context: ", r.business_context.text, " ", r.business_context.refs.map((x) => evButton(x, null, sourceDialog))) : null),
        h("td", {}, h("ul", {}, r.mitigants.map((m) => h("li", {}, m)))),
        h("td", {}, h("ul", {}, r.terms.map((t) => h("li", {}, tag(t.term_type, "info"), " ", t.text, " ", tag(labelText(t.label), labelKind(t.label)))))))) :
        h("tr", {}, h("td", { colspan: 4 }, "No risks supported by the evidence provided.")))));
    if (s4.limitations.length) body.push(h("h4", {}, "Limitations"), h("ul", {}, s4.limitations.map((l) => h("li", {}, l))));
  }
  $main.replaceChildren(...[h("h2", {}, "Section 4: Identify key risks and suggest mitigants"), head, body.length ? h("div", { class: "card" }, body) : null,
    nextSection(deal.deal_id, "memo")].filter(Boolean));
}

// --------------------------------------------------------------------------- Sections 5 and 6
function memoStatement(st, review, openSource) {
  // Read-only memo view (Section 5): plain text with its sources folded away.
  const { box, collapse } = review ? stmtShell(st, "m-") : { box: h("div", { class: `stmt plain ${st.status}`, id: `m-${st.id}` }, h("div", { class: "stmt-text" }, st.text)), collapse: false };
  const bodyEl = collapse ? h("div", { class: "stmt-body" }, h("div", { class: "stmt-text" }, st.text)) : box;
  if (collapse) box.append(bodyEl);
  const mismatch = st.verification.mark === "Number mismatch";
  bodyEl.append(h("div", { class: "meta" }, stmtBadges(st), sourceList(st.refs, st.id, openSource, review && st.id === state.activeStatement), stmtRef(st)));
  // The carried-over badge (shown below in review mode) already states the note, so don't repeat it here.
  const carriedOver = st.carried_over && st.status === "Approved";
  if (st.note && !carriedOver) bodyEl.append(h("div", { class: "note-line" }, "Note: ", st.note));
  if (st.verification.unmatched.length) bodyEl.append(h("div", { class: "unmatched" }, "Not matched: " + st.verification.unmatched.map((u) => `${u.value} (${u.reason})`).join("; ")));
  if (st.text !== st.original_text) bodyEl.append(h("div", { class: "small muted" }, "Edited. AI original: ", st.original_text));
  if (review && state.status.support_check_enabled) {
    bodyEl.append(h("div", { class: "note-line" }, st.support ? [tag(st.support.assessment, st.support.assessment === "Supported" ? "ok" : st.support.assessment === "Not supported" ? "bad" : "warn"),
      " ", st.support.reason, " ", h("span", { class: "muted" }, "(AI preliminary check; analyst verification required)")] : h("span", { class: "muted" }, "AI support check: Not checked")));
  }
  if (!review) return box;
  // Already approved in an earlier section (Section 2 extraction, Section 3 financial review, or
  // backend-generated from the database): no need to approve the same point again. Show a badge, not buttons.
  if (carriedOver) {
    const note = st.note || "";
    let badge, detail;
    if (note.startsWith("Approved in Section 2")) {
      badge = "\u2713 Approved in Section 2";
      detail = "Carried over from the Section 2 extraction review \u2014 no action needed here. Click an Evidence ID to inspect the source.";
    } else if (note.startsWith("Verified in Section 3")) {
      badge = "\u2713 Approved in Section 3";
      detail = "Carried over from the Section 3 financial review \u2014 no action needed here. Click an Evidence ID to inspect the source.";
    } else {
      badge = "\u2713 Backend-generated";
      detail = "Generated by the backend from the financial database (not AI-written) \u2014 no action needed here. Click an Evidence ID to inspect the source.";
    }
    bodyEl.append(h("div", { class: "carried-over" }, tag(badge, "ok"), h("span", { class: "small muted" }, detail)));
    if (collapse) box.querySelector(".stmt-sum").append(h("span", { class: "carried-tag" }, badge.replace("\u2713 ", "")));
    return box;
  }
  const act = async (action, text, btn) => {
    if (needName()) return;
    try {
      await busy(btn, "Saving...", () => api("POST", `/deals/${state.deal.deal_id}/memo/statements/${st.id}/action`, { action, analyst_name: analyst(), text }));
      state.activeStatement = st.id;
      announce(`${st.id}: ${action} saved`);
      await rerender();
      const el = document.getElementById(`m-${st.id}`);
      (el?.querySelector(".actions button") || el?.querySelector("summary"))?.focus();
    } catch (e) { }
  };
  const editor = (kind) => {
    const ta = h("textarea", { "aria-label": kind === "correct" ? `Edit ${st.id}` : `Flag note for ${st.id}`, maxlength: kind === "correct" ? 2000 : 500 }, kind === "correct" ? st.text : "");
    const save = h("button", { type: "button", class: "small" }, kind === "correct" ? "Save edit" : "Flag with note");
    save.addEventListener("click", () => act(kind === "correct" ? "correct" : "flag", ta.value, save));
    const ed = h("div", { class: "editor" }, ta, h("div", { class: "row" }, save, h("button", { type: "button", class: "small secondary", onclick: () => ed.remove() }, "Cancel")));
    bodyEl.querySelector(".editor")?.remove(); bodyEl.append(ed); ta.focus();
  };
  const mk = (label, cls, fn) => { const b = h("button", { type: "button", class: `small ${cls}` }, label); b.addEventListener("click", () => fn(b)); return b; };
  const primary = [], more = [];
  if (mismatch && st.status !== "Flagged") {
    primary.push(mk("Edit", "", () => editor("correct")), mk("Flag", "secondary", () => editor("flag")));
    // Unlike Section 3, a memo approval is not blocked by a mismatch (e.g. a false alarm the analyst has checked).
    more.push(["Approve as is", (b) => act("approve", null, b)]);
  } else {
    if (st.status !== "Approved") primary.push(mk("Approve", "", (b) => act("approve", null, b)));
    if (st.status === "Flagged") more.push(["Approve", (b) => act("approve", null, b)]);
    else more.push(["Flag", () => editor("flag")]);
    more.push(["Edit", () => editor("correct")]);
  }
  bodyEl.append(actionBar(primary, more, mismatch && st.status !== "Flagged" ? "Fix the figure with Edit, or Flag it" : null));
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
      if (s.subsection !== current) {
        const allDone = sts.filter((x) => x.subsection === s.subsection).every(isDone);
        subs.push(h("h4", { class: allDone ? "done-group" : null }, s.subsection_title)); current = s.subsection;
      }
      subs.push(memoStatement(s, review, openSource));
    }
    sections.push(h("section", { class: `memo-section${sts.every(isDone) ? " done-group" : ""}` }, h("h3", {}, `${num}. ${bySection[num][0].section_title}`), subs));
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
  const pendingN = s5.statements ? s5.statements.filter((s) => s.status === "Pending").length : 0;
  let step;
  if (deal.sections.s4.status !== "completed") step = nextStep("blocked", "Complete Section 4 (key risks) first, and make sure it is up to date.",
    h("a", { class: "button-link", href: `#/deal/${deal.deal_id}/risks` }, "Go to Section 4"));
  else if (!s5.statements) step = nextStep("todo", "Generate the credit memo. The AI writes it from Sections 1 to 4; this can take 2 to 3 minutes.", runBtn);
  else if (st.status === "stale") step = nextStep("warn", "Out of date: an earlier section changed. Regenerate the memo.", runBtn);
  else step = nextStep(pendingN ? "todo" : "ok", pendingN ? `${pendingN} statement${pendingN > 1 ? "s" : ""} to review in Section 6, then export the memo.` : "Every statement is reviewed. Export the memo in Section 6.",
    h("a", { class: "button-link", href: `#/deal/${deal.deal_id}/review` }, pendingN ? "Review in Section 6" : "Export in Section 6"));
  if (s5.statements && st.status !== "stale") runBtn.className = "small secondary";
  const topCard = h("div", { class: "card" },
    lead("A 7-section credit memo drafted by the AI from Sections 1 to 4, with every figure and citation checked by Python. There is no AI recommendation; you decide.",
      "The memo cites only existing Evidence IDs. Information gaps, flagged database values and the forecast scenario summaries are added by the backend.",
      "Regenerating replaces the memo and resets all Section 6 reviews."),
    step,
    s5.statements && st.status !== "stale" ? h("div", { class: "row", style: "margin-top:8px" }, h("span", { class: "spacer" }), runBtn) : null,
    st.last_error ? h("details", {}, h("summary", {}, "Last run failed"), h("ul", {}, st.last_error.map((x) => h("li", {}, x)))) : null);

  if (!s5.statements) {
    $main.replaceChildren(h("h2", {}, "Section 5: Credit memo"), topCard);
    return;
  }

  // ---- holding space: a compact overview so the analyst is oriented before reading the full memo ----
  const [s3, s4, s2] = await Promise.all([api("GET", `/deals/${deal.deal_id}/section3`), api("GET", `/deals/${deal.deal_id}/section4`), api("GET", `/deals/${deal.deal_id}/section2`)]);
  const evItems = Object.values((s2 && s2.evidence) || {}).filter((e) => e.type === "document");
  const evCount = { total: evItems.length, Approved: 0, Flagged: 0, Pending: 0 };
  evItems.forEach((e) => { evCount[e.status || "Pending"] = (evCount[e.status || "Pending"] || 0) + 1; });
  const sts = s5.statements;
  const by = (p) => sts.filter(p).length;
  const counts = { Approved: by((s) => s.status === "Approved"), Pending: by((s) => s.status === "Pending"), Flagged: by((s) => s.status === "Flagged") };
  const labels = { Sourced: by((s) => s.label === "Sourced"), ASSUMPTION: by((s) => s.label === "ASSUMPTION"), "NOT VERIFIED": by((s) => s.label === "NOT VERIFIED") };
  const carried = by((s) => s.carried_over);
  const i = deal.intake;
  const risks = (s4 && s4.risks) || [];
  const termCount = risks.reduce((n, r) => n + (r.terms ? r.terms.length : 0), 0);
  const gapCount = by((s) => s.section === 7);
  let dsFlagged = 0;
  try { dsFlagged = (await api("GET", `/deals/${deal.deal_id}/financial`)).flagged_values.length; } catch (e) { /* ignore */ }

  const kv = (label, value) => h("div", { class: "metric" }, h("div", { class: "metric-label" }, label), h("div", { class: "metric-value" }, h("b", {}, String(value))));
  const kvText = (label, value) => h("div", { class: "metric" }, h("div", { class: "metric-label" }, label), h("div", { class: "metric-text" }, String(value)));
  const snapshot = h("div", { class: "card" },
    h("h3", {}, "Deal snapshot"),
    h("div", { class: "latest" },
      kvText("Borrower", i["DI-BORROWER"].display),
      kvText("Facility", i["DI-FACILITY_TYPE"].display),
      kvText("Amount", i["DI-AMOUNT"].display),
      kvText("Tenor", i["DI-TENOR"].display)),
    h("p", { class: "small muted", style: "margin-top:8px" }, "Purpose: ", i["DI-PURPOSE"].display));

  const pipeline = h("details", { class: "card" },
    h("summary", {}, h("b", {}, "What has been analysed")),
    h("ul", { class: "small" },
      h("li", {}, `${deal.documents.length} document(s) uploaded; financial database ${deal.financial.status === "connected" || deal.financial.status === "loaded" ? "connected" : "not connected"}.`),
      h("li", {}, !evCount.total
        ? "Section 2 extraction not run yet."
        : evCount.Approved === evCount.total
          ? "Section 2 extraction approved."
          : `Section 2 extraction not yet fully approved (${evCount.Approved} of ${evCount.total} items approved).`),
      h("li", {}, deal.s3_approved ? `Section 3 financial analysis approved${s3 && s3.approval ? ` by ${s3.approval.analyst_name}` : ""}.` : "Section 3 financial analysis not yet approved."),
      h("li", {}, `${risks.length} key risk(s) identified, with ${termCount} proposed covenant(s) / term(s).`),
      h("li", {}, `${gapCount} information-gap statement(s); ${dsFlagged} database value(s) flagged for review.`)));

  const needsReview = counts.Pending > 0;
  const memoGlance = h("div", { class: "card" },
    h("h3", {}, "Memo at a glance"),
    h("div", { class: "latest" },
      kv("Statements", sts.length),
      kv("Approved", counts.Approved),
      kv("Pending", counts.Pending),
      kv("Flagged", counts.Flagged),
      kv("Carried over", carried)),
    h("p", { class: "small muted", style: "margin-top:8px" },
      `Labels: ${labels.Sourced} Sourced, ${labels.ASSUMPTION} Assumption, ${labels["NOT VERIFIED"]} Not verified.`),
    needsReview ? null : h("p", { class: "ready-line" }, "All statements reviewed."));

  const fullMemo = h("details", { class: "card" },
    h("summary", {}, "View full memo (all 7 sections)"),
    h("div", { style: "margin-top:10px" }, memoBody(s5, false, (id) => sourceDialog(id))));

  $main.replaceChildren(h("h2", {}, "Section 5: Credit memo"), topCard, snapshot, pipeline, memoGlance, fullMemo,
    nextSection(deal.deal_id, "review"));
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
    const where = s5.statements.find((s) => s.id === sid)?.position;
    if (before !== after) { toast(`${where ? `${where} (${sid})` : sid} was flagged automatically: the source could not be located.`); await rerender(); }
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
  const bulkBtn = h("button", { type: "button", class: "secondary", disabled: counts.Pending === 0 }, `Approve all pending (${counts.Pending})`);
  bulkBtn.addEventListener("click", async () => {
    if (needName() || !window.confirm(`Approve ${counts.Pending} pending statement(s)?\n\nThis confirms you have read them and agree. Read the commentary and check sources first; each approval is recorded in the audit trail under your name.`)) return;
    try {
      const r = await busy(bulkBtn, "Saving...", () => api("POST", `/deals/${deal.deal_id}/memo/bulk`, { action: "approve_pending", analyst_name: analyst() }));
      toast(`${r.changed} statement(s) approved. Each is recorded in the audit trail under your name.`, true);
      await rerender();
    } catch (e) { /* shown */ }
  });
  const attn = s5.statements.filter(needsAttention).length;
  const step = counts.Pending
    ? nextStep("todo", [h("b", {}, `${counts.Pending} statement${counts.Pending > 1 ? "s" : ""} to review.`),
      " Open a statement's sources, compare them with the text, then Approve, Flag or Edit. The final memo needs every statement Approved or Flagged."],
      bulkBtn, attentionToggle(attn))
    : nextStep("ok", "Review complete. Download the final memo and the audit trail.", memoBtn, auditBtn);
  const tools = h("div", { class: "row" }, filters, h("span", { class: "spacer" }), counts.Pending ? memoBtn : null, counts.Pending ? auditBtn : null);
  if (counts.Pending) { memoBtn.className = "small secondary"; auditBtn.className = "small secondary"; memoBtn.disabled = true; memoBtn.title = "Available when no statement is Pending"; }
  if (state.status.support_check_enabled) {
    const sc = h("button", { type: "button", class: "small secondary" }, "Run AI support check");
    sc.addEventListener("click", async () => { try { await busy(sc, "Running the advisory support check...", () => api("POST", `/deals/${deal.deal_id}/support-check/run`)); await rerender(); } catch (e) { } });
    tools.append(sc);
  }
  $main.replaceChildren(h("h2", {}, "Section 6: Analyst review and source verification"),
    h("div", { class: "card" },
      lead("Check each memo statement against its source before approving: a citation to a real page does not by itself mean the statement is right.",
        "Click \u201cN sources\u201d on a statement, then an Evidence ID, to show the source on the right: the page with the passage highlighted, the database cell, or the forecast value. If a passage cannot be found on its page, the statement is flagged automatically.",
        "Statements already approved in Section 2 or 3, and statements the backend generated from the database, start as Approved and are folded to one line."),
      step, h("div", { style: "margin-top:10px" }, tools)),
    h("div", { class: "review" }, h("div", { class: "card attn-scope" }, memoBody(s5, true, openSource, state.reviewFilter)), sourcePanel));
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
