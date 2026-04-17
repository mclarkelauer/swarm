# Inter-Agent Messaging

A run-scoped message bus that lets agents talk to each other within a
single plan execution. Messages are persisted in SQLite and survive
restarts of the orchestrator, but are scoped to a `run_id` by default so
parallel runs don't cross-pollinate.

Use it when one agent needs to ask another a question, broadcast a
finding, or negotiate over multiple turns. Skip it for one-shot data
hand-offs — those belong in artifacts or the shared context.

## 5-minute tour

Three operations cover most cases: send, receive, reply.

```python
# Agent A sends a message to Agent B in the current run
agent_send_message(
    from_agent="researcher",
    to_agent="implementer",
    content="Spec is ready at spec.md. Anything missing?",
    step_id="spec-review",
    run_id="run-2026-04-17-001",
    message_type="request",
)

# Agent B pulls inbox
agent_receive_messages(agent_name="implementer", run_id="run-2026-04-17-001")

# Agent B replies (correlation ID set automatically)
agent_reply_message(
    original_message_id="<uuid>",
    from_agent="implementer",
    content="Need the error-budget section filled in.",
    run_id="run-2026-04-17-001",
)

# Agent A acknowledges receipt
agent_acknowledge_message(message_id="<uuid>")
```

That's the loop. Broadcasts use `agent_broadcast`; threads use
`agent_get_thread`.

## Concepts

### Run-scoped delivery

Every message carries a `run_id`. `agent_receive_messages` filters on
`(to_agent = ? OR to_agent = '*') AND run_id = ?`, so cross-run leakage
is impossible by default.

If you need cross-run messaging, query the SQLite directly or pass a
shared `run_id` deliberately.

### Message types

The MCP wrapper accepts seven values, validated server-side:

| Type | Use for |
|------|---------|
| `request` | A message expecting a response |
| `response` | Default; a normal reply or asynchronous note |
| `broadcast` | Sent to all agents (`to_agent='*'`) |
| `proposal` | Negotiation — opening offer |
| `counter` | Negotiation — counter-offer |
| `accept` | Negotiation — agreement |
| `reject` | Negotiation — rejection |

Note the underlying schema CHECK constraint accepts only the first three
(`request`, `response`, `broadcast`) — the negotiation values are
validated by the MCP layer in
[`src/swarm/mcp/message_tools.py`](../src/swarm/mcp/message_tools.py)
but stored as one of the three base types via the API call. See
[Gotchas](#gotchas) below.

### Correlation IDs

Replies set `in_reply_to` to the original message's `id`. This is what
makes thread reconstruction work. `agent_reply_message` does this for
you; if you build a reply manually with `agent_send_message` you have to
populate `in_reply_to` yourself (currently no field on that tool — use
`agent_reply_message`).

### Negotiation threads

`agent_get_thread(initial_message_id)` walks the `in_reply_to` chain to
collect the full conversation in chronological order. It descends two
levels (replies and replies-to-replies) — sufficient for typical
negotiations but bounded.

```
proposal  -- from researcher      "Use bcrypt"
  counter -- from security        "Argon2 is stronger"
    accept -- from researcher     "Switching to Argon2"
```

### Message routing via `message_to`

Plan steps can declare a `message_to` field; when the step finishes, the
executor automatically posts the step output as a message addressed to
that agent. See [`src/swarm/plan/models.py`](../src/swarm/plan/models.py)
for the field and `docs/writing-plans.md` for how to use it in a plan.

### Acknowledgment

`agent_acknowledge_message` sets `read_at` to the current timestamp.
Useful for tracking whether a recipient has actually pulled the message
out of the inbox vs. it just sitting there.

## Payload shape

All MCP tools return JSON. The `AgentMessage` shape (sparsely
serialized — defaults are omitted):

```json
{
  "id": "9c8d1f2a-e123-4567-89ab-cdef01234567",
  "from_agent": "researcher",
  "to_agent": "implementer",
  "step_id": "spec-review",
  "run_id": "run-2026-04-17-001",
  "content": "Spec is ready at spec.md. Anything missing?",
  "message_type": "request",
  "created_at": "2026-04-17T15:00:00+00:00",
  "in_reply_to": "",
  "read_at": ""
}
```

Schema in
[`src/swarm/messaging/db.py`](../src/swarm/messaging/db.py); model in
[`src/swarm/messaging/models.py`](../src/swarm/messaging/models.py).

## MCP tool reference

Source:
[`src/swarm/mcp/message_tools.py`](../src/swarm/mcp/message_tools.py).

### `agent_send_message`

```
agent_send_message(from_agent, to_agent, content,
                   step_id="", run_id="", message_type="response")
```

Persists a message. Use `to_agent="*"` to broadcast (or use
`agent_broadcast` for clarity).

Call:

```json
{
  "from_agent": "researcher",
  "to_agent": "implementer",
  "content": "Spec ready",
  "run_id": "run-001",
  "message_type": "request"
}
```

Response:

```json
{
  "ok": true,
  "message": {"id": "...", "from_agent": "researcher", ...}
}
```

Validation errors come back as `{"error": "..."}`.

### `agent_receive_messages`

```
agent_receive_messages(agent_name, run_id, since="", limit="50")
```

Returns messages addressed to `agent_name` *and* broadcasts (`to_agent='*'`)
within the run. Newest first.

Call:

```json
{
  "agent_name": "implementer",
  "run_id": "run-001",
  "since": "2026-04-17T15:00:00+00:00"
}
```

Response: JSON array of message objects.

### `agent_broadcast`

```
agent_broadcast(from_agent, content, step_id="", run_id="")
```

Shorthand for `agent_send_message(..., to_agent="*", message_type="broadcast")`.

Call:

```json
{
  "from_agent": "incident-responder",
  "content": "Switching to read-only mode for db migration",
  "run_id": "run-001"
}
```

Response: `{"ok": true, "message": {...}}`.

### `agent_reply_message`

```
agent_reply_message(original_message_id, from_agent, content, run_id="")
```

Looks up the original message, sends a reply with `to_agent` set to the
original sender, `in_reply_to` set to the original ID, and
`message_type="response"`.

Call:

```json
{
  "original_message_id": "9c8d1f2a-...",
  "from_agent": "implementer",
  "content": "Need the error-budget section",
  "run_id": "run-001"
}
```

Response: the new message object.

### `agent_acknowledge_message`

```
agent_acknowledge_message(message_id)
```

Sets `read_at` if it was empty. No-op if already acked.

Call: `{"message_id": "9c8d1f2a-..."}`

Response: `{"ok": true|false, "message_id": "..."}`.

### `agent_get_thread`

```
agent_get_thread(message_id)
```

Walks the `in_reply_to` chain from the given message and returns all
messages in the thread, chronologically ordered.

Call: `{"message_id": "9c8d1f2a-..."}`

Response: JSON array of messages.

## CLI reference

There is currently **no `swarm message` CLI subcommand**. Messaging is
accessed through MCP tools from inside an orchestrator session. For
ad-hoc inspection:

```bash
sqlite3 ./messages.db "SELECT from_agent, to_agent, content FROM messages WHERE run_id = 'run-001' ORDER BY created_at;"
```

The database file lives in the plans directory (defaults to `cwd/messages.db`)
— see `_get_message_api` in
[`src/swarm/mcp/message_tools.py`](../src/swarm/mcp/message_tools.py).

## Gotchas

- **Schema vs. wrapper validation.** The SQLite CHECK constraint only
  permits `request`, `response`, `broadcast`. The MCP wrapper accepts
  the four negotiation types (`proposal`, `counter`, `accept`, `reject`)
  — stored under one of the base types or via API path that bypasses
  the CHECK. If you script around the API, expect surprises with the
  extra types.
- **`in_reply_to` is a one-step pointer.** `agent_get_thread` follows
  it two levels. Deeply nested threads (reply-to-reply-to-reply) are not
  fully reconstructed.
- **`run_id` is mandatory for receive.** A blank `run_id` returns an
  empty list because of the `WHERE run_id = ?` filter. Your orchestrator
  needs to thread the run ID through.
- **Acknowledgement is one-shot.** `agent_acknowledge_message` only
  updates rows where `read_at = ''`. Calling it twice is a no-op (and
  returns `ok: false` the second time).
- **Broadcasts are visible to everyone in the run** including the
  sender. Filter on `from_agent != self` if you want to avoid hearing
  your own broadcasts.
- **Database location is implicit.** Created lazily at
  `<plans_dir>/messages.db` on first use. If you don't set a plans
  directory, it lands in `cwd/messages.db` which can cause confusion
  across runs from different shells.
- **Negotiation `message_type` values are not first-class in the schema.**
  Treat them as labels — your code should switch on them, but don't
  expect the storage layer to enforce them.

## See also

- [`src/swarm/messaging/api.py`](../src/swarm/messaging/api.py) — Python API
- [`src/swarm/messaging/db.py`](../src/swarm/messaging/db.py) — schema
- [`src/swarm/messaging/models.py`](../src/swarm/messaging/models.py) — `AgentMessage`
- [`src/swarm/mcp/message_tools.py`](../src/swarm/mcp/message_tools.py) — MCP wrappers
- [memory.md](memory.md) — sibling subsystem for per-agent persistent state
