# LangGraph Conversation State & Persistence

LangGraph models chat workflows as **stateful graphs**. You define a shared “state” schema (often including a messages: Message\[\] channel) and add nodes (LLM calls, business logic) and edges (transitions or conditions) to control flow[\[1\]](https://docs.langchain.com/oss/python/langgraph/graph-api#:~:text=At%20its%20core%2C%20LangGraph%20models,agents%20using%20three%20key%20components)[\[2\]](https://docs.langchain.com/oss/python/langgraph/graph-api#:~:text=this%2C%20you%20can%20use%20the,updates%20for%20existing%20messages%20correctly). Crucially, LangGraph’s runtime **checkpointing** captures the entire state at each step: when you compile with a checkpointer, every super-step’s state is saved as a _checkpoint_ under a thread ID[\[3\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=LangGraph%20has%20a%20built,tolerance%20are%20all)[\[4\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=A%20thread%20is%20a%20unique,portion%20of%20the%20config). Each **thread** (identified by thread_id in config) then holds the history of all checkpoints (conversation states) for that session[\[4\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=A%20thread%20is%20a%20unique,portion%20of%20the%20config). This built-in persistence enables powerful features: you can resume or “time-travel” to any checkpoint to branch or retry, and support human-in-the-loop, memory, and fault tolerance without losing earlier context[\[3\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=LangGraph%20has%20a%20built,tolerance%20are%20all)[\[5\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=Time%20travel).

- **Message list in state:** Typically the state schema includes a list of chat messages. Use the provided add_messages reducer (or MessagesState base) to accumulate the conversation. This reducer _appends new messages_ and correctly **updates** edited messages by ID[\[2\]](https://docs.langchain.com/oss/python/langgraph/graph-api#:~:text=this%2C%20you%20can%20use%20the,updates%20for%20existing%20messages%20correctly), ensuring that modifying a past message replaces it rather than duplicating. For example, if your state is { messages: \[\] }, use add_messages so that updates (edits) to existing messages overwrite the old entry[\[2\]](https://docs.langchain.com/oss/python/langgraph/graph-api#:~:text=this%2C%20you%20can%20use%20the,updates%20for%20existing%20messages%20correctly).
- **Checkpoint threads:** At runtime, each call (turn) into the graph saves the updated state to the thread. You must supply thread_id in the config when invoking the graph so that LangGraph knows which conversation thread to persist[\[4\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=A%20thread%20is%20a%20unique,portion%20of%20the%20config). After execution you can fetch the latest state or any checkpoint history via the LangGraph API or SDK. For instance, client.threads.getState(threadId) returns the most recent state snapshot for that thread[\[6\]](https://www.assistant-ui.com/docs/runtimes/langgraph#:~:text=export%20const%20sendMessage%20%3D%20async,threadId)[\[7\]](https://www.assistant-ui.com/docs/runtimes/langgraph#:~:text=export%20function%20MyAssistant%28%29%20,threadId%3A%20externalId%2C%20messages%2C%20config).

# Message Editing & Regeneration

LangGraph’s statefulness makes **editing messages** and **regenerating AI responses** straightforward. Because every chat message lives in the graph state, you can “time-travel” back to the exact state before a given AI response and run the graph again from there. In practice, this means: when a user edits a previous message or hits “Regenerate,” you load the state of the graph at that message’s checkpoint and resume.

- **Editing a user message:** First, record which checkpoint corresponds to that message (the user’s last message). In the UI, you can use getMessagesMetadata() (from the LangGraph SDK) on each message to find firstSeenState.parent_checkpoint, i.e. the checkpoint before the AI response was produced[\[8\]](https://docs.langchain.com/oss/javascript/langchain/streaming/frontend#:~:text=Branching). Then submit the edited message as a new human-turn update **at that checkpoint**. For example:  
    
- // on edit button click  
    const newContent = /\* edited text \*/;  
    const parentCheckpoint = meta?.firstSeenState?.parent_checkpoint;  
    stream.submit(  
    { messages: \[{ type: "human", content: newContent }\] },  
    { checkpoint: parentCheckpoint }  
    );
- This tells LangGraph to roll back to the earlier state and inject the edited user message there. The graph will then re-run the downstream nodes (LLM calls) from that point. The add_messages reducer ensures the original message is replaced by the edited version in state[\[2\]](https://docs.langchain.com/oss/python/langgraph/graph-api#:~:text=this%2C%20you%20can%20use%20the,updates%20for%20existing%20messages%20correctly).
- **Regenerating an AI response:** Similar idea: to get an alternate AI answer, you also resume at the checkpoint _before_ the original response. In code:  
    
- // on regenerate button click (for an AI message)  
    stream.submit(undefined, { checkpoint: parentCheckpoint });
- Passing undefined as the update means “no new user message,” so the model runs again from that point. You can also vary parameters (e.g. temperature) in config to get a different answer. Since the conversation context is restored exactly as it was, the model produces a new response variant.
- **Versioning vs branching:** Under the hood, each of these actions creates a new “branch” of the conversation. You are effectively forking the thread history into an alternate timeline (much like Git commits)[\[5\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=Time%20travel). You might also version messages in your own storage (e.g. keep edit history in a database) for auditing. But LangGraph itself handles state rollback: after editing/regeneration, the new messages simply become part of the active thread (or a new branch) while the old branch can be kept for reference if needed.

# Conversation Branching & Forked Paths

LangGraph explicitly supports **branching** the chat flow. Its checkpointing lets you fork the conversation graph at arbitrary points[\[5\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=Time%20travel). In the UI, LangGraph’s streaming API exposes metadata such as branch and branchOptions for each message[\[8\]](https://docs.langchain.com/oss/javascript/langchain/streaming/frontend#:~:text=Branching). You can present these branches to the user (e.g. via a “BranchSwitcher” component) and call stream.setBranch(branchId) to switch between alternate timelines[\[9\]](https://docs.langchain.com/oss/javascript/langchain/streaming/frontend#:~:text=%7B%2F,stream.setBranch%28branch%29%7D).

- **Time travel:** As documented, “checkpointers allow for ‘time travel’ – replaying prior graph executions – and make it possible to fork the graph state at arbitrary checkpoints to explore alternative trajectories”[\[5\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=Time%20travel). In practice, when the user edits or regenerates, the UI tells LangGraph to continue from the earlier checkpoint (parent_checkpoint), creating a new fork. LangGraph tracks these forks internally (each branch has its own ID), so you can later revisit either branch.
- **UI support:** LangGraph’s React SDK (useStream) supports conversation branching out of the box. The example below (from LangChain’s docs) shows how to wire edit/regenerate buttons and a branch selector:

const stream = useStream({ assistantId: "...", apiUrl: "..." });  
return stream.messages.map(msg => {  
const meta = stream.getMessagesMetadata(msg);  
const parentCp = meta?.firstSeenState?.parent_checkpoint;  
return (  
&lt;div&gt;  
{/\* Edit user message \*/}  
{msg.type === "human" && &lt;button onClick={() =&gt; {  
const newText = prompt("Edit:", msg.content);  
stream.submit({messages:\[{type:"human", content:newText}\]}, {checkpoint: parentCp});  
}}>Edit&lt;/button&gt;}  
{/\* Regenerate AI message \*/}  
{msg.type === "ai" && &lt;button onClick={() =&gt; {  
stream.submit(undefined, {checkpoint: parentCp});  
}}>Regenerate&lt;/button&gt;}  
{/\* Branch switcher \*/}  
<BranchSwitcher  
branch={meta.branch}  
branchOptions={meta.branchOptions}  
onSelect={(b) => stream.setBranch(b)}  
/>  
&lt;/div&gt;  
);  
});

This code uses getMessagesMetadata() to find parent_checkpoint and calls stream.submit(..., { checkpoint: parentCp }) to branch from that point[\[8\]](https://docs.langchain.com/oss/javascript/langchain/streaming/frontend#:~:text=Branching)[\[9\]](https://docs.langchain.com/oss/javascript/langchain/streaming/frontend#:~:text=%7B%2F,stream.setBranch%28branch%29%7D). The BranchSwitcher component toggles between available branches via stream.setBranch.

- **Graph config:** In your StateGraph, you don’t need special edges for branching; it’s managed by the runtime. You do need to include an appropriate messages reducer (e.g. add_messages) so that when you branch back and inject an edited message, the state updates correctly[\[2\]](https://docs.langchain.com/oss/python/langgraph/graph-api#:~:text=this%2C%20you%20can%20use%20the,updates%20for%20existing%20messages%20correctly). Beyond that, you might use conditional edges or nodes to implement fallback or loop logic as usual. Branching largely happens at the runtime level via the checkpointer, not as explicit graph transitions in your code.

# Next.js & Assistant UI Integration

For a Next.js chatbot with the [assistant-ui](https://assistant-ui.com/) components and LangGraph backend, you typically: create/load a conversation thread, stream messages to the LangGraph agent server, and render the chat. The [assistant-ui/react-langgraph](https://github.com/assistant-ui/assistant-ui) library provides hooks to simplify this. For example:

- **Thread setup:** Use client.threads.create() to start a new thread (conversation ID) and store the thread_id. When loading an existing conversation, call client.threads.getState(threadId) to retrieve its last state[\[6\]](https://www.assistant-ui.com/docs/runtimes/langgraph#:~:text=export%20const%20sendMessage%20%3D%20async,threadId)[\[4\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=A%20thread%20is%20a%20unique,portion%20of%20the%20config).
- **Streaming messages:** Call client.runs.stream(threadId, assistantId, { input: { messages }, streamMode: "messages-tuple" }) to send new chat messages and get streaming responses[\[6\]](https://www.assistant-ui.com/docs/runtimes/langgraph#:~:text=export%20const%20sendMessage%20%3D%20async,threadId). The Assistant UI example wraps this in a sendMessage helper and a useLangGraphRuntime hook. In code, it looks like:

const client = new Client({ apiUrl: process.env.NEXT_PUBLIC_LANGGRAPH_API_URL });  
// Helper to stream messages  
async function sendMessage(threadId: string, messages) {  
return client.runs.stream(  
threadId,  
process.env.NEXT_PUBLIC_LANGGRAPH_ASSISTANT_ID!,  
{ input: { messages }, streamMode: "messages-tuple" }  
);  
}  
// In the React component  
const runtime = useLangGraphRuntime({  
// Called on each user input or bot response  
stream: async (messages, { initialize, config }) => {  
const { externalId } = await initialize(); // ensures a thread exists  
return sendMessage(externalId, messages);  
},  
create: async () => {  
const { thread_id } = await client.threads.create();  
return { externalId: thread_id };  
},  
load: async (externalId) => {  
const state = await client.threads.getState(externalId);  
return { messages: state.values.messages, interrupts: state.tasks\[0\]?.interrupts };  
},  
});

This hook manages thread creation/loading and uses sendMessage (which calls client.runs.stream) to handle chat turns[\[6\]](https://www.assistant-ui.com/docs/runtimes/langgraph#:~:text=export%20const%20sendMessage%20%3D%20async,threadId)[\[7\]](https://www.assistant-ui.com/docs/runtimes/langgraph#:~:text=export%20function%20MyAssistant%28%29%20,threadId%3A%20externalId%2C%20messages%2C%20config). The streaming response from LangGraph is fed into the Assistant UI’s &lt;Thread&gt; component for display.

- **Assistant Chat UI:** LangChain also provides a prebuilt **Agent Chat UI** (Next.js) with out-of-the-box support for LangGraph agents. It advertises support for “time-travel debugging and state forking,” meaning it can visualize and allow replay/branching of conversation threads[\[10\]](https://docs.langchain.com/oss/python/langchain/ui#:~:text=Agent%20Chat%20UI%20is%20a,adapted%20to%20your%20application%20needs). You can either use or study this code as a reference architecture.

# Key Takeaways & Recommended Approaches

- **Use LangGraph checkpointing:** Compile your graph with a checkpointer (e.g. MemorySaver or LangSmith). Every graph invocation persists state to a thread, enabling rollback and branch forks[\[3\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=LangGraph%20has%20a%20built,tolerance%20are%20all)[\[5\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=Time%20travel).
- **Design state for editability:** Include a messages list in state and use the add_messages reducer so edits replace existing messages properly[\[2\]](https://docs.langchain.com/oss/python/langgraph/graph-api#:~:text=this%2C%20you%20can%20use%20the,updates%20for%20existing%20messages%20correctly). Keep any message IDs or version info if needed.
- **Handle edits/regenerations via checkpoints:** On an edit or “regenerate” action, resume the graph at the prior checkpoint (found via message metadata). Submit the new input (or no new input) with streamMode: "messages-tuple" and { checkpoint: parentCheckpoint } to branch the conversation[\[8\]](https://docs.langchain.com/oss/javascript/langchain/streaming/frontend#:~:text=Branching)[\[11\]](https://docs.langchain.com/oss/javascript/langchain/streaming/frontend#:~:text=%7Bmessage.type%20%3D%3D%3D%20,button%3E).
- **Branch management:** Use the LangGraph SDK’s built-in branching hooks (getMessagesMetadata, stream.setBranch) to let users switch between alternate paths[\[8\]](https://docs.langchain.com/oss/javascript/langchain/streaming/frontend#:~:text=Branching)[\[9\]](https://docs.langchain.com/oss/javascript/langchain/streaming/frontend#:~:text=%7B%2F,stream.setBranch%28branch%29%7D). Design your UI (e.g. a branch selector) to display available forks.
- **Integrate with Next.js + Assistant UI:** Use useLangGraphRuntime or useStream (from @langchain/langgraph-sdk/react) to manage thread state and streaming in React. Follow the assistant-ui LangGraph docs: initialize or load a thread on start, stream messages via client.runs.stream, and render responses with &lt;Thread&gt; or similar components[\[6\]](https://www.assistant-ui.com/docs/runtimes/langgraph#:~:text=export%20const%20sendMessage%20%3D%20async,threadId)[\[7\]](https://www.assistant-ui.com/docs/runtimes/langgraph#:~:text=export%20function%20MyAssistant%28%29%20,threadId%3A%20externalId%2C%20messages%2C%20config).
- **Refer to examples:** Review the LangChain frontend examples (e.g. the “branching-chat” demo on GitHub) and documentation for code patterns. The assistant-ui docs and LangChain docs provide end-to-end examples of edit/regenerate buttons and branch switching[\[8\]](https://docs.langchain.com/oss/javascript/langchain/streaming/frontend#:~:text=Branching)[\[10\]](https://docs.langchain.com/oss/python/langchain/ui#:~:text=Agent%20Chat%20UI%20is%20a,adapted%20to%20your%20application%20needs).

By leveraging LangGraph’s persistent state and branching features, you can implement robust message editing, versioning, backtracking, and alternative conversation paths in your Next.js chatbot. The key is to store full conversation state in the graph, use checkpoints for rollback, and wire the UI’s edit/regenerate actions to LangGraph’s branching API.

**Sources:** LangChain LangGraph documentation on persistence, threading, and streaming[\[3\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=LangGraph%20has%20a%20built,tolerance%20are%20all)[\[5\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=Time%20travel)[\[2\]](https://docs.langchain.com/oss/python/langgraph/graph-api#:~:text=this%2C%20you%20can%20use%20the,updates%20for%20existing%20messages%20correctly)[\[8\]](https://docs.langchain.com/oss/javascript/langchain/streaming/frontend#:~:text=Branching); LangChain Agent Chat UI docs[\[10\]](https://docs.langchain.com/oss/python/langchain/ui#:~:text=Agent%20Chat%20UI%20is%20a,adapted%20to%20your%20application%20needs); assistant-ui React SDK guide for LangGraph[\[6\]](https://www.assistant-ui.com/docs/runtimes/langgraph#:~:text=export%20const%20sendMessage%20%3D%20async,threadId)[\[7\]](https://www.assistant-ui.com/docs/runtimes/langgraph#:~:text=export%20function%20MyAssistant%28%29%20,threadId%3A%20externalId%2C%20messages%2C%20config); community Q&A on editing/regeneration[\[12\]](https://community.latenode.com/t/how-to-implement-message-editing-and-response-regeneration-features-with-langchain-or-langgraph/39411#:~:text=LangGraph%E2%80%99s%20checkpointing%20is%20exactly%20what,the%20state%20management%20for%20you).

[\[1\]](https://docs.langchain.com/oss/python/langgraph/graph-api#:~:text=At%20its%20core%2C%20LangGraph%20models,agents%20using%20three%20key%20components) [\[2\]](https://docs.langchain.com/oss/python/langgraph/graph-api#:~:text=this%2C%20you%20can%20use%20the,updates%20for%20existing%20messages%20correctly) Graph API overview - Docs by LangChain

https://docs.langchain.com/oss/python/langgraph/graph-api

[\[3\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=LangGraph%20has%20a%20built,tolerance%20are%20all) [\[4\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=A%20thread%20is%20a%20unique,portion%20of%20the%20config) [\[5\]](https://docs.langchain.com/oss/javascript/langgraph/persistence#:~:text=Time%20travel) Persistence - Docs by LangChain

https://docs.langchain.com/oss/javascript/langgraph/persistence

[\[6\]](https://www.assistant-ui.com/docs/runtimes/langgraph#:~:text=export%20const%20sendMessage%20%3D%20async,threadId) [\[7\]](https://www.assistant-ui.com/docs/runtimes/langgraph#:~:text=export%20function%20MyAssistant%28%29%20,threadId%3A%20externalId%2C%20messages%2C%20config) Getting Started | assistant-ui

https://www.assistant-ui.com/docs/runtimes/langgraph

[\[8\]](https://docs.langchain.com/oss/javascript/langchain/streaming/frontend#:~:text=Branching) [\[9\]](https://docs.langchain.com/oss/javascript/langchain/streaming/frontend#:~:text=%7B%2F,stream.setBranch%28branch%29%7D) [\[11\]](https://docs.langchain.com/oss/javascript/langchain/streaming/frontend#:~:text=%7Bmessage.type%20%3D%3D%3D%20,button%3E) Frontend - Docs by LangChain

https://docs.langchain.com/oss/javascript/langchain/streaming/frontend

[\[10\]](https://docs.langchain.com/oss/python/langchain/ui#:~:text=Agent%20Chat%20UI%20is%20a,adapted%20to%20your%20application%20needs) Agent Chat UI - Docs by LangChain

https://docs.langchain.com/oss/python/langchain/ui

[\[12\]](https://community.latenode.com/t/how-to-implement-message-editing-and-response-regeneration-features-with-langchain-or-langgraph/39411#:~:text=LangGraph%E2%80%99s%20checkpointing%20is%20exactly%20what,the%20state%20management%20for%20you) How to implement message editing and response regeneration features with langchain or langgraph? - langchain - Latenode Official Community

https://community.latenode.com/t/how-to-implement-message-editing-and-response-regeneration-features-with-langchain-or-langgraph/39411
