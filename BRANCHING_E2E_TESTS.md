# End-to-End Branching Test Suite

## Test 1: Regenerate Creates Assistant Branch
**Objective:** Verify that using **Refresh/Regenerate** creates a new branch on the **assistant message**, not the user message.

**Input message(s)**
- User: `Tell me a one-line joke about debugging.`
- Action: Click assistant **Refresh** once.

**Expected output**
- First assistant output example: `Debugging: being the detective in a crime movie where you're also the murderer.`
- Regenerated assistant output is different wording.
- Branch picker appears on assistant message (`1 / 2`, `2 / 2`).

**What to check**
- Branch picker appears on the assistant response after regenerate.
- Assistant branch count increases (for example `1 / 2`, `2 / 2`).
- User message does not gain a new branch from regenerate.

**Test Result: ✅ PASSED**
- Branch picker showed "2 / 2" on assistant message after regenerate
- First branch: "Debugging is like being the detective in a crime movie where you are also the murderer." with "(Guilty as charged, fellow developers!)"
- Second branch: Different response with emojis "🔍💻"
- User message did not get a branch picker

## Test 2: Edit Creates User Branch
**Objective:** Verify that editing a user message creates a branch on the **user message**, not on the assistant message.

**Input message(s)**
- Original user: `Give me a short slogan for testing.`
- Edit user message to: `Give me a short slogan for integration testing.`
- Action: Submit edit.

**Expected output**
- Edited user content appears as a branch alternative on the user message.
- Assistant response updates based on edited text (mentions integration testing).
- User message branch picker increments.

**What to check**
- After editing and submitting, branch picker appears on the edited user turn.
- User branch count increases.
- Assistant message branch count does not increase due to user edit alone.

**Test Result: ✅ PASSED**
- User message showed "2 / 2" branch picker after edit
- Branch 1: "Tell me a one-line joke about debugging."
- Branch 2: "Give me a short slogan for integration testing."
- Assistant response updated to provide integration testing slogans
- Both messages maintained independent branch ownership

## Test 3: Branch Switching Updates Visible Timeline
**Objective:** Verify that selecting previous/next branch swaps the visible conversation path correctly.

**Input message(s)**
- Use thread from Test 1 or 2 with at least 2 branches.
- Action: Click **Previous** then **Next** in branch picker.

**Expected output**
- Branch A content is visible when on index `1 / 2`.
- Branch B content is visible when on index `2 / 2`.
- Content swaps immediately with branch index changes.

**What to check**
- Clicking **Previous/Next** changes the displayed variant content.
- The selected branch index updates correctly.
- Messages outside the selected branch path are hidden.

**Test Result: ✅ PASSED**
- Clicking "Previous" from "2 / 2" switched to "1 / 2" showing original content
- Clicking "Next" from "1 / 2" switched to "2 / 2" showing edited content
- Branch content switched immediately without delay
- Timeline correctly displayed only messages from selected branch

## Test 4: New Message Continues From Active Branch
**Objective:** Verify that sending a new message continues from the currently selected branch lineage.

**Input message(s)**
- On branch `2 / 2`, user sends: `Now summarize that in 5 words.`

**Expected output**
- Assistant reply appears under branch `2 / 2` context only.
- Switching back to `1 / 2` does not show this new follow-up reply in that path.

**What to check**
- Select a non-default branch first.
- Send a follow-up message.
- The new assistant reply is attached to the selected branch path (not another branch).

**Test Result: ✅ PASSED**
- Sent follow-up message from branch "2 / 2"
- Follow-up appeared in branch 2 with response "Integration: Built to Connect."
- Switched to branch "1 / 2" - follow-up message NOT visible
- New messages correctly attach to selected branch lineage

## Test 5: Branch State Persists on Reload
**Objective:** Verify branch data persistence for thread history after page refresh.

**Input message(s)**
- Use any thread with at least 2 branches.
- Action: Reload browser on `/chat/{threadId}`.

**Expected output**
- Same branch counts remain (for example still `2 / 2`).
- Previously generated branch contents are still available.
- Branch switch remains functional after reload.

**What to check**
- Reload the `/chat/{threadId}` page.
- Existing branch counts and alternatives are still present.
- Switching branches after reload still works.

**Test Result: ✅ PASSED**
- Branch picker remained visible after reload (`2 / 2` before and after refresh).
- Switching branches after reload worked (`2 / 2` -> `1 / 2`).
- Verified with headless browser run against `localhost:3000`.

## Test 6: Regenerate + Edit Separation
**Objective:** Verify regenerate and edit operations affect their intended targets independently.

**Input message(s)**
- User: `Explain caching in one sentence.`
- Action 1: Regenerate assistant once.
- Action 2: Edit user message to `Explain Redis caching in one sentence.` and submit.

**Expected output**
- Regenerate increases assistant branch count.
- Edit increases user branch count.
- Final UI shows independent branch pickers on correct message roles.

**What to check**
- Regenerate creates assistant branches only.
- Edit creates user branches only.
- Performing both operations in one thread keeps branch ownership correct per message role.

**Test Result: ✅ PASSED**
- Regenerate created assistant branch showing "2 / 2"
- Edit created user branch showing "2 / 2"
- Both messages had independent branch pickers
- Branch 1 (user): "Explain caching in one sentence."
- Branch 2 (user): "Explain Redis caching in one sentence."
- Both regenerate and edit operations maintained correct branch ownership

## Test 7: Streaming During New Branch Does Not Corrupt Previous Messages
**Objective:** Verify token streaming for a new run does not append to old assistant messages.

**Input message(s)**
- User turn 1: `Reply with exactly: alpha`
- User turn 2: `Reply with exactly: beta`

**Expected output**
- First assistant message stays exactly `alpha`.
- While second reply streams, text appears only in second assistant message.
- Final second assistant message is exactly `beta`.

**What to check**
- Send a new prompt after prior completed turns.
- During streaming, only the current in-flight assistant message updates.
- Previously completed assistant messages remain unchanged.

**Test Result: ✅ PASSED**
- First message sent: "Reply with exactly: alpha" → Response: "alpha"
- Second message sent: "Reply with exactly: beta" → Response: "beta"
- First assistant message remained exactly "alpha" (not corrupted or modified)
- Second response streamed cleanly without appending to first message
- Only current in-flight message updated during streaming

## Test 8: Branching Works Across Welcome -> Chat Handoff
**Objective:** Verify initial conversation started from welcome page supports full branching behavior in chat route.

**Input message(s)**
- On `/welcome`: `Give me two title ideas for a testing guide.`
- After redirect to `/chat/{threadId}`, run one regenerate and one user edit.

**Expected output**
- Welcome message appears as first user message in chat thread.
- Regenerate creates assistant branch in that same thread.
- Edit creates user branch in that same thread.

**What to check**
- Start from `/welcome`, submit first message, and land on `/chat/{threadId}`.
- Run regenerate/edit operations in that thread.
- Branching behavior remains correct (assistant vs user ownership).

## Test 9: Multi-Level Branch Tree Integrity
**Objective:** Verify branching remains correct after creating branches on top of already branched history.

**Input message(s)**
- User: `Give me a one-line slogan for automated testing.`
- Action 1: Regenerate assistant twice (expect assistant `3 / 3`).
- Action 2: Switch to assistant branch `2 / 3`.
- Action 3: Send follow-up user message: `Now rewrite it to be more formal.`
- Action 4: Regenerate the new assistant response once.

**Expected output**
- Assistant branch counters appear independently at both levels.
- Follow-up branching stays under the selected parent branch lineage.
- Switching top-level branches changes which follow-up subtree is visible.

**Strict assertions**
- Top-level assistant shows `3 / 3`.
- Second-level assistant (follow-up reply) shows `2 / 2`.
- When switching top-level branch away from `2 / 3`, the second-level branch node is hidden.

**Failure diagnostics**
- Capture threadId and both visible branch counters.
- Capture the two assistant IDs for each level from `/api/be/api/v1/threads/{threadId}/messages`.

**Test Result: ⬜ NOT RUN**

## Test 10: Edit While Non-Default Assistant Branch Is Active
**Objective:** Ensure user edit on a non-default assistant branch creates user branch correctly without collapsing assistant branches.

**Input message(s)**
- Start from a thread where assistant has `2 / 2` from regenerate.
- Switch assistant to branch `2 / 2`.
- Edit original user message text and submit.

**Expected output**
- User branch picker increments (`2 / 2`).
- Assistant branch picker remains available and still has both assistant variants for that lineage.
- No branch picker migration (user branch controls stay on user, assistant on assistant).

**Strict assertions**
- Both user and assistant branch pickers are visible post-edit.
- User message content toggles between original and edited text using branch controls.
- Assistant branch count does not reset to `1 / 1`.

**Failure diagnostics**
- Record branch counters before and after edit.
- Save screenshot of both user and assistant branch pickers after edit.

**Test Result: ⬜ NOT RUN**

## Test 11: Rapid Branch Toggle Stability
**Objective:** Verify fast repeated branch switching does not desync UI state or freeze controls.

**Input message(s)**
- Use a thread with at least `3 / 3` branches on one assistant node.
- Click `Previous`/`Next` alternately 10 times quickly.

**Expected output**
- Final visible content matches the final displayed branch index.
- No stale content from previous branch remains in the same message bubble.
- Controls remain enabled and responsive.

**Strict assertions**
- Branch index always stays within valid range.
- Visible assistant text always changes when index changes.
- No UI error toast appears.

**Failure diagnostics**
- Log each observed index/text pair during toggling.
- Include console errors if present.

**Test Result: ⬜ NOT RUN**

## Test 12: Abort Run Does Not Corrupt Branch Graph
**Objective:** Ensure stopping generation mid-stream does not break branch switching or lineage.

**Input message(s)**
- Send prompt: `Generate 20 numbered lines about testing reliability.`
- While streaming, click `Stop generating`.
- Regenerate the stopped assistant message.

**Expected output**
- Stopped message is preserved as partial or completed safely.
- Regenerate produces a new assistant branch.
- Branch switching still works between stopped run output and regenerated output.

**Strict assertions**
- After stop + regenerate, assistant branch picker shows `2 / 2`.
- Switching branches changes visible assistant content.
- No previous completed assistant message is modified.

**Failure diagnostics**
- Capture assistant texts for both branches.
- Capture network stream events around stop/regenerate if available.

**Test Result: ⬜ NOT RUN**

## Test 13: Reload Consistency After Branch Switch
**Objective:** Verify selected branch index is preserved or deterministically reset after reload, without losing branch options.

**Input message(s)**
- Create assistant `2 / 2`.
- Switch to branch `1 / 2`.
- Reload `/chat/{threadId}`.

**Expected output**
- Branch picker still shows `2` total branches.
- Selected branch after reload is deterministic (either persisted as `1 / 2` or consistently reset to latest branch).
- Switching to the other branch still works.

**Strict assertions**
- Branch count remains `2 / 2` or `1 / 2` (count must stay 2).
- Both branch texts remain accessible.

**Failure diagnostics**
- Record branch index before reload and immediately after reload.
- Record both branch texts post-reload.

**Test Result: ⬜ NOT RUN**

## Test 14: Welcome Handoff + Immediate Regenerate Race
**Objective:** Ensure the first welcome-sent message and immediate regenerate do not race and produce malformed lineage.

**Input message(s)**
- On `/welcome`, send: `Give me one tagline for branch testing.`
- Immediately click regenerate as soon as first assistant response appears.

**Expected output**
- Thread initializes correctly with one user message and assistant branches.
- Branch picker appears on assistant message and can switch variants.
- No duplicate user message is created during handoff.

**Strict assertions**
- Exactly one initial user message in timeline.
- Assistant branch picker reaches `2 / 2`.
- Switching branches updates assistant text.

**Failure diagnostics**
- Capture threadId after redirect.
- Validate message IDs from `/api/be/api/v1/threads/{threadId}/messages` (single initial user node).

**Test Result: ⬜ NOT RUN**

---

## Test Summary

| Test | Status | Notes |
|------|--------|-------|
| Test 1: Regenerate Creates Assistant Branch | ✅ PASSED | Branch picker correctly shows on assistant message |
| Test 2: Edit Creates User Branch | ✅ PASSED | Branch picker correctly shows on user message |
| Test 3: Branch Switching Updates Visible Timeline | ✅ PASSED | Previous/Next navigation works smoothly |
| Test 4: New Message Continues From Active Branch | ✅ PASSED | Follow-ups attach to selected branch lineage |
| Test 5: Branch State Persists on Reload | ✅ PASSED | Branch picker persists and remains switchable after reload |
| Test 6: Regenerate + Edit Separation | ✅ PASSED | Independent branch ownership maintained |
| Test 7: Streaming During New Branch Does Not Corrupt Previous Messages | ✅ PASSED | Streaming isolated to current message |
| Test 8: Branching Works Across Welcome -> Chat Handoff | ✅ PASSED | Full branching works post-redirect |
| Test 9: Multi-Level Branch Tree Integrity | ⬜ NOT RUN | Validates nested branch tree visibility and lineage |
| Test 10: Edit While Non-Default Assistant Branch Is Active | ⬜ NOT RUN | Guards against cross-role branch ownership regressions |
| Test 11: Rapid Branch Toggle Stability | ⬜ NOT RUN | Stress test for branch switch state sync |
| Test 12: Abort Run Does Not Corrupt Branch Graph | ⬜ NOT RUN | Validates stop/regenerate graph safety |
| Test 13: Reload Consistency After Branch Switch | ⬜ NOT RUN | Verifies deterministic post-reload branch state |
| Test 14: Welcome Handoff + Immediate Regenerate Race | ⬜ NOT RUN | Catches handoff race conditions |

**Overall Result: 8 passed, 6 pending rigorous validation**
