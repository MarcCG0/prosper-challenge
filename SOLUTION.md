# Solution Overview

## Summary
This implementation delivers a real-time voice agent that schedules Healthie appointments using Pipecat function calling. The codebase follows a ports-and-adapters approach so the EHR integration can be swapped without touching the agent logic. The bot asks for identity (name + DOB), then schedules appointments (and optionally lists/cancels), with explicit confirmation before any write action.

## Architecture
- **Domain** (`prosper/domain`): Immutable `Patient` / `Appointment` models and EHR-specific exceptions.
- **Ports** (`prosper/ehr/ports.py`): Defines the `EHRService` and `EHRClientProtocol` interfaces.
- **Adapters** (`prosper/ehr/adapters`):
  - GraphQL adapter for Healthie API
  - Playwright adapter for UI automation
- **Service** (`prosper/ehr/service.py`): Business logic (duplicate checks, error wrapping).
- **Agent** (`prosper/agent`): Prompts, tool schemas, and function handlers.
- **Factory** (`prosper/ehr/factory.py`): Adapter selection (`graphql`, `playwright`, or `auto`).

## Key Decisions & Trade-offs
- **LLM-driven state**: Conversation flow is driven by a system prompt and tool schemas rather than a hardcoded state machine. This keeps logic flexible, but makes testing more important (see improvements).
- **Timezone normalization**: All appointment times are treated as clinic-local. The GraphQL adapter converts incoming timestamps to the clinic timezone, and creation sends an explicit offset to Healthie. This avoids subtle duplicate-detection and display bugs.
- **Adapter flexibility**: The default adapter is GraphQL for speed and reliability. A Playwright adapter remains as a fallback for environments where GraphQL is unavailable or blocked.
- **Auth resilience**: GraphQL requests retry once on authentication failures by clearing the token and reauthenticating.
- **README vs. code location**: The README references a `healthie.py` entrypoint. I intentionally kept the logic in `prosper/ehr` to preserve the layered architecture and avoid adding an unused shim; the same functions are exposed via the tool handlers and service layer.

## Testing
- Unit tests cover service logic and tool handlers.
- Integration tests validate GraphQL operations against a real Healthie account (opt-in via env vars).

## Future Improvements
- **Reliability**: Add a circuit breaker and retry/backoff for EHR calls; surface a friendly “system unavailable” message when open.
- **Latency**: Cache appointment types and use prefetching for patient lookup; parallelize tool execution where possible.
- **Evaluation**: Add golden transcript tests that assert tool usage and conversation flow.
- **Security**: Explicitly redact PII in logs and add structured audit logging around appointment creation/cancellation.
