// Talk Dat! Companion: talks to the local control API (Settings > Core >
// "Enable local control API"). Optionally append ?token=... if you set one.
const BASE = "http://127.0.0.1:4670";

async function api(route) {
  const response = await fetch(`${BASE}${route}`, { method: "POST" });
  if (!response.ok) throw new Error(`Talk Dat! API ${route} -> ${response.status}`);
  return response.json();
}

async function insertLastTranscript(tab) {
  const response = await fetch(`${BASE}/last-text`);
  const { text } = await response.json();
  if (!text) return;
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    args: [text],
    func: (value) => {
      const el = document.activeElement;
      if (!el) return;
      if (el.isContentEditable) {
        document.execCommand("insertText", false, value);
      } else if ("value" in el) {
        const start = el.selectionStart ?? el.value.length;
        const end = el.selectionEnd ?? el.value.length;
        el.value = el.value.slice(0, start) + value + el.value.slice(end);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.selectionStart = el.selectionEnd = start + value.length;
      }
    },
  });
}

chrome.commands.onCommand.addListener(async (command, tab) => {
  try {
    if (command === "insert-last-transcript" && tab?.id) await insertLastTranscript(tab);
    if (command === "toggle-dictation") await api("/toggle");
  } catch (error) {
    console.warn("Talk Dat! companion:", error.message);
  }
});

chrome.action.onClicked.addListener(async (tab) => {
  try {
    if (tab?.id) await insertLastTranscript(tab);
  } catch (error) {
    console.warn("Talk Dat! companion:", error.message);
  }
});
