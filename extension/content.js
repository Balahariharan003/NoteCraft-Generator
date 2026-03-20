// ── content.js ────────────────────────────────────────────────
// Runs inside Google Meet / Zoom tab
// Job 1: Scrape participant names
// Job 2: Watch active speaker and report with timestamp

// ── Platform detection ─────────────────────────────────────────
const PLATFORM = (() => {
  const url = window.location.href;
  if (url.includes("meet.google.com")) return "meet";
  if (url.includes("zoom.us"))         return "zoom";
  if (url.includes("teams.microsoft")) return "teams";
  return "unknown";
})();

// ── DOM Selectors per platform ─────────────────────────────────
const SELECTORS = {
  meet: {
    // Participant names in the people panel
    participants: '[data-participant-id] [data-self-name], .zWGUib',
    // Active speaker tile (Google Meet highlights with a border)
    activeSpeaker: '[data-speaking="true"] [data-self-name], .KF4T6b',
  },
  zoom: {
    participants: '.participants-item__display-name',
    activeSpeaker: '.video-avatar__avatar--active .participants-item__display-name',
  },
  teams: {
    participants: '.participant-item__name',
    activeSpeaker: '.video-tile--dominant .participant-item__name',
  },
};

let lastSpeaker = null;
let observer = null;

// ── 1. Scrape participant names ────────────────────────────────
function scrapeParticipants() {
  const sel = SELECTORS[PLATFORM]?.participants;
  if (!sel) return [];

  const elements = document.querySelectorAll(sel);
  const names = Array.from(elements)
    .map((el) => el.textContent.trim())
    .filter((name) => name.length > 0);

  // Remove duplicates
  return [...new Set(names)];
}

// ── 2. Get current active speaker ────────────────────────────
function getActiveSpeaker() {
  const sel = SELECTORS[PLATFORM]?.activeSpeaker;
  if (!sel) return null;

  const el = document.querySelector(sel);
  return el ? el.textContent.trim() : null;
}

// ── 3. Send participants to background.js ─────────────────────
function sendParticipants() {
  const participants = scrapeParticipants();
  if (participants.length > 0) {
    chrome.runtime.sendMessage({
      action: "PARTICIPANTS_UPDATE",
      participants,
    });
  }
}

// ── 4. Watch for active speaker changes ───────────────────────
function watchActiveSpeaker() {
  observer = new MutationObserver(() => {
    const currentSpeaker = getActiveSpeaker();

    // Only send when speaker actually changes
    if (currentSpeaker && currentSpeaker !== lastSpeaker) {
      lastSpeaker = currentSpeaker;
      chrome.runtime.sendMessage({
        action: "SPEAKER_UPDATE",
        name: currentSpeaker,
      });
    }
  });

  // Watch the entire body for DOM changes
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["data-speaking", "class"],
  });
}

// ── 5. Start everything ────────────────────────────────────────
function init() {
  // Wait for the meeting UI to fully load
  setTimeout(() => {
    sendParticipants();   // initial scrape
    watchActiveSpeaker(); // start watching

    // Re-scrape participants every 30 seconds
    // (people join late — this catches them)
    setInterval(sendParticipants, 30000);
  }, 3000);
}

// ── 6. Listen for messages from background.js ─────────────────
chrome.runtime.onMessage.addListener((message) => {
  if (message.action === "GET_PARTICIPANTS") {
    sendParticipants();
  }
  if (message.action === "STOP_OBSERVING") {
    if (observer) {
      observer.disconnect();
      observer = null;
    }
  }
});

// Start when page is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}