# Solution

## What I built

The README asked for four things: a conversation flow that collects patient identity, a `find_patient` implementation, a `create_appointment` implementation, and wiring it all together with the voice agent. I ended up going a bit further -- I also added appointment cancellation and a few things around reliability and UX that I think matter for a voice interface.

The bot greets the patient, asks for their name and date of birth, looks them up in Healthie, and then either schedules or cancels an appointment based on what they need. Everything goes through three function-calling tools: `find_patient`, `create_appointment`, and `cancel_appointment`.

## How I structured the code

I noticed the starter repo had Playwright already set up for browser automation, but I thought talking to Healthie's GraphQL API directly would be way faster and more reliable. Instead of picking one and throwing the other away, I went with a ports-and-adapters approach so both could coexist behind the same interface.

```
bot.py                          Entry point
prosper/
  agent/
    shared/
      fillers.py                Filler phrases for slow tool calls
      validation.py             Date/time parsing helpers
    v1/
      prompts.py                System prompt
      tools.py                  Tool schemas + handlers
  ehr/
    ports.py                    Interfaces (AbstractEHRService, EHRClientProtocol)
    service.py                  Business logic on top of the raw client
    factory.py                  Picks which adapter to use
    adapters/
      graphql.py                Healthie GraphQL API
      playwright.py             Healthie browser automation
      fake.py                   In-memory double for tests
  domain/
    models.py                   Patient, Appointment, AppointmentRequest
    exceptions.py               EHRError hierarchy
  config.py                     Pydantic Settings
```

The idea is simple: `domain/` has no idea Healthie exists, `service.py` only talks to the `EHRClientProtocol` interface, and the concrete adapters (`graphql.py`, `playwright.py`, `fake.py`) are the only things that know how to actually reach Healthie. This also means I can test all the business logic with `FakeEHRClient` and never touch the network.

I also intentionally didn't follow the README's suggestion of putting everything in a single `healthie.py` file. It would have been simpler, but it would have mixed concerns that I wanted to keep separate -- the service logic (DOB filtering, error normalization) shouldn't live next to HTTP calls or Playwright selectors. The same functions are still accessible through the tool handlers and service layer, just better organized.

### How the pipeline fits together

`bot.py` builds a Pipecat pipeline: ElevenLabs STT captures speech, feeds it to the OpenAI LLM, and the LLM's output goes through the filler processor and then ElevenLabs TTS back to the caller. The three tools (`find_patient`, `create_appointment`, `cancel_appointment`) are registered on the LLM via OpenAI's function-calling API with JSON schemas that describe each tool's parameters. When the model decides to call a tool, Pipecat intercepts the function call, runs the corresponding handler in `tools.py` (which delegates to `EHRService`), and feeds the structured result back into the LLM context so it can formulate a natural-language response. The caller never knows a tool call happened -- they just hear the bot pause briefly and then respond with the result.

## Decisions and why I made them

### Conversation flow: prompt-driven, not a state machine

The README asked to "modify the agent's behavior to ask for patient name and date of birth, then appointment date and time." I had two options here: build a state machine that forces a specific sequence of steps, or encode the flow in the system prompt and let the LLM handle transitions.

I went with the prompt approach. The system prompt defines a clear step-by-step flow (greet, identify, find patient, ask what they need, schedule/cancel with confirmation, end) and the tool schemas constrain what the model can actually do. It can only call three tools, and each requires specific validated inputs.

The downside is that the LLM could theoretically skip steps or call tools in the wrong order -- a state machine would prevent that by construction. But in practice, I found the prompt-based approach handles edge cases much better (patient changes their mind, gives partial info, asks a clarifying question mid-flow). And I added input validation in every tool handler as a safety net: even if the LLM tries to create an appointment with a bad date or without a patient ID, the handler rejects it with a clear error message instead of letting garbage through to Healthie.

### GraphQL as primary, Playwright as fallback

The starter code pointed me toward Playwright, but once I found Healthie's GraphQL API, it was a clear win for the default path. A GraphQL call takes ~200-400ms; Playwright needs to launch a browser, navigate pages, fill forms, and wait for UI animations -- we're talking seconds. For a voice agent where every millisecond of silence feels like an eternity, that difference matters a lot.

That said, I kept the Playwright adapter. It was already partly scaffolded, and there's a real scenario where API access might not be available or the API doesn't expose some functionality the UI does. Both adapters implement the same `EHRClientProtocol`, so swapping is just changing the `HEALTHIE_ADAPTER` env var. The factory in `factory.py` handles the rest.

Yes, maintaining two adapters is more work. But I think having a browser-automation fallback for an EHR integration is worth it -- these systems change, and having two paths to the same data is a decent safety net.

### DOB filtering happens in the service layer

Healthie's API lets you search patients by keyword but doesn't filter by date of birth server-side. I didn't want to leave that to the LLM ("here are 5 Marc's, which one has this birthday?"), so `EHRService.find_patient` does client-side DOB filtering after the search comes back. The adapter just does the keyword search, the service applies the stricter match.

This keeps things deterministic: one match is unambiguous, multiple matches get reported back so the agent can ask the patient to clarify, and zero matches get a clear "not found."

### Filler phrases to cover tool call latency

This was something I added after testing the bot and noticing how awkward silence feels during a tool call. Even a 2-second pause on a phone call makes you wonder if you got disconnected.

I wrote a `ToolCallFillerProcessor` that sits in the pipeline between the LLM and TTS. When a tool call starts, it schedules a filler phrase after 1.5 seconds. If the tool finishes before that (which it usually does with GraphQL), the filler gets cancelled and the patient never hears it. If the tool is slow (Playwright, or a network hiccup), the patient hears something like "One moment, let me look up your record" instead of dead silence.

Each tool has its own contextual phrase, and the delay is configurable. It's a small thing but it makes the experience feel much more natural.

### Timezone handling

I treated all appointment times as clinic-local (`America/New_York` by default, configurable). The GraphQL adapter sends explicit timezone offsets when creating appointments and converts UTC timestamps back to clinic-local when reading them. The Playwright adapter formats dates and times the way Healthie's UI expects (US long format for dates, 12-hour for times). The tool handlers also check the clinic's local time to reject appointments in the past.

I've been bitten by timezone bugs before, so I wanted to be explicit about it everywhere rather than hoping UTC conversions work out.

### Error handling

I built a small exception hierarchy (`EHRError` -> `EHRUnavailableError`, `AppointmentCreationError`, `AppointmentCancellationError`) so that errors carry context (which patient, what went wrong) rather than just a generic message.

The pattern across the codebase is: the service layer catches unexpected exceptions and wraps them into the right domain exception (preserving the original for debugging), while known errors pass through as-is. The tool handlers then catch everything and always return a structured dict to the LLM. The model never sees a stack trace -- it gets a message it can relay to the patient in natural language. No matter what breaks, the patient hears a coherent response.

### Auth retry in the GraphQL adapter

The bot is a long-running process, so the Healthie session token will eventually expire. I added lazy authentication (first request triggers `signIn`, token gets cached) with a one-shot retry: if a request gets a 401/403 or a GraphQL-level auth error, the adapter clears the token, re-authenticates, and replays the request. A flag prevents infinite loops. Simple, but it covers the most common failure mode.

### Configuration

I used Pydantic Settings for all config (`prosper/config.py`). It validates types at startup, supports nested configs with env prefixes, and has a nice trick with `AliasChoices` on the LLM config -- the same code reads from either `OPENAI_API_KEY` or `OPENROUTER_API_KEY`, so switching LLM providers is just changing an env var.

## Testing

### Unit tests

These run on every push/PR in CI (`pytest -m unit`). No credentials, no network. They cover:

- **Service logic** (`test_service.py`): DOB filtering, error wrapping, delegation to the client.
- **Tool handlers** (`test_tools.py`): Input validation, success and error paths for all three tools.
- **Filler processor** (`test_fillers.py`): Timing behavior -- does the filler fire when the tool is slow? Does it get cancelled when the tool is fast?
- **GraphQL client** (`test_graphql.py`): Response parsing, error handling, the auth flow, appointment type caching. These use `pytest-httpx` to mock HTTP and actually check the request payloads (e.g., the timezone format on the datetime variable).
- **Helpers** (`test_datetime_helpers.py`, `test_parsing_helpers.py`): Edge cases for date/time formatting and regex parsing.

One thing I'm happy with: the `FakeEHRClient` lives in production code (`prosper/ehr/adapters/fake.py`), not under `tests/`. It conforms to the same `EHRClientProtocol` as the real adapters, so if I ever change the interface, the fake breaks and the tests catch it.

### Integration tests

These run against a real Healthie instance -- they create an appointment and immediately cancel it. They're gated behind `@pytest.mark.integration` and skip when credentials aren't set.

To run them you need:
1. `HEALTHIE_EMAIL` and `HEALTHIE_PASSWORD` in `.env` or as env vars.
2. A patient named **"Test"** in the Healthie account (the tests search for this name).

```bash
uv run pytest -m integration
```

## CI/CD

Two GitHub Actions workflows:
- **Lint** (`lint.yml`): Ruff for import sorting and formatting via pre-commit.
- **Test** (`test.yml`): Runs unit tests only -- no credentials needed in CI.

There's also a Dockerfile and docker-compose.yaml for local deployment (`docker compose up`, bot on port 7860).

## Where I'd go next

These are things I'd want to tackle if this were heading to production.

### On latency

The filler processor already helps with perceived latency, but there's more to do. After `find_patient` succeeds, I could prefetch appointment types in the background so `create_appointment` doesn't need an extra round trip on first call -- that's ~200ms I could shave off. I'd also look into whether Pipecat's streaming capabilities could let the LLM start talking before the full tool result is ready (e.g., "I found your record..." while the result is still being assembled).

### On reliability

Right now, if Healthie goes down, each tool call fails independently. I'd add a circuit breaker so the bot detects this early and switches to a scripted fallback ("Our scheduling system is temporarily unavailable, please call us at...") instead of failing on every interaction. The factory could also try GraphQL first and automatically fall back to Playwright if the health check fails, though that would need the browser to be pre-warmed to avoid cold-start delays.

The auth retry only handles token expiration, not transient network errors. A retry with exponential backoff on the `_graphql` method would cover most of those without adding much complexity.

### On evaluation

Unit tests verify the pieces work in isolation, but they can't tell me if the bot has a good conversation. I'd want golden-transcript tests -- recorded conversations that assert the right tools get called in the right order with the right arguments. That would catch prompt regressions.

Going further, an LLM-as-judge approach could score conversations on correctness (did it book the right appointment?), safety (did it ever book without explicit confirmation?), and tone. And latency instrumentation with a dashboard (p50/p95/p99 per tool call) would help spot performance regressions early.

### On security

For a healthcare product, there are a few things I'd need before going live: PII redaction in logs (right now patient names and DOBs show up at INFO level), a structured audit trail for every appointment operation (HIPAA), and proper secret management (vault instead of `.env`).

### On conversation control: Pipecat Flows

The current bot encodes the entire conversation flow in a single system prompt. It works well in practice -- the tool schemas constrain what the model can do, and every handler validates its inputs. But there are no structural guarantees: the LLM could theoretically skip the patient-lookup step and jump straight to booking, or call `cancel_appointment` before identifying the patient.

I didn't have enough time to dive deep into Pipecat's more advanced features, and I preferred to keep a straightforward but robust implementation rather than overcomplicate things. That said, Pipecat has a **Pipecat Flows** module (`pipecat-flows`) that looks like a natural upgrade path for this kind of problem. It replaces the monolithic prompt with a node-based conversation graph where each node has its own task message, its own set of available functions, and explicit transitions to the next node. The LLM still has full conversational freedom *within* each node (handling clarifications, small talk, partial answers), but it can only call the functions that exist in the current node -- you literally can't book an appointment from the greeting node.

A few things that would make it worth the investment:

- **Structural safety**: Each node only exposes the functions relevant to that phase. No amount of prompt engineering can make the model call a tool that isn't registered in the current node.
- **Context resets**: Pipecat Flows supports `RESET_WITH_SUMMARY` between phases, which would help with context rot in longer conversations -- after patient lookup, summarize and start fresh for scheduling.
- **Interruption protection**: Write operations like `create_appointment` could be marked as non-cancellable, so user interruptions don't leave half-completed bookings.
- **Global functions**: Things like warm transfer ("I'd like to speak with a person") could be registered once and available in every node, without repeating them in each prompt section.

The EHR layer, domain models, and tool handler logic wouldn't need to change -- it's mostly a matter of splitting the system prompt into per-node task messages and wiring up the transitions. Something I'd definitely explore for the next iteration.

### On observability

For production, I'd add OpenTelemetry tracing. Each EHR call and tool invocation would produce a span, giving full visibility into conversation flow timing and error rates. Pipecat already has OpenTelemetry integration points -- it's mainly a matter of wiring them up.
