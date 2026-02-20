I have Next.js and Fast API application. Read the AGENTS.md first. I want you to implement Assistant UI - Local Runtime approeach to be integrated with Fast API backend which have langgraph and its tooling. 

For LocalRuntime integration you can crawl it in
https://www.assistant-ui.com/docs/runtimes/custom/local.mdx

Here's the feature i want to implement:
- A Welcome Page. It should be a centered text area with a welcome message. This has no context on the current chat conversation. When submitted, it should redirect to the chat page with a context of the current chat conversation thread.
- A chat page with threadId params like /chat/:threadId
- The platform should support:
  - LocalRuntime integration
  - Integration with Langgraph Fast API backend
  - A streaming output message from the frontend to the backend.
  - Streamed Tool Calling
  - Human In The Loop Tool Calling (bonus point if you can figure out to change the arguments of the tool called)
  - Message Branching
  - Message Editing


You can change anything in the frontend and backend, but not with the general langgraph flow. You can pick other infrastrcuture for the backend as needed, if you feel dont need the cosmosdb, you can do sqlite first. You can also use other databases like postgresql or mysql. You can save the a blob data in the backend on local storage. Yo
