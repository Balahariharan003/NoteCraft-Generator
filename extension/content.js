// content.js — injected into Google Meet / Zoom / Teams
// Combined logic for scraping, UI injection, and recording
// Mic is captured via offscreen document to bypass Meet's mic lock

(function() {
  if (window.notecraftInjected) return;
  window.notecraftInjected = true;

  const BACKEND_URL = "http://localhost:8000";
  const CHUNK_INTERVAL_MS = 30000; // Reduced for faster testing/feedback
  const POLL_INTERVAL = 2000;

  let shadowRoot = null;
  let container = null;
  let widget = null;
  let isMinimized = false;

  // Recording State
  let timerInterval = null;
  let pollInterval = null;
  let chunkInterval = null;
  let elapsedSeconds = 0;
  let currentSession = null;
  let mediaRecorder = null;
  let audioStream = null;
  let chunkIndex = 0;
  let speakerTimeline = [];
  let participants = [];
  let recordingStart = null;
  let isRecording = false;

  const PLATFORM = (() => {
    if (location.href.includes("meet.google.com")) return "meet";
    if (location.href.includes("zoom.us")) return "zoom";
    if (location.href.includes("teams.microsoft")) return "teams";
    return "unknown";
  })();

  const SELECTORS = {
    meet: { 
      participants: ".zWGUib, .ZjG79c, .dwS77e", 
      activeSpeaker: ".KF4T6b, [data-speaking='true'] .zWGUib" 
    },
    zoom: { participants: ".participants-item__display-name", activeSpeaker: ".video-avatar__avatar--active .participants-item__display-name" },
    teams: { participants: ".participant-item__name", activeSpeaker: ".video-tile--dominant .participant-item__name" },
  };

  // ── Scrapers ──────────────────────────────────────────────────
  function scrapeParticipants() {
    const sel = SELECTORS[PLATFORM]?.participants;
    if (!sel) return [];
    return [...new Set(Array.from(document.querySelectorAll(sel)).map(el => el.textContent.trim()).filter(n => n.length > 0))];
  }

  function startScraping() {
    const observer = new MutationObserver(() => {
      const sel = SELECTORS[PLATFORM]?.activeSpeaker;
      if (!sel) return;
      const el = document.querySelector(sel);
      const name = el?.textContent.trim();
      if (name && name !== lastSpeaker && isRecording) {
        lastSpeaker = name;
        console.log("Speaker detected:", name);
        const elapsed = Date.now() - recordingStart;
        speakerTimeline.push({ name, timestamp_ms: elapsed });
      }
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-speaking", "class"] });

    setInterval(() => {
      if (isRecording) participants = scrapeParticipants();
    }, 10000);
  }

  let lastSpeaker = null;

  // ── UI Injection ─────────────────────────────────────────────
  function injectUI() {
    if (document.getElementById("notecraft-root")) return;

    const host = document.createElement("div");
    host.id = "notecraft-root";
    document.body.appendChild(host);
    shadowRoot = host.attachShadow({ mode: "open" });

    container = document.createElement("div");
    container.id = "notecraft-container";
    container.innerHTML = `
      <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@600;700&display=swap');
        :host {
          --bg-main: #0a0a0f;
          --bg-card: rgba(26, 26, 46, 0.95);
          --accent-primary: #6366f1;
          --accent-secondary: #a855f7;
          --text-primary: #ffffff;
          --text-secondary: #94a3b8;
          --danger: #ef4444;
          --success: #22c55e;
          --glass-border: rgba(255, 255, 255, 0.1);
          --font-heading: 'Outfit', sans-serif;
          --font-body: 'Inter', sans-serif;
        }
        #notecraft-container {
          position: fixed;
          top: 20px;
          right: 20px;
          width: 320px;
          background: var(--bg-main);
          background-image: 
            radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.15) 0px, transparent 50%),
            radial-gradient(at 100% 100%, rgba(168, 85, 247, 0.15) 0px, transparent 50%);
          border: 1px solid var(--glass-border);
          border-radius: 16px;
          color: var(--text-primary);
          font-family: var(--font-body);
          z-index: 2147483647;
          box-shadow: 0 10px 30px rgba(0,0,0,0.5);
          display: flex;
          flex-direction: column;
          overflow: hidden;
          transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }
        .header {
          padding: 16px 20px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          border-bottom: 1px solid var(--glass-border);
        }
        .logo { display:flex; align-items:center; gap:8px; }
        .logo-dot { width:10px; height:10px; border-radius:3px; background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary)); animation: rotate 4s linear infinite; }
        .logo-text { font-family: var(--font-heading); font-size: 14px; font-weight:700; letter-spacing:0.05em; background: linear-gradient(to right, #fff, #94a3b8); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
        .controls { display:flex; gap:8px; }
        .btn-icon { background:none; border:none; cursor:pointer; color:var(--text-secondary); padding:4px; border-radius:4px; display:flex; align-items:center; justify-content:center; }
        .btn-icon:hover { background: rgba(255,255,255,0.1); color:white; }
        
        .state { display: none; flex-direction: column; padding: 24px; gap: 20px; align-items: center; }
        .state.active { display: flex; }
        
        #btn-start, #btn-stop, #btn-retry, #btn-new, #btn-new-error { width:100%; }
        .btn { padding:12px; border-radius:10px; border:1px solid var(--glass-border); font-family:var(--font-body); font-size:14px; font-weight:600; cursor:pointer; transition:all 0.2s; display:flex; align-items:center; justify-content:center; gap:8px; text-decoration:none; }
        .btn-primary { background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary)); color:white; border:none; }
        .btn-danger { background: rgba(239, 68, 68, 0.1); color: var(--danger); }
        .btn-danger:hover { background: var(--danger); color:white; }
        .btn-ghost { background:rgba(255,255,255,0.05); color:var(--text-secondary); }
        .btn-download { background: linear-gradient(135deg, #059669, #10b981); color:white; border:none; }

        .hint { font-size: 12px; color: var(--text-secondary); text-align: center; }
        .timer { font-family: var(--font-heading); font-size: 32px; font-weight: 700; }
        .status-icon { width:48px; height:48px; border-radius:14px; display:flex; align-items:center; justify-content:center; font-size:20px; }
        .success-bg { background: rgba(34, 197, 94, 0.1); color: var(--success); }
        .error-bg { background: rgba(239, 68, 68, 0.1); color: var(--danger); }

        .widget-btn {
          position: fixed;
          bottom: 30px;
          right: 30px;
          width: 56px;
          height: 56px;
          border-radius: 50%;
          background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
          display: none;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          box-shadow: 0 4px 15px rgba(99, 102, 241, 0.4);
          z-index: 2147483647;
          animation: float 3s ease-in-out infinite;
        }
        .widget-dot { width: 12px; height: 12px; border-radius: 4px; background: white; }

        @keyframes rotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-10px); } }
      </style>
      <div class="header">
        <div class="logo">
          <div class="logo-dot"></div>
          <span class="logo-text">NOTECRAFT</span>
        </div>
        <div class="controls">
          <button id="nc-minimize" class="btn-icon" title="Minimize">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line></svg>
          </button>
        </div>
      </div>
      <div id="state-idle" class="state active">
        <p class="hint">Ready to capture insights.</p>
        <button id="btn-start" class="btn btn-primary">Start Recording</button>
      </div>
      <div id="state-recording" class="state">
        <div class="timer" id="timer">00:00:00</div>
        <button id="btn-stop" class="btn btn-danger">End Meeting</button>
      </div>
      <div id="state-processing" class="state">
        <p id="processing-text" class="status-text">Crafting Notes</p>
        <p class="hint">Analyzing audio...</p>
      </div>
      <div id="state-ready" class="state">
        <div class="status-icon success-bg">✓</div>
        <p class="status-text">Notes Ready!</p>
        <a id="btn-docx" class="btn btn-download" target="_blank">Download DOCX</a>
        <button id="btn-new" class="btn btn-ghost">Start New</button>
      </div>
      <div id="state-error" class="state">
        <div class="status-icon error-bg">✕</div>
        <button id="btn-retry" class="btn btn-primary">Try Again</button>
        <button id="btn-new-error" class="btn btn-ghost">Reset</button>
      </div>
    `;

    widget = document.createElement("div");
    widget.id = "notecraft-widget";
    widget.className = "widget-btn";
    widget.innerHTML = `<div class="widget-dot"></div>`;
    shadowRoot.appendChild(container);
    shadowRoot.appendChild(widget);

    // Event listeners
    shadowRoot.getElementById("nc-minimize").onclick = toggleMinimize;
    widget.onclick = toggleMinimize;
    shadowRoot.getElementById("btn-start").onclick = startRecording;
    shadowRoot.getElementById("btn-stop").onclick = stopRecording;
    shadowRoot.getElementById("btn-new").onclick = resetToIdle;
    shadowRoot.getElementById("btn-new-error").onclick = resetToIdle;
    shadowRoot.getElementById("btn-retry").onclick = finalizeSession;
  }

  function toggleMinimize() {
    isMinimized = !isMinimized;
    container.style.display = isMinimized ? "none" : "flex";
    widget.style.display = isMinimized ? "flex" : "none";
  }

  function showState(name) {
    const states = shadowRoot.querySelectorAll(".state");
    states.forEach(s => s.classList.remove("active"));
    shadowRoot.getElementById("state-" + name).classList.add("active");
  }

  // ── Recording Logic ──────────────────────────────────────────
  async function startRecording() {
    currentSession = crypto.randomUUID();
    chunkIndex = 0;
    speakerTimeline = [];
    isRecording = true;
    recordingStart = Date.now();

    try {
      // Step 1: Start mic capture via offscreen document (independent of Meet)
      console.log("🎤 Starting offscreen mic capture...");
      try {
        const micResult = await chrome.runtime.sendMessage({ action: "START_OFFSCREEN_MIC" });
        if (micResult?.ok) {
          console.log("🎤 Offscreen mic started successfully!");
        } else {
          console.warn("🎤 Offscreen mic failed to start:", micResult?.error);
        }
      } catch (micErr) {
        console.warn("🎤 Offscreen mic unavailable:", micErr);
      }

      // Step 2: Capture Tab Audio (friends' voices)
      const displayStream = await navigator.mediaDevices.getDisplayMedia({ 
        video: true, 
        audio: true,
        preferCurrentTab: true,
        selfBrowserSurface: "include" 
      });
      
      const tabAudioTrack = displayStream.getAudioTracks()[0];
      if (displayStream.getVideoTracks()[0]) displayStream.getVideoTracks()[0].stop();
      
      if (!tabAudioTrack) {
        isRecording = false;
        chrome.runtime.sendMessage({ action: "STOP_OFFSCREEN_MIC" }).catch(() => {});
        return alert("Please share tab audio! Select the Meet tab and check 'Share tab audio'.");
      }

      // Step 3: Record tab audio only (mic is recorded separately in offscreen)
      audioStream = new MediaStream([tabAudioTrack]);
      tabAudioTrack.onended = stopRecording;

      // Step 4: Begin recording chunks
      recordChunk();
      chunkInterval = setInterval(recordChunk, CHUNK_INTERVAL_MS);
      startTimer();
      showState("recording");
      console.log("🚀 Recording started — Session:", currentSession);
      console.log("📢 Tab audio: friends' voices | 🎤 Offscreen: your voice");

    } catch (err) {
      console.error("NoteCraft Error:", err);
      chrome.runtime.sendMessage({ action: "STOP_OFFSCREEN_MIC" }).catch(() => {});
      isRecording = false;
      stopTimer();
      showState("idle");
      alert("Could not start recording: " + (err.message || "Unknown error"));
    }
  }

  function recordChunk() {
    if (!audioStream || !isRecording) return;
    const currentIndex = chunkIndex++;
    const recorder = new MediaRecorder(audioStream, { mimeType: "audio/webm" });
    const chunks = [];
    recorder.ondataavailable = e => e.data.size > 0 && chunks.push(e.data);
    recorder.onstop = async () => {
      if (chunks.length > 0) {
        const tabBlob = new Blob(chunks, { type: "audio/webm" });
        await uploadChunk(tabBlob, currentIndex);
      }
    };
    recorder.start();
    setTimeout(() => recorder.state === "recording" && recorder.stop(), CHUNK_INTERVAL_MS);
    mediaRecorder = recorder;
  }

  async function uploadChunk(tabBlob, index) {
    let micData = null;
    try {
      const response = await chrome.runtime.sendMessage({ action: "GET_OFFSCREEN_MIC_CHUNK" });
      if (response?.ok && response.data) {
        const raw = response.data;
        micData = (raw instanceof Uint8Array) ? raw : new Uint8Array(Object.values(raw));
      }
    } catch (err) {
      console.warn(`🎤 Mic fetch failed:`, err);
    }

    // Convert tab blob to buffer to send to background
    const tabBuffer = await tabBlob.arrayBuffer();

    chrome.runtime.sendMessage({
      action: "UPLOAD_CHUNK_DATA",
      sessionId: currentSession,
      chunkIndex: index,
      timeline: JSON.stringify(speakerTimeline),
      participants: JSON.stringify(participants),
      tabAudio: Array.from(new Uint8Array(tabBuffer)),
      micAudio: micData ? Array.from(micData) : null
    });

    console.log(`📤 Chunk ${index} sent to background for upload`);
  }

  async function stopRecording() {
    isRecording = false;
    clearInterval(chunkInterval);
    stopTimer();

    // Stop tab audio
    if (mediaRecorder && mediaRecorder.state === "recording") {
      mediaRecorder.stop();
      await new Promise(r => setTimeout(r, 500));
    }
    if (audioStream) audioStream.getTracks().forEach(t => t.stop());

    // Stop offscreen mic
    chrome.runtime.sendMessage({ action: "STOP_OFFSCREEN_MIC" }).catch(() => {});

    showState("processing");
    await finalizeSession();
  }

  async function finalizeSession() {
    await fetch(`${BACKEND_URL}/finalize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: currentSession, participants, speaker_timeline: speakerTimeline })
    });
    startPolling();
  }

  function startPolling() {
    pollInterval = setInterval(async () => {
      try {
        const res = await fetch(`${BACKEND_URL}/status?session_id=${currentSession}`);
        const data = await res.json();
        if (data.status === "ready") {
          clearInterval(pollInterval);
          showState("ready");
          shadowRoot.getElementById("btn-docx").href = BACKEND_URL + data.docx_url;
        } else if (data.status === "failed") {
          clearInterval(pollInterval);
          showState("error");
        }
      } catch (err) {
        console.error("Poll error:", err);
      }
    }, POLL_INTERVAL);
  }

  function startTimer() {
    elapsedSeconds = 0;
    timerInterval = setInterval(() => {
      elapsedSeconds++;
      const h = String(Math.floor(elapsedSeconds / 3600)).padStart(2, "0");
      const m = String(Math.floor((elapsedSeconds % 3600) / 60)).padStart(2, "0");
      const s = String(elapsedSeconds % 60).padStart(2, "0");
      shadowRoot.getElementById("timer").textContent = `${h}:${m}:${s}`;
    }, 1000);
  }

  function stopTimer() { clearInterval(timerInterval); }

  function resetToIdle() {
    showState("idle");
    currentSession = null;
    elapsedSeconds = 0;
    shadowRoot.getElementById("timer").textContent = "00:00:00";
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.action === "TOGGLE_OVERLAY") {
      if (!shadowRoot) {
        injectUI();
      } else {
        toggleMinimize();
      }
    }
  });

  function initNoteCraft() {
    if (!shadowRoot) {
      injectUI();
      isMinimized = true;
      container.style.display = "none";
      widget.style.display = "flex";
    }
    startScraping();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initNoteCraft);
  } else {
    initNoteCraft();
  }
})();