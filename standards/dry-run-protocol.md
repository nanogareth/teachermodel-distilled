# Dry-run protocol (W3)

Status: draft, framework 0.2.0.

1. Preflight the learner environment: accounts, sandbox API keys and their rate limits, data,
   network, model version pinned for the session.
2. Walk the run sheet against the clock.
3. Inject at least one failure from the module's failure catalogue (environment, API error,
   rate limit, unexpected model output) and handle it live.
4. Exercise the fallback path (recorded demo or pre-computed outputs).
5. A clearer signs off or lists fixes.

Validity: until the module's environment, model version or run sheet changes materially.
