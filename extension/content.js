// content.js — injected into Google Meet / Zoom / Teams
// Job: scrape participant names and active speaker timeline

const PLATFORM = (() => {
  if (location.href.includes("meet.google.com")) return "meet";
  if (location.href.includes("zoom.us"))         return "zoom";
  if (location.href.includes("teams.microsoft")) return "teams";
  return "unknown";
})();

const SELECTORS = {
  meet:  {
    participants:  ".zWGUib",
    activeSpeaker: ".KF4T6b",
  },
  zoom:  {
    participants:  ".participants-item__display-name",
    activeSpeaker: ".video-avatar__avatar--active .participants-item__display-name",
  },
  teams: {
    participants:  ".participant-item__name",
    activeSpeaker: ".video-tile--dominant .participant-item__name",
  },
};

let lastSpeaker = null;
let observer    = null;

// ── Scrape participant names ───────────────────────────────────
function scrapeParticipants() {
  const sel = SELECTORS[PLATFORM]?.participants;
  if (!sel) return [];
  return [...new Set(
    Array.from(document.querySelectorAll(sel))
      .map(el => el.textContent.trim())
      .filter(n => n.length > 0)
  )];
}

function sendParticipants() {
  const participants = scrapeParticipants();
  if (participants.length > 0) {
    chrome.runtime.sendMessage({ action: "PARTICIPANTS_UPDATE", participants });
  }
}

// ── Watch active speaker ───────────────────────────────────────
function watchActiveSpeaker() {
  observer = new MutationObserver(() => {
    const sel = SELECTORS[PLATFORM]?.activeSpeaker;
    if (!sel) return;
    const el   = document.querySelector(sel);
    const name = el?.textContent.trim();
    if (name && name !== lastSpeaker) {
      lastSpeaker = name;
      chrome.runtime.sendMessage({ action: "SPEAKER_UPDATE", name });
    }
  });
  observer.observe(document.body, {
    childList:       true,
    subtree:         true,
    attributes:      true,
    attributeFilter: ["data-speaking", "class"],
  });
}

// ── Init ───────────────────────────────────────────────────────
function init() {
  setTimeout(() => {
    sendParticipants();
    watchActiveSpeaker();
    setInterval(sendParticipants, 30000);
  }, 3000);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}