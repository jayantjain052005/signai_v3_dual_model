/* ═══════════════════════════════════════════════════════════════
   SignAI — Dual Model JS  |  Words + Alphabet modes
   ═══════════════════════════════════════════════════════════════ */

// ── App state ────────────────────────────────────────────────────
const S = {
  running:       false,
  mode:          "words",   // "words" | "alpha"
  autoSpeak:     false,
  darkMode:      true,
  history:       [],
  MAX_HISTORY:   12,
  sentence:      [],
  lastStable:    null,
  stableAt:      null,
  lastSpoken:    null,
  SPEAK_DELAY:   1100,
  heroSign:      null,
  session: { total:0, confSum:0, counts:{} },
  // Arc constants
  ARC_CIRCUM:    201,   // 2π×32 (small HUD arc)
  BIG_CIRCUM:    352,   // 2π×56 (right panel big arc)
};

// ── Boot ─────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  checkStatus();
  bindGallery();
  bindSearch();
});

// ── Mode switching ────────────────────────────────────────────────
async function switchMode(mode) {
  if (S.mode === mode) return;
  S.mode = mode;
  S.lastStable = null; S.stableAt = null; S.lastSpoken = null; S.heroSign = null;

  // Visual mode swap
  const isAlpha = mode === "alpha";
  document.getElementById("btnModeWords").className = "mode-btn" + (isAlpha ? "" : " active");
  document.getElementById("btnModeAlpha").className = "mode-btn" + (isAlpha ? " alpha-active" : "");

  // Gallery swap
  document.getElementById("galleryWords").style.display = isAlpha ? "none" : "grid";
  document.getElementById("galleryAlpha").style.display = isAlpha ? "grid" : "none";

  // Strip
  const dot = document.querySelector(".ms-dot");
  dot.className = "ms-dot " + (isAlpha ? "alpha-dot" : "words-dot");
  document.getElementById("modeStripLabel").innerHTML =
    isAlpha ? "ALPHABET MODE" : "WORDS &amp; PHRASES MODE";

  // HUD sign colour
  document.getElementById("hudSign").className = "hud-sign" + (isAlpha ? " alpha-mode" : "");

  // Panel chip
  document.getElementById("modelChip").className = "model-chip" + (isAlpha ? " alpha" : "");
  document.getElementById("modelChip").textContent = isAlpha ? "🔤 1-Hand" : "🧠 2-Hand";
  document.getElementById("refTitle").textContent  = isAlpha ? "Alphabet Reference" : "Reference Signs";
  document.getElementById("galleryLabel").textContent = isAlpha ? "A–Z SIGNS" : "ALL SIGNS";

  clearHero();
  resetArc();

  // Tell server
  if (S.running) {
    await fetch(`/api/mode/${mode}`, { method: "POST" });
  }
}

// ── Camera controls ───────────────────────────────────────────────
async function startCamera() {
  setStatus("Connecting…", "");
  const btn = document.getElementById("btnStart");
  btn.disabled = true; btn.textContent = "Connecting…";

  const res  = await fetch("/api/camera/start", { method:"POST" });
  const data = await res.json();

  if (data.ok) {
    S.running = true;
    // Tell server the current mode
    await fetch(`/api/mode/${S.mode}`, { method:"POST" });
    showFeed();
    startPoll();
    setStatus("Running", "running");
    document.getElementById("btnStop").disabled = false;
    document.getElementById("btnSnap").disabled = false;
  } else {
    showIdleMsg("⚠ " + data.message);
    btn.disabled = false; btn.textContent = "▶ Start Camera";
    setStatus("Error", "error");
  }
}

async function stopCamera() {
  stopPoll();
  await fetch("/api/camera/stop", { method:"POST" });
  S.running = false;
  hideFeed();
  setStatus("Ready", "ready");
  document.getElementById("btnStart").disabled = false;
  document.getElementById("btnStart").textContent = "▶ Start Camera";
  document.getElementById("btnStop").disabled = true;
  document.getElementById("btnSnap").disabled = true;
  resetArc();
  document.getElementById("hudSign").textContent = "—";
  document.getElementById("hudSub").textContent  = "Waiting…";
  clearHero();
}

function showFeed() {
  document.getElementById("videoFeed").src = "/video_feed?" + Date.now();
  document.getElementById("videoFeed").style.display = "block";
  document.getElementById("camIdle").style.display   = "none";
  document.getElementById("camOverlay").style.display = "block";
}
function hideFeed() {
  document.getElementById("videoFeed").src = "";
  document.getElementById("videoFeed").style.display  = "none";
  document.getElementById("camIdle").style.display    = "flex";
  document.getElementById("camOverlay").style.display = "none";
}
function showIdleMsg(msg) {
  document.getElementById("camIdle").innerHTML =
    `<div class="idle-emoji">⚠️</div><div class="idle-h">Error</div><div class="idle-sub">${msg}</div>`;
}

// ── Polling ───────────────────────────────────────────────────────
let _pollTimer = null;
function startPoll() {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(poll, 130);
}
function stopPoll() {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = null;
}

async function poll() {
  if (!S.running) return;
  try {
    const r = await fetch("/api/prediction");
    const d = await r.json();
    updateHUD(d);
  } catch (_) {}
}

// ── HUD update ────────────────────────────────────────────────────
function updateHUD(d) {
  const { sign, confidence, stable, hand_count, message, fps, mode } = d;

  // FPS
  document.getElementById("camFps").textContent = fps ? `${fps} FPS` : "-- FPS";

  // Hand pips
  document.getElementById("hL").className = "hand-pip" + (hand_count >= 1 ? " on" : "");
  document.getElementById("hR").className = "hand-pip" + (hand_count >= 2 ? " on" : "");

  // Notice overlay
  const notice = document.getElementById("camNotice");
  if (!sign && hand_count === 0) {
    notice.textContent = "👋 Show your hands"; notice.style.display = "block";
  } else if (mode === "words" && hand_count === 1) {
    notice.textContent = "🤲 Show both hands"; notice.style.display = "block";
  } else {
    notice.style.display = "none";
  }

  if (sign && stable) {
    let displaySign = sign;

// fix model typo
if (displaySign === "recipt") {
  displaySign = "receipt";
}

// optional (cleaner UI)
if (displaySign === "Thankyou") {
  displaySign = "thank you";
}

document.getElementById("hudSign").textContent = displaySign;
document.getElementById("hudSub").textContent  = message || displaySign;
    setArc(confidence);
    highlightCard(sign, mode);
    updateHero(sign, confidence, mode);

    // Auto-speak
    if (sign !== S.lastStable) {
      S.lastStable = sign; S.stableAt = Date.now(); S.lastSpoken = null;
    } else if (S.autoSpeak && Date.now() - S.stableAt > S.SPEAK_DELAY && sign !== S.lastSpoken) {
      speakSign(sign); S.lastSpoken = sign;
    }

    // History
    if (!S.history.length || S.history[0].sign !== sign) addHistory(sign, confidence, mode);

  } else if (!sign || hand_count === 0) {
    document.getElementById("hudSign").textContent = "—";
    document.getElementById("hudSub").textContent  = "Waiting…";
    resetArc();
    clearHero();
    S.lastStable = null; S.stableAt = null; S.lastSpoken = null;
    document.querySelectorAll(".ref-card").forEach(c => c.classList.remove("lit","lit-a"));
  }
}

// ── Arc helpers ───────────────────────────────────────────────────
function setArc(val) {
  const pct  = Math.round(val * 100);
  const fSmall = (pct / 100) * S.ARC_CIRCUM;
  const fBig   = (pct / 100) * S.BIG_CIRCUM;
  document.getElementById("arcFill").setAttribute("stroke-dasharray", `${fSmall} ${S.ARC_CIRCUM}`);
  document.getElementById("arcPct").textContent  = `${pct}%`;
  document.getElementById("bigArcFill").setAttribute("stroke-dasharray", `${fBig} ${S.BIG_CIRCUM}`);
  document.getElementById("bigPct").textContent  = `${pct}%`;
}
function resetArc() { setArc(0); }

// ── Gallery card highlight ────────────────────────────────────────
function highlightCard(sign, mode) {
  const litClass = mode === "alpha" ? "lit-a" : "lit";
  document.querySelectorAll(".ref-card").forEach(c => {
    c.classList.remove("lit","lit-a");
    if (c.dataset.sign === sign && c.dataset.mode === mode) {
      c.classList.add(litClass);
      c.scrollIntoView({ block:"nearest", behavior:"smooth" });
    }
  });
  // Live pip colour
  const pip = document.getElementById("livePip");
  pip.className = "live-pip on" + (mode === "alpha" ? " alpha" : "");
}

// ── Hero card ─────────────────────────────────────────────────────
function updateHero(sign, confidence, mode) {
  const hero = document.getElementById("heroCard");
  if (sign !== S.heroSign) {
    S.heroSign = sign;
    document.getElementById("heroImg").src = `/api/sign_image/${mode}/${encodeURIComponent(sign)}`;
  }
  document.getElementById("heroSign").textContent = sign;
  document.getElementById("heroConf").textContent = Math.round(confidence * 100) + "%";
  hero.style.display = "block";
}
function clearHero() {
  document.getElementById("heroCard").style.display = "none";
  document.getElementById("livePip").className = "live-pip";
  S.heroSign = null;
}

// ── History ───────────────────────────────────────────────────────
function addHistory(sign, conf, mode) {
  S.history.unshift({ sign, conf, mode });
  if (S.history.length > S.MAX_HISTORY) S.history.pop();
  S.session.total++;
  S.session.confSum += conf;
  S.session.counts[sign] = (S.session.counts[sign] || 0) + 1;
  renderHistory();
  renderStats();
}
function renderHistory() {
  const el = document.getElementById("histList");
  document.getElementById("histBadge").textContent = S.history.length;
  if (!S.history.length) {
    el.innerHTML = '<div class="hist-empty">No predictions yet</div>'; return;
  }
  el.innerHTML = S.history.map(h =>
    `<div class="hist-item" onclick="speakSign('${h.sign}')">
       <span class="hist-sign">${h.sign}</span>
       <span class="hist-conf">${Math.round(h.conf * 100)}%</span>
       <span class="hist-mode ${h.mode === 'alpha' ? 'alpha' : ''}">${h.mode === 'alpha' ? 'ABC' : 'WRD'}</span>
     </div>`
  ).join("");
}
function renderStats() {
  const { total, confSum, counts } = S.session;
  document.getElementById("svTotal").textContent = total;
  document.getElementById("svAvg").textContent   = total ? Math.round((confSum / total) * 100) + "%" : "0%";
  const top = Object.entries(counts).sort((a,b) => b[1]-a[1])[0];
  document.getElementById("svTop").textContent   = top ? top[0].split(" ")[0] : "—";
}
function resetAll() {
  S.history = []; S.session = { total:0, confSum:0, counts:{} }; S.sentence = [];
  renderHistory(); renderStats(); renderSentence(); resetArc();
  document.getElementById("hudSign").textContent = "—";
  document.getElementById("hudSub").textContent  = "Waiting…";
  clearHero();
}

// ── Sentence builder ──────────────────────────────────────────────
function addWord() {
  const sign = document.getElementById("hudSign").textContent;
  if (!sign || sign === "—") return;
  S.sentence.push(sign);
  renderSentence();
}
function clearSentence() { S.sentence = []; renderSentence(); }
function renderSentence() {
  const box = document.getElementById("sentenceBox");
  if (!S.sentence.length) {
    box.innerHTML = '<span class="sentence-placeholder">Detected signs will appear here…</span>'; return;
  }
  box.innerHTML = S.sentence.map((w, i) =>
    `<span class="word-chip" onclick="removeWord(${i})" title="Click to remove">${w}</span>`
  ).join("");
}
function removeWord(i) { S.sentence.splice(i, 1); renderSentence(); }
function speakSentence() {
  if (S.sentence.length) speak(S.sentence.join(" "));
}

// ── Voice ─────────────────────────────────────────────────────────
function speakCurrent() {
  const sign = document.getElementById("hudSign").textContent;
  if (sign && sign !== "—") speakSign(sign);
}
function speakSign(text) { if (text) speak(text); }
function speak(text) {
  if (!window.speechSynthesis || !text) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.toLowerCase());
  u.rate = 0.88; u.pitch = 1.0; u.volume = 1.0;
  const voices = window.speechSynthesis.getVoices();
  const v = voices.find(v => v.name.includes("Google") || v.name.includes("Samantha"));
  if (v) u.voice = v;
  window.speechSynthesis.speak(u);
}

// ── Gallery & search ──────────────────────────────────────────────
function bindGallery() {
  document.querySelectorAll(".ref-card").forEach(card => {
    card.addEventListener("click", () => speakSign(card.dataset.sign));
  });
}
function bindSearch() {
  document.getElementById("searchInput").addEventListener("input", function () {
    const q = this.value.toLowerCase();
    document.querySelectorAll(".ref-card").forEach(c => {
      c.style.display = c.dataset.sign.toLowerCase().includes(q) ? "" : "none";
    });
  });
}

// ── Screenshot ────────────────────────────────────────────────────
async function takeSnapshot() {
  const r = await fetch("/api/snapshot");
  const d = await r.json();
  if (d.ok) {
    const a = document.createElement("a");
    a.href = `data:image/jpeg;base64,${d.image}`;
    a.download = `signai_${Date.now()}.jpg`;
    a.click();
  }
}

// ── Settings ──────────────────────────────────────────────────────
function toggleAutoSpeak(el) {
  S.autoSpeak = el.checked;
  if (!el.checked) S.lastSpoken = null;
}
function toggleDark() {
  S.darkMode = !S.darkMode;
  document.body.className = S.darkMode ? "dark" : "light";
  document.getElementById("chkDark").checked = S.darkMode;
}
function toggleFullscreen() {
  const el = document.querySelector(".cam-shell");
  if (!document.fullscreenElement) el.requestFullscreen?.();
  else document.exitFullscreen?.();
}

// ── Status ────────────────────────────────────────────────────────
function setStatus(text, cls) {
  document.getElementById("sDot").className  = "s-dot " + cls;
  document.getElementById("sText").textContent = text;
}
async function checkStatus() {
  try {
    const r = await fetch("/api/camera/status");
    const d = await r.json();
    if (d.words_ready || d.alpha_ready) setStatus("Ready", "ready");
    else setStatus("No Model", "error");
    // Update count chips
    const wc = (d.words_classes||[]).length;
    const ac = (d.alpha_classes||[]).length;
    document.getElementById("countChip").textContent =
      S.mode === "alpha" ? `${ac} signs` : `${wc} signs`;
  } catch (_) { setStatus("Offline","error"); }
}

if (window.speechSynthesis) {
  window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
}
