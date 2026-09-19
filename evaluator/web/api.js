// Single boundary between the browser and the evaluator API.
//
// These routes are the read/chat contract present in the evaluator today. The
// upcoming API_CONTRACT.md should extend this module with jobs and global-call
// routes; views must not call fetch directly or infer a failed API from mocks.
window.LabApi = (() => {
  async function request(path, options = {}) {
    const response = await fetch(path, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `${response.status} ${response.statusText}`);
    return body;
  }

  const json = (method, body) => ({
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  return {
    getRuns: () => request("/api/runs"),
    getRun: (id) => request(`/api/runs/${encodeURIComponent(id)}`),
    getCases: (id) => request(`/api/runs/${encodeURIComponent(id)}/cases`),
    getRealCalls: (id) => request(`/api/runs/${encodeURIComponent(id)}/real-calls`),
    getComparison: (id) => request(`/api/runs/${encodeURIComponent(id)}/compare`),
    getDiff: (query) => request(`/api/diff?${query}`),
    getProfiles: () => request("/api/profiles"),
    openChat: (body) => request("/api/chat", json("POST", body)),
    say: (id, body) => request(`/api/chat/${encodeURIComponent(id)}/say`, json("POST", body)),
    sayAudio: (id, body) => request(`/api/chat/${encodeURIComponent(id)}/say-audio`, json("POST", body)),
    closeChat: (id) => request(`/api/chat/${encodeURIComponent(id)}/close`, { method: "POST" }),
  };
})();
