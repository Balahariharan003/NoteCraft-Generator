// content.js — NoteCraft Generator Content Script
// Injected into meeting pages to scrape data and manage recording.

(function () {
  if (window.notecraftInjected) return;
  window.notecraftInjected = true;

  const BACKEND_URL = 'http://localhost:8000';
  const CHUNK_INTERVAL_MS = 30000;
  const POLL_INTERVAL = 2000;

  let shadowRoot = null;
  let container = null;
  let isRecording = false;
  let currentSession = null;
  let chunkIndex = 0;
  let timerInterval = null;
  let chunkInterval = null;
  let elapsedSeconds = 0;
  let recordingStart = null;
  let mediaRecorder = null;
  let audioStream = null; // This will be the merged stream
  let micStream = null;
  let tabStream = null;
  let audioCtx = null;
  let speakerTimeline = [];
  let participants = [];
  let lastSpeaker = null;

  const PLATFORM = (() => {
    if (location.href.includes('meet.google.com')) return 'meet';
    if (location.href.includes('zoom.us')) return 'zoom';
    if (location.href.includes('teams.microsoft')) return 'teams';
    return 'unknown';
  })();

  const SELECTORS = {
    meet: {
      participants: '.zWGUib, .ZjG79c, .dwS77e',
      activeSpeaker: '.KF4T6b, [data-speaking="true"] .zWGUib',
    },
  };

  /**
   * Scrapes participants from the current meeting.
   */
  function scrapeParticipants() {
    const sel = SELECTORS[PLATFORM]?.participants;
    if (!sel) return [];
    return [...new Set(Array.from(document.querySelectorAll(sel)).map(el => el.textContent.trim()).filter(n => n.length > 0))];
  }

  /**
   * Monitors active speaker and participant list.
   */
  function startScraping() {
    const observer = new MutationObserver(() => {
      const sel = SELECTORS[PLATFORM]?.activeSpeaker;
      if (!sel) return;
      const el = document.querySelector(sel);
      const name = el?.textContent.trim();

      if (name && name !== lastSpeaker && isRecording) {
        lastSpeaker = name;
        const elapsed = Date.now() - recordingStart;
        speakerTimeline.push({ name, timestamp_ms: elapsed });
        console.log('🗣️ Speaker detected:', name);
      }
    });

    observer.observe(document.body, { childList: true, subtree: true, attributes: true });

    setInterval(() => {
      if (isRecording) participants = scrapeParticipants();
    }, 10000);
  }

  /**
   * Injects the NoteCraft UI overlay.
   */
  function injectUI() {
    if (document.getElementById('notecraft-root')) return;

    const host = document.createElement('div');
    host.id = 'notecraft-root';
    document.body.appendChild(host);
    shadowRoot = host.attachShadow({ mode: 'open' });

    container = document.createElement('div');
    container.id = 'nc-container';
    shadowRoot.appendChild(container); 
    updateUI('idle'); 
  }

  /**
   * Updates the UI state.
   */
  function updateUI(state, data = {}) {
    let content = '';
    const styles = `
      <style>
        #nc-panel {
          position: fixed;
          top: 20px;
          right: 20px;
          width: 300px;
          background: #111;
          color: #fff;
          padding: 20px;
          border-radius: 12px;
          font-family: sans-serif;
          z-index: 999999;
          box-shadow: 0 4px 20px rgba(0,0,0,0.5);
          border: 1px solid #333;
        }
        button {
          width: 100%;
          padding: 10px;
          margin-top: 10px;
          border-radius: 6px;
          border: none;
          cursor: pointer;
          font-weight: bold;
        }
        #btn-start { background: #4f46e5; color: white; }
        #btn-stop { background: #ef4444; color: white; }
        #btn-download { background: #10b981; color: white; }
        #timer { font-size: 24px; font-weight: bold; margin: 10px 0; text-align: center; }
        .status { color: #9ca3af; font-size: 14px; text-align: center; }
      </style>
    `;

    switch (state) {
      case 'idle':
        content = `
          <div id="nc-panel">
            <h3>NoteCraft</h3>
            <p class="status">Ready to capture notes.</p>
            <button id="btn-start">Start Recording</button>
          </div>
        `;
        break;
      case 'recording':
        content = `
          <div id="nc-panel">
            <h3>Recording...</h3>
            <div id="timer">00:00:00</div>
            <button id="btn-stop">Stop Meeting</button>
          </div>
        `;
        break;
      case 'processing':
        content = `
          <div id="nc-panel">
            <h3>Finalizing...</h3>
            <p class="status">Generating meeting notes...</p>
          </div>
        `;
        break;
      case 'ready':
        content = `
          <div id="nc-panel">
            <h3>Notes Ready!</h3>
            <button id="btn-download">Download DOCX</button>
            <button id="btn-reset" style="background:#333; color:white;">Start New</button>
          </div>
        `;
        break;
      case 'error':
        content = `
          <div id="nc-panel">
            <h3 style="color:#ef4444">Error</h3>
            <p class="status">${data.error || 'Something went wrong.'}</p>
            <button id="btn-reset">Retry</button>
          </div>
        `;
        break;
    }

    container.innerHTML = styles + content;

    // Re-attach listeners
    if (shadowRoot.getElementById('btn-start')) shadowRoot.getElementById('btn-start').onclick = startRecording;
    if (shadowRoot.getElementById('btn-stop')) shadowRoot.getElementById('btn-stop').onclick = stopRecording;
    if (shadowRoot.getElementById('btn-download')) {
      shadowRoot.getElementById('btn-download').onclick = () => {
        window.open(`${BACKEND_URL}/download/${currentSession}`);
      };
    }
    if (shadowRoot.getElementById('btn-reset')) {
      shadowRoot.getElementById('btn-reset').onclick = () => updateUI('idle');
    }
  }

  /**
   * Starts the recording process with merged audio.
   */
  async function startRecording() {
    currentSession = crypto.randomUUID();
    chunkIndex = 0;
    speakerTimeline = [];
    isRecording = true;
    recordingStart = Date.now();

    try {
      console.log('🎤 Initializing microphone...');
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true }
      });

      console.log('🖥️ Requesting tab audio...');
      tabStream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: { echoCancellation: true, noiseSuppression: true }
      });

      const tabAudioTrack = tabStream.getAudioTracks()[0];
      if (!tabAudioTrack) {
        throw new Error('Please share tab audio! Select this tab and check "Share tab audio".');
      }

      // Stop video track as we only need audio
      tabStream.getVideoTracks().forEach(t => t.stop());

      console.log('🔊 Merging audio streams...');
      audioCtx = new AudioContext();
      const destination = audioCtx.createMediaStreamDestination();

      const micSource = audioCtx.createMediaStreamSource(micStream);
      const tabSource = audioCtx.createMediaStreamSource(new MediaStream([tabAudioTrack]));

      // Connect both to destination
      micSource.connect(destination);
      tabSource.connect(destination);

      audioStream = destination.stream;
      tabAudioTrack.onended = () => stopRecording();

      updateUI('recording');
      startTimer();

      // Start capturing chunks
      setTimeout(recordChunk, 1000);
      chunkInterval = setInterval(recordChunk, CHUNK_INTERVAL_MS);

      console.log('🚀 Recording started (Merged Tab + Mic).');

    } catch (err) {
      console.error('❌ Start failed:', err);
      isRecording = false;
      
      let errorMsg = err.message;
      if (errorMsg.includes('context invalidated')) {
        errorMsg = 'Extension updated. Please refresh this page to continue.';
      }
      
      updateUI('error', { error: errorMsg });
      cleanupStreams();
    }
  }

  /**
   * Records a single chunk of the merged stream.
   */
  function recordChunk() {
    if (!audioStream || !isRecording) return;

    const index = chunkIndex++;
    const recorder = new MediaRecorder(audioStream, { mimeType: 'audio/webm' });
    const chunks = [];

    recorder.ondataavailable = e => e.data.size > 0 && chunks.push(e.data);
    recorder.onstop = async () => {
      if (chunks.length > 0) {
        const blob = new Blob(chunks, { type: 'audio/webm' });
        uploadChunk(blob, index);
      }
    };

    recorder.start();
    setTimeout(() => {
      if (recorder.state === 'recording') recorder.stop();
    }, CHUNK_INTERVAL_MS - 100); 
    mediaRecorder = recorder;
  }

  /**
   * Uploads the merged chunk to the background script.
   */
  async function uploadChunk(blob, index) {
    const buffer = await blob.arrayBuffer();

    chrome.runtime.sendMessage({
      action: 'UPLOAD_CHUNK_DATA',
      sessionId: currentSession,
      chunkIndex: index,
      timeline: JSON.stringify(speakerTimeline),
      participants: JSON.stringify(participants),
      audio: new Uint8Array(buffer) // Combined stream
    });

    console.log(`📤 Chunk ${index} (merged) sent for upload.`);
  }

  /**
   * Stops recording and finalizes the session.
   */
  async function stopRecording() {
    if (!isRecording) return;
    isRecording = false;

    clearInterval(chunkInterval);
    stopTimer();
    updateUI('processing');

    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop();
    }
    
    cleanupStreams();

    console.log('🛑 Recording stopped. Finalizing...');

    try {
      const response = await fetch(`${BACKEND_URL}/finalize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: currentSession,
          participants: participants,
          speaker_timeline: speakerTimeline
        })
      });

      if (response.ok) {
        console.log('✅ Finalize successful.');
        startPolling();
      } else {
        throw new Error('Finalize failed on server.');
      }
    } catch (err) {
      console.error('❌ Finalize failed:', err);
      updateUI('error', { error: 'Failed to finalize meeting notes.' });
    }
  }

  function cleanupStreams() {
    if (micStream) micStream.getTracks().forEach(t => t.stop());
    if (tabStream) tabStream.getTracks().forEach(t => t.stop());
    if (audioCtx) audioCtx.close();
    micStream = null;
    tabStream = null;
    audioCtx = null;
  }

  /**
   * Polls the backend for processing status.
   */
  function startPolling() {
    const pollId = setInterval(async () => {
      try {
        const res = await fetch(`${BACKEND_URL}/status?session_id=${currentSession}`);
        const data = await res.json();

        if (data.status === 'ready') {
          clearInterval(pollId);
          updateUI('ready');
        } else if (data.status === 'failed') {
          clearInterval(pollId);
          updateUI('error', { error: 'Processing failed.' });
        }
      } catch (err) {
        console.warn('⚠️ Poll failed:', err);
      }
    }, POLL_INTERVAL);
  }

  /**
   * Timer management.
   */
  function startTimer() {
    elapsedSeconds = 0;
    timerInterval = setInterval(() => {
      elapsedSeconds++;
      const h = String(Math.floor(elapsedSeconds / 3600)).padStart(2, '0');
      const m = String(Math.floor((elapsedSeconds % 3600) / 60)).padStart(2, '0');
      const s = String(elapsedSeconds % 60).padStart(2, '0');
      const timerEl = shadowRoot.getElementById('timer');
      if (timerEl) timerEl.textContent = `${h}:${m}:${s}`;
    }, 1000);
  }

  function stopTimer() {
    clearInterval(timerInterval);
  }

  /**
   * Safe message sending with retry logic.
   */
  async function sendMessageSafe(message, retries = 3) {
    for (let i = 0; i < retries; i++) {
      try {
        return await chrome.runtime.sendMessage(message);
      } catch (err) {
        if (i === retries - 1) throw err;
        await new Promise(r => setTimeout(r, 200 * (i + 1)));
      }
    }
  }

  // Handle messages from the background script
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.action === 'TOGGLE_OVERLAY') {
      const panel = shadowRoot.getElementById('nc-panel');
      if (panel) panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    }
  });

  // Initialization
  function init() {
    injectUI();
    startScraping();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();