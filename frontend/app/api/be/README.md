# Backend API Proxy

This directory contains the API proxy route that forwards requests to your backend server.

## How it works

The proxy route is located at `/api/be/[...path]/route.ts` and handles all HTTP methods (GET, POST, PUT, DELETE, PATCH).

### URL Pattern
- **Frontend URL**: `/api/be/{backendPath}`
- **Backend URL**: `/{backendPath}`

### Example Usage

If your backend has an endpoint `/users/profile`, you can access it through the proxy at:
```
/api/be/users/profile
```

### Features

1. **Method Forwarding**: All HTTP methods are supported and forwarded to the backend
2. **Header Forwarding**: Relevant headers from the client request are forwarded
3. **Authentication**: Adds `UserID` header with the authenticated user's ID (if logged in)
4. **Backend Authentication**: Automatically includes backend API credentials via Basic Auth
5. **Query Parameters**: Search parameters are preserved and forwarded
6. **Request Body**: POST/PUT/PATCH request bodies are forwarded
7. **Response Streaming**: Supports streaming responses from the backend
8. **Error Handling**: Returns appropriate error responses if the proxy fails


### Environment Variables Required

- `BACKEND_URL`: The base URL of your backend server (defaults to `http://localhost:8000`)


### Example Frontend Usage

```typescript
// Instead of calling your backend directly:
// fetch('http://backend.com/api/users')

// Use the proxy:
fetch('/api/be/users')
```

The proxy will automatically:
1. Extract the user ID from the NextAuth session
2. Add the `UserID` header to the backend request
3. Include backend authentication credentials
4. Forward the request to your backend server
