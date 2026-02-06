# Repository Condition

This is the documentation on current repository condition.

It has 2 main folders.
- /backend: hosting the FastAPI python with the langgraph
- /frontend: hosting the Next.js application with the Assistant UI

# Backend

Backend has minimal FastApi application. Currently it only implement the attachment routes.
I have prepare the graph that you can import via function `get_graph()` in the `/backend/agent/graph.py`

I suggest you didn't change the graph except implementing the human in the loop function.

You can also add more simple tools with hardcoded return to test.

All python backend routes is implemented in the `/backend/routes` files.


# Frontend

Frontend has minimal Assistant-UI library application.

Currently it implement basic chat functionality through AI SDK that uses next js backend api on the `/frontend/app/api/chat/route.ts`

If you want to send api to our python backend api, use the proxy in the `/frontend/app/api/be/...`
