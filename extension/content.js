// content.js — floating button + speaker/participant tracking

const PLATFORM = (() => {
  const u = window.location.href;
  if (u.includes("meet.google.com")) return "meet";
  if (u.includes("zoom.us"))         return "zoom";
  if (u.includes("teams.microsoft")) return "teams";
  return "unknown";
})();

const SELECTORS = {
  meet: {
    participants:  '[data-participant-id] [data-self-name], .zWGUib',
    activeSpeaker: '[data-speaking="true"] [data-self-name], .KF4T6b',
  },
};

let lastSpeaker    = null;
let isRecording    = false;
let floatingBtn    = null;
let buttonCreated  = false;

// ── Floating Button ────────────────────────────────────────────
function createFloatingButton() {
  if (document.getElementById("mom-floating-btn")) return;

  floatingBtn = document.createElement("div");
  floatingBtn.id = "mom-floating-btn";
  floatingBtn.innerHTML = `
    <span id="mom-btn-dot" style="width:8px;height:8px;border-radius:50%;background:white;display:inline-block;flex-shrink:0;"></span>
    <span id="mom-btn-label">Start MoM</span>
  `;
  floatingBtn.style.cssText = `
    position:fixed; bottom:80px; right:20px; z-index:999999;
    cursor:pointer; border-radius:24px; background:#534AB7;
    color:white; padding:10px 18px; font-size:13px;
    font-family:sans-serif; display:flex; align-items:center;
    gap:8px; box-shadow:0 4px 12px rgba(0,0,0,0.3); user-select:none;
    transition: background 0.2s;
  `;
  document.body.appendChild(floatingBtn);
  floatingBtn.addEventListener("click", () => {
    if (isRecording) stopRecording();
    else startRecording();
  });
}

// ── Button states ──────────────────────────────────────────────
const BTN_STATES = {
  idle:       { bg: "#534AB7", text: "Start MoM"     },
  loading:    { bg: "#888888", text: "Starting..."    },
  recording:  { bg: "#E24B4A", text: "Stop MoM"      },
  processing: { bg: "#F59E0B", text: "Processing..."  },
};

function setButtonState(state) {
  const dot   = document.getElementById("mom-btn-dot");
  const label = document.getElementById("mom-btn-label");
  if (!floatingBtn || !dot || !label) return;
  const s = BTN_STATES[state] || BTN_STATES.idle;
  floatingBtn.style.background = s.bg;
  label.textContent            = s.text;
}

// ── Start ──────────────────────────────────────────────────────
function startRecording() {
  setButtonState("loading");
  chrome.runtime.sendMessage({ action: "FLOATING_START" }, (res) => {
    if (chrome.runtime.lastError || !res?.success) {
      alert("Could not start: " + (res?.error || chrome.runtime.lastError?.message || "unknown"));
      setButtonState("idle");
      return;
    }
    isRecording = true;
    setButtonState("recording");
  });
}

// ── Stop ───────────────────────────────────────────────────────
function stopRecording() {
  isRecording = false;
  setButtonState("processing");
  chrome.runtime.sendMessage({ action: "FLOATING_STOP" });
}

// ── Messages from background ───────────────────────────────────
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.action === "RECORDING_STARTED") { isRecording = true;  setButtonState("recording");  }
  if (msg.action === "RECORDING_STOPPED") { isRecording = false; setButtonState("processing"); }
  if (msg.action === "MOM_READY")         { isRecording = false; setButtonState("idle");       }
});

// ── Participants ───────────────────────────────────────────────
function sendParticipants() {
  const sel = SELECTORS[PLATFORM]?.participants;
  if (!sel) return;
  const names = [...document.querySelectorAll(sel)]
    .map((el) => el.textContent.trim()).filter(Boolean);
  if (names.length > 0)
    chrome.runtime.sendMessage({ action: "PARTICIPANTS_UPDATE", participants: [...new Set(names)] });
}

// ── Speaker tracking ───────────────────────────────────────────
function watchActiveSpeaker() {
  new MutationObserver(() => {
    if (!isRecording) return;
    const sel  = SELECTORS[PLATFORM]?.activeSpeaker;
    const name = sel ? document.querySelector(sel)?.textContent?.trim() : null;
    if (name && name !== lastSpeaker) {
      lastSpeaker = name;
      chrome.runtime.sendMessage({ action: "SPEAKER_UPDATE", name });
    }
  }).observe(document.body, { childList: true, subtree: true, attributes: true });
}

// ── Check if inside active meeting ────────────────────────────
function isInActiveMeeting() {
  const url = window.location.href;
  if (url.includes("meet.google.com")) {
    // Must match meeting code pattern
    if (!/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}/.test(url)) return false;
    // Must have mic controls (only present inside active meeting, not pre-join)
    return !!document.querySelector(
      '[aria-label="Turn off microphone"], [aria-label="Turn on microphone"], [data-is-muted]'
    );
  }
  if (url.includes("zoom.us"))         return url.includes("/wc/") || url.includes("/j/");
  if (url.includes("teams.microsoft")) return url.includes("/meet/") || url.includes("callId");
  return false;
}

// ── Init ───────────────────────────────────────────────────────
function tryShowButton() {
  if (buttonCreated) return;
  if (!isInActiveMeeting()) return;
  buttonCreated = true;
  createFloatingButton();
  sendParticipants();
  watchActiveSpeaker();
  setInterval(sendParticipants, 30000);
}

// Watch DOM for join event (Meet is SPA — no page reload on join)
new MutationObserver(() => { if (!buttonCreated) tryShowButton(); })
  .observe(document.body, { childList: true, subtree: true });

setTimeout(tryShowButton, 3000);