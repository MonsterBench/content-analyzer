const API_BASE = "/api";

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const error = await res.text();
    throw new Error(`API error ${res.status}: ${error}`);
  }
  return res.json();
}

// --- Types ---

export interface Platform {
  id: number;
  type: "instagram" | "youtube";
  handle: string;
  url: string | null;
  last_scraped_at: string | null;
  content_count: number;
}

export interface Creator {
  id: number;
  name: string;
  summary: string | null;
  schedule_frequency: string;
  last_scraped_at: string | null;
  created_at: string;
  platforms: Platform[];
  total_content: number;
}

export interface ContentItem {
  id: number;
  platform_id: number;
  type: string;
  external_id: string;
  url: string | null;
  title: string | null;
  caption: string | null;
  transcript: string | null;
  transcript_source: string | null;
  timestamp: string | null;
  likes: number;
  comments: number;
  views: number;
  duration: number;
  tags: string | null;
  platform_type: string;
  platform_handle: string;
}

export interface ScrapeJob {
  id: number;
  creator_id: number;
  status: string;
  new_items_found: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface ChatSession {
  id: number;
  creator_id: number;
  title: string;
  created_at: string;
  message_count: number;
}

export interface ChatMessage {
  id: number;
  session_id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface CompareResult {
  creator_id: number;
  name: string;
  platforms: { type: string; handle: string }[];
  total_content: number;
  avg_views: number;
  avg_likes: number;
  avg_comments: number;
  total_views: number;
  summary: string | null;
}

// --- Creators ---

export async function getCreators(): Promise<Creator[]> {
  return fetchJSON("/creators");
}

export async function getCreator(id: number): Promise<Creator> {
  return fetchJSON(`/creators/${id}`);
}

export async function createCreator(data: {
  name: string;
  schedule_frequency?: string;
  platforms?: { type: string; handle: string; url?: string }[];
}): Promise<Creator> {
  return fetchJSON("/creators", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateCreator(
  id: number,
  data: { name?: string; schedule_frequency?: string }
): Promise<Creator> {
  return fetchJSON(`/creators/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteCreator(id: number): Promise<void> {
  await fetch(`${API_BASE}/creators/${id}`, { method: "DELETE" });
}

export async function addPlatform(
  creatorId: number,
  data: { type: string; handle: string; url?: string }
): Promise<Platform> {
  return fetchJSON(`/creators/${creatorId}/platforms`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function removePlatform(
  creatorId: number,
  platformId: number
): Promise<void> {
  await fetch(`${API_BASE}/creators/${creatorId}/platforms/${platformId}`, {
    method: "DELETE",
  });
}

// --- Content ---

export async function getContent(
  creatorId: number,
  params?: {
    platform_type?: string;
    sort_by?: string;
    sort_order?: string;
    limit?: number;
    offset?: number;
  }
): Promise<ContentItem[]> {
  const searchParams = new URLSearchParams();
  if (params?.platform_type) searchParams.set("platform_type", params.platform_type);
  if (params?.sort_by) searchParams.set("sort_by", params.sort_by);
  if (params?.sort_order) searchParams.set("sort_order", params.sort_order);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  return fetchJSON(`/creators/${creatorId}/content${qs ? `?${qs}` : ""}`);
}

// --- Scraping ---

export async function triggerScrape(
  creatorId: number,
  options?: { transcribe?: boolean; max_items?: number }
): Promise<ScrapeJob> {
  return fetchJSON(`/creators/${creatorId}/scrape`, {
    method: "POST",
    body: JSON.stringify(options || {}),
  });
}

export async function getScrapeJobs(creatorId: number): Promise<ScrapeJob[]> {
  return fetchJSON(`/creators/${creatorId}/scrape/jobs`);
}

// --- Chat ---

export async function createChatSession(
  creatorId: number,
  title?: string
): Promise<ChatSession> {
  return fetchJSON(`/creators/${creatorId}/chat`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export async function getChatSessions(
  creatorId: number
): Promise<ChatSession[]> {
  return fetchJSON(`/creators/${creatorId}/chat/sessions`);
}

export async function getChatMessages(
  sessionId: number
): Promise<ChatMessage[]> {
  return fetchJSON(`/chat/${sessionId}/messages`);
}

export async function sendMessage(
  sessionId: number,
  content: string,
  onChunk: (text: string) => void
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`/api/chat/${sessionId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
  } catch (err) {
    throw new Error(`Network error: could not reach the server. Check your connection.`);
  }

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Server error (${res.status}): ${body || "Unknown error"}`);
  }
  if (!res.body) return;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === "text") {
              onChunk(data.content);
            }
          } catch {}
        }
      }
    }
  } catch (err) {
    // If we already got some chunks, don't throw — just stop gracefully
    if (buffer.length === 0) {
      throw new Error(`Connection lost during streaming. Please try again.`);
    }
  }
}

export async function sendMessageWithFiles(
  sessionId: number,
  content: string,
  files: File[],
  onChunk: (text: string) => void
): Promise<void> {
  const formData = new FormData();
  formData.append("content", content);
  for (const file of files) {
    formData.append("files", file);
  }

  let res: Response;
  try {
    res = await fetch(`/api/chat/${sessionId}/messages/upload`, {
      method: "POST",
      body: formData,
    });
  } catch (err) {
    throw new Error("Network error: could not reach the server. Check your connection.");
  }

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Server error (${res.status}): ${body || "Unknown error"}`);
  }
  if (!res.body) return;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === "text") {
              onChunk(data.content);
            }
          } catch {}
        }
      }
    }
  } catch (err) {
    if (buffer.length === 0) {
      throw new Error("Connection lost during streaming. Please try again.");
    }
  }
}

export async function deleteChatSession(sessionId: number): Promise<void> {
  await fetch(`${API_BASE}/chat/${sessionId}`, { method: "DELETE" });
}

// --- Compare ---

export async function compareCreators(
  creatorIds: number[]
): Promise<CompareResult[]> {
  return fetchJSON(`/compare?creator_ids=${creatorIds.join(",")}`);
}

// --- Knowledge ---

export interface KnowledgeEntry {
  id: number;
  type: string;
  generated_at: string;
  version: number;
  content_preview: string;
}

export interface KnowledgeStatus {
  has_knowledge: boolean;
  total_items: number;
  summarized_items: number;
  entries: KnowledgeEntry[];
}

export interface KnowledgeDetail {
  id: number;
  type: string;
  content: string;
  generated_at: string;
  version: number;
}

export interface KnowledgeProgress {
  stage: string;
  message: string;
  progress?: number;
}

export async function getKnowledgeStatus(
  creatorId: number
): Promise<KnowledgeStatus> {
  return fetchJSON(`/creators/${creatorId}/knowledge`);
}

export async function getKnowledgeDetail(
  creatorId: number,
  type: string
): Promise<KnowledgeDetail> {
  return fetchJSON(`/creators/${creatorId}/knowledge/${type}`);
}

export async function generateKnowledge(
  creatorId: number,
  onProgress: (event: KnowledgeProgress) => void
): Promise<void> {
  const res = await fetch(`${API_BASE}/creators/${creatorId}/knowledge/generate`, {
    method: "POST",
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Server error (${res.status}): ${body || "Unknown error"}`);
  }
  if (!res.body) return;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop() || "";

    for (const chunk of lines) {
      if (chunk.startsWith("data: ")) {
        try {
          const data: KnowledgeProgress = JSON.parse(chunk.slice(6));
          onProgress(data);
        } catch {}
      }
    }
  }
}

// --- Schedule ---

export async function updateSchedule(
  creatorId: number,
  frequency: string
): Promise<void> {
  await fetchJSON(`/schedule/creators/${creatorId}`, {
    method: "PUT",
    body: JSON.stringify({ frequency }),
  });
}
