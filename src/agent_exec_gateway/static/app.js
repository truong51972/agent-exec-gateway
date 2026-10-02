async function aegRequest(url, options = {}) {
  const response = await fetch(url, {
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

function formObject(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function showResult(elementId, value) {
  const node = document.getElementById(elementId);
  if (!node) return;
  node.hidden = false;
  node.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}
