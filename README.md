# Langgraph FastAPI Assistant UI

This repository contains an experimental integration of Langgraph with Fast API backend to the Assistant UI Backend.

This repository target is an integration with its baseline features such as:
1. Response Text Streaming
2. Tool Calling and Tool Calling Result
3. Message Editing
4. Message Regenerate
5. Message Branching
   

So far, we have 2 candidates that're "stable" for now.
- LocalRuntime (branch `exp/local-runtime`)  
  - Messages saved in a Assistant UI format
  - saved in a json format loaded in frontend
  - messages sent to backend as in the frontend format
  - messages is not checkpointed in the langgraph (invoked as stateless) 
- ExternalStoreRuntime (branch `exp/external-store-runtime-2`)
  - Messages saved in a Langgraph format
  - Saved in a Langgraph checkpointer
  - A command sent to the backend on what checkpoint and thread to invoke
  - Doing conversion on Langgraph Messages into Assistant UI format 


Other advance feature on top of the runtime
- Compaction build on LocalRuntime (branch `exp/local-runtime-compaction`)
   - Backend will check on the end of the stream what's total estimated token, next it will determine weather it needs compaction or not. If needs compaction backend will send a custom metadata `next_should_compact` to true.
   - Frontend will recieve this message metadata and will automatically invoke a new request with all the messages to compact. It will return a new a compacted AI Message to the frontend with metadata `compaction` to true.
   - Messages lifecycle to be sent to the backend is from messages of `compaction` set to true onward.
