// Talk DAT! Companion: talks to the local control API (Settings > "Enable local control API for automations").
// Polylane iss_161b76cb6001ua2mankzoc8d: every request carries the token saved in the Companion's options as a
// Bearer header, because /last-text never answers without one (403 when Talk DAT! has no remote.token, 401 when
// the token is missing or wrong). A refused request now shows a "!" badge and the reason on the toolbar button
// instead of failing silently; the next request that works clears both.
const BASE = "http://127.0.0.1:4670";

const PROBLEMS = {
  unreachable: "Talk DAT! did not answer. Turn on the local control API in Talk DAT!'s Settings and keep Talk DAT! open.",
  token: "Talk DAT! did not accept the token. Paste the token from its config into the Companion's options.",
  noToken: "Talk DAT! has no token yet, so it will not share your last dictation. Add one to its config, then paste the same token into the Companion's options.",
  other: "Talk DAT! refused the request. Check the local control API in its Settings.",
};

class Refused extends Error {
  constructor(kind) {
    super(kind);
    this.kind = kind;
  }
}

async function savedToken() {
  try {
    const { token } = await chrome.storage.local.get("token");
    return typeof token === "string" ? token.trim() : "";
  } catch {
    return "";
  }
}

async function api(route, method = "POST") {
  const token = await savedToken();
  let response;
  try {
    response = await fetch(`${BASE}${route}`, { method, headers: token ? { Authorization: `Bearer ${token}` } : {} });
  } catch {
    throw new Refused("unreachable");
  }
  if (response.status === 401) throw new Refused("token");
  if (response.status === 403 && route === "/last-text") throw new Refused("noToken");
  if (!response.ok) throw new Refused("other");
  return response.json();
}

async function show(problem) {
  await chrome.action.setBadgeText({ text: problem ? "!" : "" });
  if (problem) await chrome.action.setBadgeBackgroundColor({ color: "#B3261E" });
  await chrome.action.setTitle({ title: problem ? PROBLEMS[problem] || PROBLEMS.other : defaultTitle() });
}

function defaultTitle() {
  try {
    return chrome.runtime.getManifest().action.default_title;
  } catch {
    return "Talk DAT! Companion";
  }
}

async function insertLastTranscript(tab) {
  const { text } = await api("/last-text", "GET");
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

async function attempt(work) {
  try {
    await work();
    await show(null);
  } catch (error) {
    console.warn("Talk DAT! Companion:", error.message);
    await show(error instanceof Refused ? error.kind : "other");
  }
}

chrome.commands.onCommand.addListener(async (command, tab) => {
  if (command === "insert-last-transcript" && tab?.id) await attempt(() => insertLastTranscript(tab));
  if (command === "toggle-dictation") await attempt(() => api("/toggle"));
});

chrome.action.onClicked.addListener(async (tab) => {
  if (tab?.id) await attempt(() => insertLastTranscript(tab));
});
