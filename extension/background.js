// background.js — service worker

// ── Toggle overlay when extension icon is clicked ──────────────
chrome.action.onClicked.addListener((tab) => {
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
let offscreenCreated = false;

async function ensureOffscreen() {
  if (offscreenCreated) return;
  try {
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["USER_MEDIA"],
      justification: "Capture microphone audio independently of the meeting page"
    });
    offscreenCreated = true;
    console.log("✅ Offscreen document created for mic capture");
  } catch (e) {
    if (e.message?.includes("already exists")) {
      offscreenCreated = true;
    } else {
      console.error("❌ Offscreen creation failed:", e);
    }
  }
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
    ensureOffscreen().then(() => {
      chrome.runtime.sendMessage({ target: "offscreen", action: "START_MIC" }).then(() => {
        sendResponse({ ok: true });
      }).catch(err => {
        console.error("Failed to start offscreen mic:", err);
        sendResponse({ ok: false, error: err.message });
      });
    });
    return true; // async
  }

  // Content script asks to stop mic
  if (message.action === "STOP_OFFSCREEN_MIC") {
    chrome.runtime.sendMessage({ target: "offscreen", action: "STOP_MIC" }).catch(() => {});
    sendResponse({ ok: true });
    return;
  }

  // Content script asks for a mic audio chunk
  if (message.action === "GET_OFFSCREEN_MIC_CHUNK") {
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
    
    // Tab audio from base64/array back to Blob
    const tabBlob = new Blob([new Uint8Array(tabAudio)], { type: "audio/webm" });
    fd.append("audio", tabBlob, `chunk_${chunkIndex}.webm`);
    
    // Mic audio if present
    if (micAudio) {
      const micBlob = new Blob([new Uint8Array(micAudio)], { type: "audio/webm" });
      fd.append("mic_audio", micBlob, `mic_chunk_${chunkIndex}.webm`);
    }

    fetch("http://localhost:8000/upload-chunk", { method: "POST", body: fd })
      .then(r => r.json())
      .then(res => console.log(`✅ Chunk ${chunkIndex} uploaded successfully`, res))
      .catch(err => console.error(`❌ Chunk ${chunkIndex} upload FAILED:`, err));
      
    return;
  }
});