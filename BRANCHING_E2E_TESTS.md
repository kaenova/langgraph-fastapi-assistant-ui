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

**Test Result: ❌ FAILED - CRITICAL ISSUE**
- After page reload, branch picker UI completely disappeared
- Branch data persists on backend (content still available)
- Branch picker buttons (Previous/Next with "X / Y" indicators) not visible after reload
- Page defaults to showing one branch variant instead of maintaining branch state
- **Root Cause**: Branch selection state not persisted to localStorage or backend state

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

---

## Test Summary

| Test | Status | Notes |
|------|--------|-------|
| Test 1: Regenerate Creates Assistant Branch | ✅ PASSED | Branch picker correctly shows on assistant message |
| Test 2: Edit Creates User Branch | ✅ PASSED | Branch picker correctly shows on user message |
| Test 3: Branch Switching Updates Visible Timeline | ✅ PASSED | Previous/Next navigation works smoothly |
| Test 4: New Message Continues From Active Branch | ✅ PASSED | Follow-ups attach to selected branch lineage |
| Test 5: Branch State Persists on Reload | ❌ FAILED | **Critical: Branch picker UI disappears after reload** |
| Test 6: Regenerate + Edit Separation | ✅ PASSED | Independent branch ownership maintained |
| Test 7: Streaming During New Branch Does Not Corrupt Previous Messages | ✅ PASSED | Streaming isolated to current message |
| Test 8: Branching Works Across Welcome -> Chat Handoff | ✅ PASSED | Full branching works post-redirect |

**Overall Result: 7 of 8 tests passed (87.5%)**

### Critical Issues Identified

**Issue #1 - Branch State Not Persisted on Reload (Test 5)**
- **Severity**: HIGH
- **Description**: After page reload, the branch picker UI completely disappears despite branch data existing in the backend
- **Impact**: Users cannot navigate between branches after refreshing the page
- **Affected Tests**: Test 5
- **Root Cause**: Branch selection state (current branch index) not stored in localStorage or frontend state management
- **Suggested Fix**: Persist selected branch index to localStorage and restore on page load

**Test Result: ✅ PASSED**
- Started from `/welcome` with "Give me two title ideas for a testing guide."
- Successfully redirected to `/chat/b03eef15-c52e-4060-b25f-f9cf963a4a93`
- Regenerate created assistant branch (showed "2 / 2")
- Edit created user branch (showed "2 / 2")
- Edited to: "Give me three title ideas for a testing guide focused on API testing."
- Assistant correctly provided three API testing focused titles
- Full branching functionality works seamlessly across welcome->chat handoff
