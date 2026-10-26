// Polylane iss_161b76cb6001ua2mankzoc8d: the token background.js sends, kept in chrome.storage.local.
const field = document.getElementById("token");
const status = document.getElementById("status");

chrome.storage.local.get("token").then(({ token }) => {
  field.value = typeof token === "string" ? token : "";
});

document.getElementById("save").addEventListener("click", async () => {
  await chrome.storage.local.set({ token: field.value.trim() });
  status.textContent = "Saved.";
});
