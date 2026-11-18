"use strict";
const $ = (id) => document.getElementById(id);
const q = $("question");
const messages = $("messages");
let status = null;
let pending = false;
let indexBusy = false;

function el(tag, klass, text) {
  const node = document.createElement(tag);
  if (klass) node.className = klass;
  if (text !== undefined) node.textContent = text;
  return node;
}
async function api(path, data) {
  const options = data === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)
  };
  const res = await fetch(path, options);
  const json = await res.json();
  if (!res.ok) throw new Error(json.error || "Požiadavka sa nepodarila.");
  return json;
}
function runtimeState(kind, label) {
  $("runtime").className = "status" + (kind ? " " + kind : "");
  $("runtime").querySelector("b").textContent = label;
}
function updateMode() {
  $("retrieval-label").textContent = $("mode").value === "lexical" || status?.embeddings_ready === false
    ? "BM25 · podľa slov" : "Hybridné vyhľadávanie";
}
function sourceLink(src, title) {
  const a = el("a", "", title);
  // The server creates these URLs for indexed files only.
  if (typeof src.url === "string" && src.url.startsWith("/sources/")) a.href = src.url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}
function applyStatus(s) {
  status = s;
  $("count-pdf").textContent = s.pdf_count;
  $("count-owl").textContent = s.owl_count;
  $("count-chunks").textContent = s.chunk_count;
  if (s.generation_ready) runtimeState("", "Lokálny model pripravený");
  else runtimeState("preview", "Len vyhľadávanie");
  updateMode();

  const extras = [...s.warnings];
  if (!s.generation_ready) extras.push("Pre generovanie spusti Ollamu a stiahni " + s.chat_model + ".");
  if (s.embedding_installed && !s.embeddings_ready) extras.push("Pre hybridný režim preindexuj zdroje.");
  $("index-note").textContent = [s.vector_note, ...extras].join("\n");
  $("source-list").replaceChildren();
  for (const src of s.sources) {
    const row = el("div", "source-row");
    const type = el("span", "tag" + (src.kind === "owl" ? " owl" : ""), src.kind.toUpperCase());
    const meta = el("div");
    meta.append(el("strong", "", src.title));
    const pages = src.pages === null ? "" : src.pages + " str. · ";
    meta.append(el("small", "", pages + src.chunks + " úryvkov · " + src.file));
    row.append(type, meta, sourceLink(src, src.kind === "pdf" ? "Otvoriť ↗" : "Stiahnuť ↓"));
    $("source-list").append(row);
  }
}
async function refresh() {
  try { applyStatus(await api("/api/status")); }
  catch { runtimeState("preview", "Server nedostupný"); }
}
function showPane(pane) {
  const chat = pane === "chat";
  $("chat-pane").hidden = !chat;
  $("sources-pane").hidden = chat;
  $("view-title").textContent = chat ? "Asistent" : "Zdroje";
  for (const [button, active] of [[$("nav-chat"), chat], [$("nav-sources"), !chat]]) {
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  window.scrollTo(0, 0);
  if (!chat) refresh();
}
function bottom() { requestAnimationFrame(() => window.scrollTo(0, document.documentElement.scrollHeight)); }
function answerCard(label, meta = "") {
  const card = el("article", "answer");
  const head = el("div", "answer-head");
  const brand = el("div", "answer-brand");
  const logo = el("img");
  logo.src = "/favicon.svg"; logo.alt = "";
  brand.append(logo, el("span", "", label));
  head.append(brand, el("span", "answer-meta", meta));
  card.append(head);
  return card;
}
function renderAnswer(r) {
  const retrieval = r.retrieval === "hybrid" ? "Hybridné" : "BM25";
  const time = (r.total_ms / 1000).toLocaleString("sk", {maximumFractionDigits: 1});
  const label = {rag: "Odpoveď zo zdrojov", excerpts: "Nájdené výňatky", insufficient: "Chýba podklad"}[r.kind];
  const card = answerCard(label, retrieval + " · " + time + " s");
  card.append(el("p", "answer-text", r.answer));
  if (r.warning) card.append(el("p", "warning", r.warning));
  const cited = r.sources.filter(s => s.cited);
  if (cited.length) {
    const refs = el("div", "citations");
    for (const src of cited) {
      const a = sourceLink(src, "[" + src.id + "] " + (src.kind === "pdf" ? src.title : "OWL") + " · " + src.locator);
      a.className = "citation";
      refs.append(a);
    }
    card.append(refs);
  }
  if (r.sources.length) {
    const evidence = el("details", "evidence");
    evidence.open = r.kind === "excerpts";
    evidence.append(el("summary", "", "Nájdené úryvky (" + r.sources.length + ")"));
    for (const src of r.sources) {
      const details = el("details", "evidence-card");
      details.open = r.kind === "excerpts" && src === r.sources[0];
      details.append(el("summary", "", "[" + src.id + "] " + src.kind.toUpperCase() + " · " + src.title
        + " · " + src.locator + (src.cited ? " · citované" : "")));
      details.append(el("p", "", src.text));
      details.append(sourceLink(src, src.kind === "pdf" ? "Otvoriť stranu PDF ↗" : "Stiahnuť ontológiu ↓"));
      evidence.append(details);
    }
    card.append(evidence);
  }
  return card;
}
async function send(question) {
  question = question.trim();
  if (pending || !question) return;
  if (question.length < 2) {
    q.setCustomValidity("Zadaj aspoň dva znaky.");
    q.reportValidity();
    return;
  }
  pending = true;
  q.value = "";
  $("intro").hidden = true;
  $("send").disabled = true;
  $("clear").hidden = false;
  $("clear").disabled = true;
  messages.append(el("div", "question-bubble", question));
  const waiting = answerCard("Motor Rent");
  waiting.append(el("p", "loading", "Vyhľadávam zdroje a pripravujem výsledok…"));
  messages.append(waiting);
  bottom();
  try {
    const r = await api("/api/ask", {
      question, retrieval: $("mode").value, scope: $("scope").value, generate: $("generate").checked
    });
    waiting.replaceWith(renderAnswer(r));
  } catch (err) {
    const failed = answerCard("Požiadavka sa nepodarila");
    failed.append(el("p", "answer-text", err.message));
    waiting.replaceWith(failed);
    q.value = question;
  } finally {
    pending = false;
    $("send").disabled = false;
    $("clear").disabled = false;
    bottom();
  }
}
$("ask-form").addEventListener("submit", (event) => { event.preventDefault(); send(q.value); });
q.addEventListener("input", () => q.setCustomValidity(""));
q.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault(); $("ask-form").requestSubmit();
  }
});
document.querySelectorAll(".example").forEach(button => button.addEventListener("click", () => send(button.dataset.question)));
$("nav-chat").addEventListener("click", () => showPane("chat"));
$("nav-sources").addEventListener("click", () => showPane("sources"));
$("settings-toggle").addEventListener("click", () => {
  const settings = $("settings");
  settings.hidden = !settings.hidden;
  $("settings-toggle").setAttribute("aria-expanded", String(!settings.hidden));
  if (!settings.hidden) bottom();
});
$("mode").addEventListener("change", updateMode);
$("clear").addEventListener("click", () => {
  if (pending) return;
  messages.replaceChildren();
  $("intro").hidden = false;
  $("clear").hidden = true;
  q.value = "";
  q.focus();
  window.scrollTo(0,0);
});
$("reindex").addEventListener("click", async () => {
  if (indexBusy) return;
  indexBusy = true;
  $("reindex").disabled = true;
  $("index-note").textContent = "Načítavam dokumenty a obnovujem index…";
  try { applyStatus(await api("/api/reindex", {})); }
  catch (err) { $("index-note").textContent = err.message; }
  finally { indexBusy = false; $("reindex").disabled = false; }
});
refresh();
