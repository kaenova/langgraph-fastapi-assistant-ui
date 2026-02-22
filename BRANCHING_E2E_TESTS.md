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
