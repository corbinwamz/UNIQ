"use strict";

const $ = (selector) => document.querySelector(selector);
let data = null;
let selectedId = null;
let dirty = false;
let actionBusy = false;
let editorRevision = null;
let pollTimer = null;

function message(text = "") { $("#message").textContent = text; }
function paragraph(parent, text) {
  const node = document.createElement("p");
  node.textContent = text;
  parent.append(node);
}
function selected() { return data?.records.find((record) => record.email.email_id === selectedId); }
function canDiscard() { return !dirty || window.confirm("Discard unsaved draft changes?"); }

async function request(url, payload) {
  const response = await fetch(url, payload === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Request failed.");
  return body;
}

function controlState() {
  const processing = Boolean(data?.job.busy);
  const locked = processing || actionBusy;
  for (const selector of ["#upload", "#runs", "#process", "#check-ai"]) $(selector).disabled = locked;
  $("#export").disabled = locked || dirty || !data || data.records.some((record) => !record.result);
  const record = selected();
  $("#retry").disabled = locked || !record || dirty;
  $("#save").disabled = locked || !record?.result || !dirty;
  $("#reviewed").disabled = locked || !record?.result;
  $("#draft").disabled = locked || !record?.result || !record.result.decisions.triage.reply_allowed;
  $("#save-state").textContent = dirty ? "Unsaved changes" : record?.result ? "Saved locally" : "";
}

function renderQueue() {
  const category = $("#category").value;
  const filter = $("#filter").value;
  const records = data.records.filter((record) => {
    if (category && record.result?.category !== category) return false;
    if (filter === "human" && !record.result?.decisions.triage.needs_human) return false;
    if (filter === "unreviewed" && record.reviewed) return false;
    if (filter === "error" && !record.error) return false;
    if (filter === "pending" && record.result) return false;
    return true;
  }).sort((a, b) => (a.result?.priority || "P5").localeCompare(b.result?.priority || "P5") || a.email.received_at.localeCompare(b.email.received_at));
  $("#count").textContent = `(${records.length})`;
  $("#emails").replaceChildren();
  if (!records.length) paragraph($("#emails"), "No emails match these filters.");
  for (const record of records) {
    const button = document.createElement("button");
    button.type = "button";
    const state = record.error ? " · Error" : record.reviewed ? " · Reviewed" : "";
    button.textContent = `${record.result?.priority || "Pending"} · ${record.email.email_id}${state}\n${record.email.subject || "(No subject)"}`;
    button.style.whiteSpace = "pre-line";
    button.setAttribute("aria-current", String(record.email.email_id === selectedId));
    button.addEventListener("click", () => {
      if (!canDiscard()) return;
      selectedId = record.email.email_id;
      dirty = false;
      message();
      renderQueue();
      renderDetail();
    });
    $("#emails").append(button);
  }
}

function renderDetail() {
  const record = selected();
  $("#detail").hidden = !record;
  if (!record) { controlState(); return; }
  const { email, order_context: context, result } = record;
  editorRevision = record.revision;
  $("#subject").textContent = email.subject || "(No subject)";
  $("#sender").textContent = `${email.email_id} · ${email.from_name} <${email.from_email}> · ${email.received_at}`;
  $("#body").textContent = email.body;
  $("#draft").value = result?.draft_reply || "";
  $("#reviewed").checked = record.reviewed;
  $("#quote").textContent = result?.quote || (result ? "No custom quote requested." : "Not processed yet.");
  $("#human").textContent = result?.needs_human || "";
  $("#entry-error").textContent = record.error ? `${result ? "Retry failed; previous result preserved. " : ""}${record.error}` : "";
  $("#retry").textContent = result ? "Regenerate this email" : record.error ? "Retry this email" : "Process this email";
  $("#badges").replaceChildren();
  for (const text of result ? [result.priority, result.category, result.decisions.triage.needs_human ? "Owner review" : "Standard policy", record.reviewed ? "Reviewed" : "Needs review"] : ["Pending processing"]) {
    const badge = document.createElement("span");
    badge.className = `badge ${text === "P1" ? "p1" : text === "Owner review" ? "human" : ""}`;
    badge.textContent = text;
    $("#badges").append(badge);
  }
  $("#evidence").textContent = result ? JSON.stringify(result.decisions, null, 2) : "Rule decisions appear after processing.";
  $("#match").textContent = context.explanation;
  $("#orders").replaceChildren();
  for (const candidate of context.candidates) {
    const order = candidate.order;
    const card = document.createElement("article");
    card.className = "order";
    const heading = document.createElement("h3");
    heading.textContent = `${order.order_id}${order.order_id === context.suggested_order_id ? " · Suggested context" : ""}`;
    card.append(heading);
    paragraph(card, `${order.order_date} · ${order.order_type} · ${order.production_path}`);
    paragraph(card, order.items);
    paragraph(card, `Status: ${order.status} · Shipped: ${order.ship_date || "—"} · Delivered: ${order.delivered_date || "—"}`);
    paragraph(card, `Carrier: ${order.carrier || "—"} · Tracking: ${order.tracking || "—"}`);
    paragraph(card, `Historical total: ${order.order_total || "—"} (not a new quote)`);
    if (order.notes) paragraph(card, order.notes);
    paragraph(card, `Matching evidence: ${candidate.reasons.join("; ")}. Score ${candidate.score}; heuristic only.`);
    $("#orders").append(card);
  }
  controlState();
}

function render(snapshot, preserveEditor = false) {
  data = snapshot;
  if (!data.records.some((record) => record.email.email_id === selectedId)) {
    selectedId = data.records[0]?.email.email_id || null;
    dirty = false;
  }
  const complete = data.records.filter((record) => record.result).length;
  const reviewed = data.records.filter((record) => record.reviewed).length;
  const config = data.ai_configured ? "Gemini configured" : "Set GEMINI_API_KEY and GEMINI_MODEL in .env";
  $("#status").textContent = `${complete}/${data.records.length} processed · ${reviewed} reviewed · ${config} · Scenario ${data.scenario_date}${data.job.busy ? ` · Processing ${data.job.current || "…"} (${data.job.completed}/${data.job.total})` : ""}`;
  renderQueue();
  if (!preserveEditor || !dirty) renderDetail();
  else controlState();
  clearTimeout(pollTimer);
  if (data.job.busy) pollTimer = setTimeout(poll, 1200);
}

async function poll() {
  try {
    render(await request("/api/inbox"), true);
    if (!data.job.busy) { message(data.job.message); await refreshRuns(); }
  } catch (error) { message(error.message); pollTimer = setTimeout(poll, 2500); }
}

async function refreshRuns() {
  const { runs } = await request("/api/runs");
  $("#runs").replaceChildren();
  for (const run of runs) {
    const option = document.createElement("option");
    option.value = run.run_id;
    option.textContent = `${run.created_at.slice(0, 16).replace("T", " ")} UTC · ${run.completed}/${run.count} · ${run.run_id.slice(0, 6)}`;
    $("#runs").append(option);
  }
  $("#runs").value = data.run_id;
}

async function action(work) {
  if (actionBusy) return;
  actionBusy = true;
  controlState();
  message();
  try { await work(); }
  catch (error) { message(error.message); }
  finally { actionBusy = false; controlState(); }
}

for (const selector of ["#draft", "#reviewed"]) $(selector).addEventListener("input", () => { dirty = true; controlState(); });
for (const selector of ["#category", "#filter"]) $(selector).addEventListener("change", renderQueue);
$("#save").addEventListener("click", () => action(async () => {
  const payload = { email_id: selectedId, revision: editorRevision, draft_reply: $("#draft").value, reviewed: $("#reviewed").checked };
  const snapshot = await request("/api/review", payload);
  dirty = false;
  render(snapshot);
  message("Review saved locally.");
}));
$("#retry").addEventListener("click", () => action(async () => {
  if (selected()?.result && !window.confirm("Regenerate this email? A successful result replaces the saved draft and clears its reviewed status. A failed retry preserves it.")) return;
  render(await request("/api/process", { email_id: selectedId }));
}));
$("#process").addEventListener("click", () => action(async () => {
  if (!canDiscard()) return;
  const snapshot = await request("/api/process", {});
  dirty = false;
  render(snapshot);
}));
$("#check-ai").addEventListener("click", () => action(async () => { message((await request("/api/check-ai", {})).message); }));
$("#runs").addEventListener("change", () => action(async () => {
  if (!canDiscard()) { $("#runs").value = data.run_id; return; }
  const snapshot = await request("/api/open-run", { run_id: $("#runs").value });
  dirty = false;
  selectedId = null;
  render(snapshot);
}));
$("#upload").addEventListener("change", (event) => action(async () => {
  const file = event.target.files[0];
  if (!file || !canDiscard()) { event.target.value = ""; return; }
  const snapshot = await request("/api/import", { inbox_csv: await file.text() });
  dirty = false;
  selectedId = null;
  render(snapshot);
  await refreshRuns();
  event.target.value = "";
}));
$("#export").addEventListener("click", () => action(async () => {
  const response = await fetch("/api/export");
  if (!response.ok) throw new Error((await response.json()).error);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "uniq-results.csv";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  message("Exported latest saved drafts. Review status remains available in the app.");
}));
window.addEventListener("beforeunload", (event) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });

for (const category of ["Custom Quote", "Stock Order / Product Question", "Order Status", "Damage / Complaint", "Return / Refund", "Billing / Terms", "Spam / Phishing", "Vendor Pitch", "Feedback / Praise"]) {
  const option = document.createElement("option"); option.value = category; option.textContent = category; $("#category").append(option);
}
request("/api/inbox").then(async (snapshot) => { render(snapshot); await refreshRuns(); }).catch((error) => message(error.message));
