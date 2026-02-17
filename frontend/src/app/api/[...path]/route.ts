import { NextRequest } from "next/server";

const getBackendUrl = () => process.env.BACKEND_URL || "http://localhost:8000";

async function proxyRequest(request: NextRequest) {
  const backendUrl = getBackendUrl();
  const path = request.nextUrl.pathname;
  const search = request.nextUrl.search;
  const url = `${backendUrl}${path}${search}`;

  const headers: Record<string, string> = {};
  request.headers.forEach((value, key) => {
    if (key !== "host" && key !== "connection") {
      headers[key] = value;
    }
  });

  const init: RequestInit = {
    method: request.method,
    headers,
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    const contentType = request.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      init.body = await request.text();
    } else if (contentType.includes("multipart/form-data")) {
      init.body = await request.arrayBuffer();
      // Preserve the original content-type with boundary
      headers["content-type"] = contentType;
    } else {
      init.body = await request.text();
    }
  }

  const backendRes = await fetch(url, init);

  const responseHeaders = new Headers();
  backendRes.headers.forEach((value, key) => {
    responseHeaders.set(key, value);
  });

  // Stream SSE responses
  const resContentType = backendRes.headers.get("content-type") || "";
  if (resContentType.includes("text/event-stream")) {
    responseHeaders.set("Cache-Control", "no-cache");
    responseHeaders.set("Connection", "keep-alive");
    responseHeaders.set("X-Accel-Buffering", "no");
    return new Response(backendRes.body, {
      status: backendRes.status,
      headers: responseHeaders,
    });
  }

  const body = await backendRes.arrayBuffer();
  return new Response(body, {
    status: backendRes.status,
    headers: responseHeaders,
  });
}

export async function GET(request: NextRequest) {
  return proxyRequest(request);
}

export async function POST(request: NextRequest) {
  return proxyRequest(request);
}

export async function PUT(request: NextRequest) {
  return proxyRequest(request);
}

export async function DELETE(request: NextRequest) {
  return proxyRequest(request);
}

export async function PATCH(request: NextRequest) {
  return proxyRequest(request);
}
