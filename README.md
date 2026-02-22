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
