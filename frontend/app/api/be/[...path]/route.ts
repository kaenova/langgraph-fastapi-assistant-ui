import { NextRequest, NextResponse } from "next/server";
// import { DataStreamResponse } from "assistant-stream";

/**
 * Get the backend URL from environment variables
 * @returns Backend URL string
 */
export async function getBackendUrl(): Promise<string> {
  return process.env.BACKEND_URL || "http://localhost:8000";
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const resolvedParams = await params;
  return handleProxyRequest(request, resolvedParams, "GET");
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const resolvedParams = await params;
  return handleProxyRequest(request, resolvedParams, "POST");
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const resolvedParams = await params;
  return handleProxyRequest(request, resolvedParams, "PUT");
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const resolvedParams = await params;
  return handleProxyRequest(request, resolvedParams, "DELETE");
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const resolvedParams = await params;
  return handleProxyRequest(request, resolvedParams, "PATCH");
}

async function handleProxyRequest(
  request: NextRequest,
  params: { path: string[] },
  method: string,
) {
  try {
    // Construct the backend path
    const backendPath = "/" + params.path.join("/");
    const backendUrl = await getBackendUrl();
    const fullBackendUrl = `${backendUrl}${backendPath}`;

    // Copy search parameters from the original request
    const url = new URL(request.url);
    const searchParams = url.searchParams;
    const finalUrl = searchParams.toString()
      ? `${fullBackendUrl}?${searchParams.toString()}`
      : fullBackendUrl;

    let body = undefined;
    if (["POST", "PUT", "PATCH"].includes(method)) {
      body = await request.arrayBuffer();
    }

    // Make the request to the backend
    const response = await fetch(finalUrl, {
      method: method,
      headers: request.headers,
      body: body,
    });

    // Create response headers, excluding some that shouldn't be forwarded
    const responseHeaders = new Headers();
    const headersToExclude = [
      "connection",
      "content-encoding",
      "content-length",
      "keep-alive",
      "proxy-authenticate",
      "proxy-authorization",
      "te",
      "trailers",
      "transfer-encoding",
      "upgrade",
    ];

    response.headers.forEach((value, key) => {
      if (!headersToExclude.includes(key.toLowerCase())) {
        responseHeaders.set(key, value);
      }
    });

    // Handle streaming responses
    const contentType = response.headers.get("content-type");
    const transferEncoding = response.headers.get("transfer-encoding");
    if (
      contentType?.includes("text/stream") ||
      contentType?.includes("application/stream") ||
      contentType?.includes("text/event-stream") ||
      transferEncoding === "chunked"
    ) {
      return new NextResponse(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });
    }

    // For non-streaming responses, get the response body
    const responseBody = await response.text();

    return new NextResponse(responseBody, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error("Proxy request failed:", error);

    return NextResponse.json(
      {
        error: "Proxy request failed",
        message: error instanceof Error ? error.message : "Unknown error",
      },
      { status: 500 },
    );
  }
}
