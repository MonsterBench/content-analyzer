import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await params;

  // Forward the multipart form data as-is to the backend
  const formData = await request.formData();

  const backendRes = await fetch(
    `${BACKEND_URL}/api/chat/${sessionId}/messages/upload`,
    {
      method: "POST",
      body: formData,
    }
  );

  if (!backendRes.ok) {
    return new Response(await backendRes.text(), { status: backendRes.status });
  }

  return new Response(backendRes.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
