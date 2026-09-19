# FrontDesk

Next.js App Router dashboard for the integrated Prosper agent.

```sh
npm install
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000. Start `agent.serve` on port 7860 first, as
described in [the integration runbook](../integration/README.md).

- `AGENT_HTTP_BASE_URL`: server-side backend URL, default `http://127.0.0.1:7860`.
- `FRONTDESK_DEMO=true`: opt into the original simulated data and local settings.
  Without this flag the dashboard uses only backend data, including in production.

The Next.js `/api/frontdesk/{calls,clinic}` handlers proxy read-only resources.
Provider keys remain in the backend. Calls refresh every three seconds, clinic
data every minute. Failures are displayed without replacing real data with mocks.
The calendar shows the clinic EHR; submissions do not mutate that EHR.

Prompt editing, knowledge uploads and manual takeover do not have backend write
APIs. The live UI disables them. Demo mode keeps the local mock interactions.

```sh
npm run lint
npm run typecheck
npm run build
npm run start
```

`typecheck` generates Next.js route types before invoking TypeScript. The demo
flag is read at request time, so changing it requires restarting the process but
does not require rebuilding.
