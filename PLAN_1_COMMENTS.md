I’d integrate compaction as an inference‑time step in the backend stream path so UI history stays untouched, then optionally share that helper with the LangGraph graph for consistency. The current chat flow uses backend/routes/chat.py for model streaming (not backend/agent/graph.py), so that’s the critical insertion point.
Proposed integration
- Add a compaction helper (e.g., backend/agent/compaction.py) that takes BaseMessage[] and a config and returns compacted messages.
> This is good, let's create new graph or agent for compaction, it should be only llm node right?

- Keep persistence unchanged: still save full payload.messages via thread_store.replace_messages(...) so Assistant UI history and branching remain exact.
> Keep this concept

- In backend/routes/chat.py, right after _to_langchain_messages(...), call compaction before model_with_tools.astream(...).
- Use trim_messages + count_tokens_approximately with start_on="human" and end_on=("human","tool") so tool-call sequences stay valid; follow with sanitize_and_validate_messages(...).


---

Let's rediscuss it agin for below points

- Wire config via runConfig.compaction (from frontend/lib/assistant-template/runtime/adapters.ts) with env defaults (e.g., COMPACTION_MAX_TOKENS, COMPACTION_STRATEGY) so it’s controllable without UI changes.
- If you want summaries: add an optional summarization pass that creates a single SystemMessage("Summary: ...") for older history, store it in thread metadata (e.g., thread.compaction.summary in backend/lib/thread_store.py), and inject it only at inference time (not into UI messages).
Why this fits the repo
- Keeps Assistant UI’s history repository intact (/history and append) and avoids showing synthetic summary messages to users.
- Centralizes compaction in the server path that actually feeds the model (backend/routes/chat.py).
- Respects tool‑call pairing and existing message sanitation.
One targeted question so I can design the right path:  
Do you want compaction to be trim‑only and ephemeral (recommended: simple, no extra model calls), or hybrid with persisted summaries stored in thread metadata (adds a summarization step and new thread fields)?  
- If trim‑only: I’ll focus on trim_messages + config in run_stream.  
- If hybrid: I’ll add a summarizer step and summary persistence in backend/lib/thread_store.py

---

Probably my idea is that, the frontend after finished generating AI content from normal flow, it will check how long the token so far.
And this information so it doesn't go back-and-forth from frontend to the backend, can we send custom data via normal chat endpoint, and at the end, the backend calculate the token so far all the messages.

Let's say after 10k token, we do compaction. this 10k token should be informed by the backend in the same response on generating AI message. Don't forget to save in the metadata of the AI message that next_should_compact=True. It will be useful to check on the every load that the last message if we have next should compact, we automatically do compaction

The frontend recieve this flags, and then doing the compaction immediately. It will send to the compaction endpoint, and then recieve the compaction. This compaction message should have custom metadata of compaction=True.

So that in the normal flow of sending message, we should evaluate is there any compaction metadata? If yes, then we only get tha latest to the compaction=True only.