// background.js — service worker
// Minimal — only relays speaker/participant updates from content.js

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

  // Relay speaker and participant updates from content.js to popup.js
  if (message.action === "SPEAKER_UPDATE" || message.action === "PARTICIPANTS_UPDATE") {
    chrome.runtime.sendMessage(message).catch(() => {});
  }

});