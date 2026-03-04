Got it. Here’s a focused plan that aligns with your comments and the current architecture, without making any edits yet.
Interpretation of your desired flow
- Keep normal chat generation unchanged.
- After each assistant response, backend computes total token usage and returns a flag next_should_compact if threshold exceeded (e.g., 10k).
- Frontend receives the flag and immediately calls a compaction endpoint.
- Compaction returns a special assistant message with metadata.custom.compaction = true.
- When sending new messages, frontend should filter history so it only includes messages from the latest compaction marker onward.
Proposed architecture
1) Compaction agent graph (LLM-only)
- Create a dedicated LangGraph (or simpler “agent”) that only runs a compaction LLM call.
- Input: message list + config (strategy, max tokens, keep last N turns).
> I think we don't need strategy, max tokens, or even keep last N turns. We just recieves what message to compact
- Output: a single “compaction summary” assistant message (not replacing UI history).
> Following normal flow of chat, this should return the compacted message with the metadata as this is a compact message
- This keeps compaction logic separate and testable.
2) Backend: token accounting + flagging
- In backend/routes/chat.py, after response is complete and before persisting, estimate total tokens for payload.messages + assistant_message.
- If above threshold, set assistant_message.metadata.custom.next_should_compact = true.
- Persist as usual (full messages).
3) Backend: compaction endpoint
- New endpoint, e.g. POST /api/v1/threads/{thread_id}/compact.
> I think compact is a stateless endpoint, we just need to recieves the messages. So change it to /api/v1/compact
- It loads persisted messages, finds the most recent compaction marker (if any), and only compacts messages after that.
> As my comment before, we already get the messages from the frontend
- Uses the compaction graph to produce a summary assistant message.
- Returns:
  - compacted_message (assistant) with metadata.custom.compaction = true.
  - Optionally compaction_window info (message IDs, counts) for debugging.
4) Frontend: compaction trigger
- When receiving next_should_compact = true, call the compaction endpoint.
- Append the returned compaction message to the runtime history (as a normal assistant message).
> YES! This is important, so it looks like a normal message in the chat history like the others, but with the metadata.
- This message becomes the anchor for future message selection.
> YEP YEP
5) Frontend: history filtering on run
- When sending to /runs/stream, filter thread messages so only messages after the latest compaction marker are included (plus the compaction summary message itself).
- This ensures the model context is bounded without altering the persisted full history.
---
Key decisions to confirm
1) Should compaction replace older messages in the request or prepend the summary and keep the last N messages after it?  
   - Recommended: prepend summary + keep last N intact.
   > Replace older message
2) Should compaction be triggered client-side only (as you described), or should backend also auto‑compact if client missed it?  
   - Recommended: client-only is fine, but backend fallback can prevent runaway context growth.
   > Client side
3) Do you want compaction to be strategy‑based (trim vs summary), or summary-only since you’re adding an LLM compaction graph?
  > summary only
If you confirm the above, I’ll translate it into a concrete implementation plan (API shape, payloads, and where to add metadata checks).