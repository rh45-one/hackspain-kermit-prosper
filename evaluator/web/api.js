// Single boundary between the browser and the evaluator API.
//
// Views use this boundary only: the browser never invents destinations, routes
// or mock evidence when a local API response is unavailable.
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
    getAnalytics: (query) => request(`/api/analytics?${query}`),
    getJudge: () => request("/api/judge"),
    judgeCall: (id) => request(`/api/history/calls/${encodeURIComponent(id)}/judge`, { method: "POST" }),
    getRun: (id) => request(`/api/runs/${encodeURIComponent(id)}`),
    getCases: (id) => request(`/api/runs/${encodeURIComponent(id)}/cases`),
    getRealCalls: (id) => request(`/api/runs/${encodeURIComponent(id)}/real-calls`),
    getComparison: (id) => request(`/api/runs/${encodeURIComponent(id)}/compare`),
    getDiff: (query) => request(`/api/diff?${query}`),
    getProfiles: () => request("/api/profiles"),
    importHistory: () => request("/api/history/import", json("POST", { source: "runs" })),
    getHistoryCalls: (query) => request(`/api/history/calls?${query}`),
    getHistoryCall: (id) => request(`/api/history/calls/${encodeURIComponent(id)}`),
    getHistorySummary: (query) => request(`/api/history/summary?${query}`),
    getScenarios: () => request("/api/scenarios"),
    getJobs: () => request("/api/jobs"),
    createJob: (body) => request("/api/jobs", json("POST", body)),
    cancelJob: (id) => request(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
    getComparisons: (query) => request(`/api/comparisons?${query}`),
    openChat: (body) => request("/api/chat", json("POST", body)),
    say: (id, body) => request(`/api/chat/${encodeURIComponent(id)}/say`, json("POST", body)),
    sayAudio: (id, body) => request(`/api/chat/${encodeURIComponent(id)}/say-audio`, json("POST", body)),
    closeChat: (id) => request(`/api/chat/${encodeURIComponent(id)}/close`, { method: "POST" }),
  };
})();
