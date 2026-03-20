// recorder.js — offscreen document
// getUserMedia + MediaRecorder + sends ArrayBuffer chunks to background

let mediaRecorder = null;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.target !== "offscreen") return;

  if (msg.action === "START") {
    startRecording(msg.streamId)
      .then(() => sendResponse({ success: true }))
      .catch((e) => sendResponse({ success: false, error: e.message }));
    return true;
  }

  if (msg.action === "STOP") {
    stopRecording();
    sendResponse({ success: true });
    return true;
  }
});

async function startRecording(streamId) {
  if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: streamId } },
    video: false,
  });

  mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });

  mediaRecorder.ondataavailable = async (e) => {
    if (!e.data || e.data.size === 0) return;
    console.log(`Offscreen chunk: ${e.data.size} bytes`);
    const buffer = await e.data.arrayBuffer();
    chrome.runtime.sendMessage({
      action:   "CHUNK_DATA",
      target:   "background",
      buffer:   buffer,
      mimeType: e.data.type || "audio/webm",
    }).catch(() => {});
  };

  mediaRecorder.onerror = (e) => console.error("MediaRecorder error:", e);
  mediaRecorder.start(25000); // 25s chunks
  console.log("Offscreen: recording started");
}

function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state === "inactive") return;
  mediaRecorder.onstop = () => {
    mediaRecorder.stream.getTracks().forEach((t) => t.stop());
    mediaRecorder = null;
    console.log("Offscreen: stopped");
  };
  mediaRecorder.stop();
}