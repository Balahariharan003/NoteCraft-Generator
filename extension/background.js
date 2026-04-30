// background.js — service worker

// ── Keep service worker alive ────────────────────────────────
// Prevents "Extension context invalidated" errors by preventing
// the background service worker from being terminated
let keepaliveTimer = null;

function resetKeepalive() {
  if (keepaliveTimer) clearTimeout(keepaliveTimer);
  keepaliveTimer = setTimeout(() => {
    console.log("Keepalive tick");
    resetKeepalive();
  }, 20000); // Reset every 20 seconds
}

// Initialize keepalive
resetKeepalive();

// Reset keepalive on any activity
chrome.tabs.onUpdated.addListener(resetKeepalive);
chrome.runtime.onMessage.addListener(() => resetKeepalive());

// ── Toggle overlay when extension icon is clicked ──────────────
chrome.action.onClicked.addListener((tab) => {
  if (!tab || !tab.url || !(tab.url.startsWith('http://') || tab.url.startsWith('https://'))) {
    console.warn("Skipping action click on unsupported tab URL:", tab?.url);
    return;
  }

  chrome.tabs.sendMessage(tab.id, { action: "TOGGLE_OVERLAY" }).catch((err) => {
    console.warn("Content script not ready, injecting:", err);
    chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['content.js']
    }).then(() => {
      chrome.tabs.sendMessage(tab.id, { action: "TOGGLE_OVERLAY" }).catch(() => {});
    }).catch(e => console.error("Injection failed:", e));
  });
});

// ── Auto-inject on install/update ──────────────────────────────
chrome.runtime.onInstalled.addListener(async () => {
  const tabs = await chrome.tabs.query({ url: ["*://meet.google.com/*", "*://*.zoom.us/*", "*://teams.microsoft.com/*"] });
  for (let tab of tabs) {
    try {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content.js'] });
    } catch (e) {
      console.warn("Auto-inject failed for tab:", tab.id, e);
    }
  }
});

// ── Offscreen document management ──────────────────────────────
let offscreenCreating = null;
let offscreenReady = false;
let lastOffscreenCheck = 0;

async function ensureOffscreen() {
  // If already ready, return immediately
  if (offscreenReady) return Promise.resolve();
  
  // If already creating, wait for that promise
  if (offscreenCreating) return offscreenCreating;
  
  offscreenCreating = (async () => {
    try {
      // Debounce checks to avoid race conditions (min 500ms between checks)
      const now = Date.now();
      if (now - lastOffscreenCheck < 500) {
        await new Promise(resolve => setTimeout(resolve, 500 - (now - lastOffscreenCheck)));
      }
      lastOffscreenCheck = Date.now();
      
      // First, check if offscreen already exists by trying to send a ping
      try {
        const pingPromise = chrome.runtime.sendMessage({ target: "offscreen", action: "PING" });
        const timeoutPromise = new Promise((_, reject) => 
          setTimeout(() => reject(new Error("PING_TIMEOUT")), 1000)
        );
        await Promise.race([pingPromise, timeoutPromise]);
        console.log("✅ Offscreen document already exists");
        offscreenReady = true;
        return;
      } catch (e) {
        // Offscreen doesn't exist, proceed with creation
        console.log("ℹ️ Creating offscreen document...");
      }
      
      // Create the offscreen document
      try {
        await chrome.offscreen.createDocument({
          url: "offscreen.html",
          reasons: ["USER_MEDIA"],
          justification: "Capture microphone audio independently of the meeting page"
        });
        console.log("✅ Offscreen document created for mic capture");
      } catch (createErr) {
        // If it's already exists error, just mark as ready
        if (createErr.message?.includes("already exists")) {
          console.log("✅ Offscreen document already existed");
          offscreenReady = true;
          return;
        }
        throw createErr;
      }
      
      // Wait for the offscreen to fully initialize
      await new Promise(resolve => setTimeout(resolve, 300));
      offscreenReady = true;
      
    } catch (e) {
      console.error("❌ Offscreen creation failed:", e);
      offscreenReady = false;
      throw e; // Re-throw so caller knows it failed
    } finally {
      offscreenCreating = null;
    }
  })();
  
  return offscreenCreating;
}

// ── Message relay ──────────────────────────────────────────────
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Relay speaker updates
  if (message.action === "SPEAKER_UPDATE" || message.action === "PARTICIPANTS_UPDATE") {
    if (sender.tab) {
      chrome.tabs.sendMessage(sender.tab.id, message).catch(() => {});
    }
    return;
  }

  // Content script asks to start mic via offscreen
  if (message.action === "START_OFFSCREEN_MIC") {
    ensureOffscreen()
      .then(() => chrome.runtime.sendMessage({ target: "offscreen", action: "START_MIC" }))
      .then((res) => {
        if (res && res.ok) {
          sendResponse({ ok: true });
        } else {
          console.error("Failed to start offscreen mic:", res?.error);
          // If it's a permission error, opening the offscreen page as a tab allows the user to grant it
          if (res?.error?.includes("NotAllowedError") || res?.error?.includes("DOMException")) {
            chrome.tabs.create({ url: chrome.runtime.getURL("offscreen.html#allow") });
          }
          sendResponse({ ok: false, error: res?.error });
        }
      })
      .catch(err => {
        console.error("Failed to ensure/start offscreen mic:", err);
        sendResponse({ ok: false, error: err.message });
      });
    return true; // async
  }

  // Content script asks to stop mic
  if (message.action === "STOP_OFFSCREEN_MIC") {
    if (offscreenReady) {
      chrome.runtime.sendMessage({ target: "offscreen", action: "STOP_MIC" }).catch(() => {});
    }
    sendResponse({ ok: true });
    return;
  }

  // Content script asks for a mic audio chunk
  if (message.action === "GET_OFFSCREEN_MIC_CHUNK") {
    if (!offscreenReady) {
      sendResponse({ ok: false, error: "Offscreen not ready" });
      return true;
    }
    chrome.runtime.sendMessage({ target: "offscreen", action: "GET_MIC_CHUNK" }).then(response => {
      sendResponse(response);
    }).catch(err => {
      sendResponse({ ok: false, error: err.message });
    });
    return true; // async
  }

  // Content script asks to upload a chunk
  if (message.action === "UPLOAD_CHUNK_DATA") {
    const { sessionId, chunkIndex, timeline, participants, tabAudio, micAudio } = message;
    
    const fd = new FormData();
    fd.append("session_id", sessionId);
    fd.append("chunk_index", chunkIndex);
    fd.append("speaker_timeline", timeline);
    fd.append("participants", participants);
    
    // Ensure we have Uint8Arrays even if serialized as objects
    const tabUint8 = (tabAudio instanceof Uint8Array) ? tabAudio : new Uint8Array(Object.values(tabAudio));
    const tabBlob = new Blob([tabUint8], { type: "audio/webm" });
    fd.append("audio", tabBlob, `chunk_${chunkIndex}.webm`);
    
    // Mic audio if present
    if (micAudio) {
      const micUint8 = (micAudio instanceof Uint8Array) ? micAudio : new Uint8Array(Object.values(micAudio));
      const micBlob = new Blob([micUint8], { type: "audio/webm" });
      fd.append("mic_audio", micBlob, `mic_chunk_${chunkIndex}.webm`);
    }

    fetch("http://localhost:8000/upload-chunk", { method: "POST", body: fd })
      .then(async r => {
        if (!r.ok) {
          const txt = await r.text();
          throw new Error(`Server returned ${r.status}: ${txt}`);
        }
        return r.json();
      })
      .then(res => console.log(`✅ Chunk ${chunkIndex} uploaded successfully`, res))
      .catch(err => console.error(`❌ Chunk ${chunkIndex} upload FAILED:`, err));
      
    return;
  }
});