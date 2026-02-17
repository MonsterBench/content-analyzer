"use client";

import { useEffect, useState, useRef, useCallback, use } from "react";
import {
  getCreator,
  getContent,
  triggerScrape,
  getScrapeJobs,
  addPlatform,
  removePlatform,
  updateSchedule,
  getKnowledgeStatus,
  generateKnowledge,
  getKnowledgeDetail,
  type Creator,
  type ContentItem,
  type ScrapeJob,
  type KnowledgeStatus,
  type KnowledgeProgress,
  type KnowledgeDetail,
} from "@/lib/api";

function PlatformBadge({ type }: { type: string }) {
  const colors =
    type === "instagram"
      ? "bg-pink-100 text-pink-800 dark:bg-pink-900 dark:text-pink-200"
      : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${colors}`}>
      {type === "instagram" ? "IG" : "YT"}
    </span>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

// --- Scrape Progress Panel ---

interface ScrapeProgress {
  stage: string;
  message: string;
  progress?: number;
  platform_type?: string;
  status?: string;
  new_items_found?: number;
}

function ScrapeProgressPanel({
  active,
  progress,
  elapsedSeconds,
}: {
  active: boolean;
  progress: ScrapeProgress | null;
  elapsedSeconds: number;
}) {
  if (!active) return null;

  const pct = progress?.progress ?? 0;
  const isDone = progress?.stage === "done";
  const isFailed = progress?.status === "failed";

  const stageIcon: Record<string, string> = {
    platform: "🔗",
    scraping: "📡",
    processing: "⚙️",
    transcribing: "🎤",
    done: isFailed ? "❌" : "✅",
  };

  const icon = stageIcon[progress?.stage || ""] || "⏳";

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
  };

  return (
    <div
      className={`bg-[var(--card)] border rounded-lg p-5 space-y-3 transition-colors ${
        isDone
          ? isFailed
            ? "border-red-400"
            : "border-green-400"
          : "border-[var(--primary)]"
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {!isDone && (
            <svg
              className="animate-spin h-4 w-4 text-[var(--primary)]"
              viewBox="0 0 24 24"
              fill="none"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
          )}
          <h3 className="font-semibold text-sm">
            {isDone ? (isFailed ? "Scrape Failed" : "Scrape Complete") : "Scraping in Progress"}
          </h3>
        </div>
        <span className="text-xs text-[var(--muted-foreground)]">
          {formatTime(elapsedSeconds)}
        </span>
      </div>

      {/* Progress bar */}
      <div className="w-full bg-[var(--muted)] rounded-full h-2.5 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ease-out ${
            isDone
              ? isFailed
                ? "bg-red-500"
                : "bg-green-500"
              : "bg-[var(--primary)]"
          }`}
          style={{
            width: isDone ? "100%" : pct > 0 ? `${Math.round(pct * 100)}%` : undefined,
            // Indeterminate animation when no progress value
            ...(pct === 0 && !isDone
              ? { width: "30%", animation: "indeterminate 1.5s ease-in-out infinite" }
              : {}),
          }}
        />
      </div>

      {/* Status message */}
      <div className="flex items-center gap-2">
        <span>{icon}</span>
        <p className="text-sm text-[var(--muted-foreground)]">
          {progress?.message || "Preparing..."}
        </p>
      </div>

      {/* Done stats */}
      {isDone && progress.new_items_found !== undefined && (
        <p className="text-sm font-medium">
          {progress.new_items_found} new items found
        </p>
      )}
    </div>
  );
}

// --- Knowledge Panel ---

function KnowledgePanel({ creatorId }: { creatorId: number }) {
  const [status, setStatus] = useState<KnowledgeStatus | null>(null);
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState<KnowledgeProgress | null>(null);
  const [expandedType, setExpandedType] = useState<string | null>(null);
  const [detail, setDetail] = useState<KnowledgeDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const timerRef2 = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const s = await getKnowledgeStatus(creatorId);
      setStatus(s);
    } catch (err) {
      console.error("Failed to load knowledge status:", err);
    }
  }, [creatorId]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    return () => {
      if (timerRef2.current) clearInterval(timerRef2.current);
    };
  }, []);

  const handleGenerate = async () => {
    setGenerating(true);
    setProgress({ stage: "starting", message: "Starting knowledge generation..." });
    setElapsed(0);
    timerRef2.current = setInterval(() => setElapsed((p) => p + 1), 1000);

    try {
      await generateKnowledge(creatorId, (event) => {
        setProgress(event);
        if (event.stage === "done") {
          setGenerating(false);
          if (timerRef2.current) {
            clearInterval(timerRef2.current);
            timerRef2.current = null;
          }
          loadStatus();
        }
      });
    } catch (err) {
      console.error(err);
      setGenerating(false);
      setProgress({ stage: "error", message: "Generation failed. Check server logs." });
      if (timerRef2.current) {
        clearInterval(timerRef2.current);
        timerRef2.current = null;
      }
    }
  };

  const toggleDetail = async (type: string) => {
    if (expandedType === type) {
      setExpandedType(null);
      setDetail(null);
      return;
    }
    setExpandedType(type);
    setLoadingDetail(true);
    try {
      const d = await getKnowledgeDetail(creatorId, type);
      setDetail(d);
    } catch {
      setDetail(null);
    }
    setLoadingDetail(false);
  };

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
  };

  const pct = progress?.progress ?? 0;
  const knowledgeTypeLabels: Record<string, string> = {
    profile: "Creator Profile",
    topics: "Topic Clusters",
    style: "Style Analysis",
  };

  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-semibold">AI Knowledge Base</h2>
          {status && (
            <p className="text-xs text-[var(--muted-foreground)] mt-0.5">
              {status.summarized_items}/{status.total_items} videos summarized
              {status.has_knowledge && ` | ${status.entries.length} knowledge entries`}
            </p>
          )}
        </div>
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="px-3 py-1.5 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-md text-sm font-medium hover:opacity-90 disabled:opacity-50"
        >
          {generating ? "Generating..." : status?.has_knowledge ? "Regenerate" : "Generate Knowledge"}
        </button>
      </div>

      {/* Progress bar during generation */}
      {(generating || progress?.stage === "error") && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-[var(--muted-foreground)]">
            <span>{progress?.message || "Preparing..."}</span>
            {generating && <span>{formatTime(elapsed)}</span>}
          </div>
          <div className="w-full bg-[var(--muted)] rounded-full h-2 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ease-out ${
                progress?.stage === "done"
                  ? "bg-green-500"
                  : progress?.stage === "error"
                  ? "bg-red-500"
                  : "bg-[var(--primary)]"
              }`}
              style={{
                width:
                  progress?.stage === "done"
                    ? "100%"
                    : pct > 0
                    ? `${Math.round(pct * 100)}%`
                    : undefined,
                ...(pct === 0 && generating
                  ? { width: "30%", animation: "indeterminate 1.5s ease-in-out infinite" }
                  : {}),
              }}
            />
          </div>
        </div>
      )}

      {/* Knowledge entries */}
      {status?.entries && status.entries.length > 0 && (
        <div className="space-y-2">
          {status.entries.map((entry) => (
            <div key={entry.id} className="border border-[var(--border)] rounded-md">
              <button
                onClick={() => toggleDetail(entry.type)}
                className="w-full flex items-center justify-between p-3 text-left hover:bg-[var(--muted)] rounded-md"
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">
                    {knowledgeTypeLabels[entry.type] || entry.type}
                  </span>
                  <span className="text-xs text-[var(--muted-foreground)]">
                    v{entry.version} | {new Date(entry.generated_at).toLocaleDateString()}
                  </span>
                </div>
                <span className="text-xs text-[var(--muted-foreground)]">
                  {expandedType === entry.type ? "▼" : "▶"}
                </span>
              </button>
              {expandedType === entry.type && (
                <div className="px-3 pb-3">
                  {loadingDetail ? (
                    <p className="text-xs text-[var(--muted-foreground)]">Loading...</p>
                  ) : detail ? (
                    <div className="text-sm whitespace-pre-line bg-[var(--background)] p-3 rounded-md max-h-64 overflow-y-auto">
                      {detail.content}
                    </div>
                  ) : (
                    <p className="text-xs text-[var(--muted-foreground)]">Failed to load</p>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Main Page ---

export default function CreatorDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const creatorId = parseInt(id);

  const [creator, setCreator] = useState<Creator | null>(null);
  const [content, setContent] = useState<ContentItem[]>([]);
  const [jobs, setJobs] = useState<ScrapeJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [scraping, setScraping] = useState(false);
  const [scrapeProgress, setScrapeProgress] = useState<ScrapeProgress | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [sortBy, setSortBy] = useState("timestamp");
  const [sortOrder, setSortOrder] = useState("desc");
  const [platformFilter, setPlatformFilter] = useState("");

  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Add platform form
  const [showAddPlatform, setShowAddPlatform] = useState(false);
  const [newPlatformType, setNewPlatformType] = useState<"instagram" | "youtube">("instagram");
  const [newPlatformHandle, setNewPlatformHandle] = useState("");

  const load = useCallback(async () => {
    try {
      const [c, items, j] = await Promise.all([
        getCreator(creatorId),
        getContent(creatorId, {
          sort_by: sortBy,
          sort_order: sortOrder,
          platform_type: platformFilter || undefined,
          limit: 500,
        }),
        getScrapeJobs(creatorId),
      ]);
      setCreator(c);
      setContent(items);
      setJobs(j);
    } catch (err) {
      console.error(err);
    }
    setLoading(false);
  }, [creatorId, sortBy, sortOrder, platformFilter]);

  useEffect(() => {
    load();
  }, [load]);

  // Clean up WebSocket and timer on unmount
  useEffect(() => {
    return () => {
      wsRef.current?.close();
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const connectWebSocket = (jobId: number) => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const ws = new WebSocket(`${protocol}//${host}/ws/scrape/${jobId}`);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const data: ScrapeProgress = JSON.parse(event.data);
        setScrapeProgress(data);

        if (data.stage === "done") {
          setScraping(false);
          if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
          }
          ws.close();
          // Reload data after a short delay
          setTimeout(() => load(), 1000);
        }
      } catch {}
    };

    ws.onerror = () => {
      // Fall back to polling if WS fails
      ws.close();
    };

    ws.onclose = () => {
      wsRef.current = null;
    };
  };

  const handleScrape = async () => {
    setScraping(true);
    setScrapeProgress({ stage: "preparing", message: "Starting scrape..." });
    setElapsedSeconds(0);

    // Start elapsed timer
    timerRef.current = setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);

    try {
      const job = await triggerScrape(creatorId, { max_items: 0 });

      // Connect WebSocket for live progress
      connectWebSocket(job.id);

      // Also poll as fallback in case WebSocket doesn't connect
      const poll = setInterval(async () => {
        const updatedJobs = await getScrapeJobs(creatorId);
        setJobs(updatedJobs);
        const current = updatedJobs.find((j) => j.id === job.id);
        if (current && (current.status === "completed" || current.status === "failed")) {
          clearInterval(poll);
          // If WebSocket didn't already handle it
          if (scraping) {
            setScraping(false);
            if (timerRef.current) {
              clearInterval(timerRef.current);
              timerRef.current = null;
            }
            setScrapeProgress({
              stage: "done",
              status: current.status,
              message:
                current.status === "completed"
                  ? `Done! ${current.new_items_found} new items found.`
                  : `Failed: ${current.error_message || "Unknown error"}`,
              new_items_found: current.new_items_found,
              progress: 1,
            });
            load();
          }
        }
      }, 3000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setScraping(false);
      setScrapeProgress({
        stage: "done",
        status: "failed",
        message: `Failed to start: ${msg}`,
      });
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
  };

  const handleAddPlatform = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPlatformHandle.trim()) return;
    await addPlatform(creatorId, {
      type: newPlatformType,
      handle: newPlatformHandle.trim(),
    });
    setNewPlatformHandle("");
    setShowAddPlatform(false);
    load();
  };

  const handleRemovePlatform = async (platformId: number) => {
    if (!confirm("Remove this platform and all its content?")) return;
    await removePlatform(creatorId, platformId);
    load();
  };

  const handleScheduleChange = async (frequency: string) => {
    await updateSchedule(creatorId, frequency);
    load();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-[var(--muted-foreground)]">Loading...</p>
      </div>
    );
  }

  if (!creator) {
    return <p className="text-[var(--muted-foreground)]">Creator not found.</p>;
  }

  return (
    <div className="space-y-6">
      {/* Indeterminate animation keyframes */}
      <style>{`
        @keyframes indeterminate {
          0% { margin-left: 0; }
          50% { margin-left: 70%; }
          100% { margin-left: 0; }
        }
      `}</style>

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold">{creator.name}</h1>
          <p className="text-[var(--muted-foreground)] text-sm mt-1">
            {creator.total_content} content items across{" "}
            {creator.platforms.length} platform(s)
          </p>
        </div>
        <div className="flex gap-2">
          <a
            href={`/chat?creator=${creator.id}`}
            className="px-4 py-2 border border-[var(--border)] rounded-md text-sm hover:bg-[var(--muted)]"
          >
            Chat
          </a>
          <button
            onClick={handleScrape}
            disabled={scraping}
            className="px-4 py-2 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-md text-sm font-medium hover:opacity-90 disabled:opacity-50"
          >
            {scraping ? "Scraping..." : "Scrape Now"}
          </button>
        </div>
      </div>

      {/* Live Scrape Progress */}
      <ScrapeProgressPanel
        active={scraping || scrapeProgress?.stage === "done"}
        progress={scrapeProgress}
        elapsedSeconds={elapsedSeconds}
      />

      {/* Platforms */}
      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold">Platforms</h2>
          <button
            onClick={() => setShowAddPlatform(!showAddPlatform)}
            className="text-sm text-[var(--primary)] hover:underline"
          >
            {showAddPlatform ? "Cancel" : "+ Add Platform"}
          </button>
        </div>

        {showAddPlatform && (
          <form onSubmit={handleAddPlatform} className="flex gap-2 mb-3">
            <select
              value={newPlatformType}
              onChange={(e) => setNewPlatformType(e.target.value as "instagram" | "youtube")}
              className="px-2 py-1.5 bg-[var(--background)] border border-[var(--border)] rounded-md text-sm"
            >
              <option value="instagram">Instagram</option>
              <option value="youtube">YouTube</option>
            </select>
            <input
              type="text"
              value={newPlatformHandle}
              onChange={(e) => setNewPlatformHandle(e.target.value)}
              placeholder="@handle or URL"
              className="flex-1 px-3 py-1.5 bg-[var(--background)] border border-[var(--border)] rounded-md text-sm"
            />
            <button
              type="submit"
              className="px-3 py-1.5 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-md text-sm"
            >
              Add
            </button>
          </form>
        )}

        <div className="space-y-2">
          {creator.platforms.map((p) => (
            <div
              key={p.id}
              className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 sm:gap-2 py-2 border-b border-[var(--border)] last:border-0"
            >
              <div className="flex items-center gap-2">
                <PlatformBadge type={p.type} />
                <span className="text-sm font-medium">@{p.handle}</span>
                <span className="text-xs text-[var(--muted-foreground)]">
                  {p.content_count} items
                </span>
              </div>
              <div className="flex items-center gap-2">
                {p.last_scraped_at && (
                  <span className="text-xs text-[var(--muted-foreground)]">
                    Last scraped:{" "}
                    {new Date(p.last_scraped_at).toLocaleDateString()}
                  </span>
                )}
                <button
                  onClick={() => handleRemovePlatform(p.id)}
                  className="text-xs text-[var(--destructive)] hover:underline"
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* Schedule */}
        <div className="mt-4 pt-3 border-t border-[var(--border)]">
          <label className="text-sm font-medium mr-2">Schedule:</label>
          <select
            value={creator.schedule_frequency}
            onChange={(e) => handleScheduleChange(e.target.value)}
            className="px-2 py-1 bg-[var(--background)] border border-[var(--border)] rounded-md text-sm"
          >
            <option value="manual">Manual only</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
          </select>
        </div>
      </div>

      {/* Summary */}
      {creator.summary && (
        <div className="bg-[var(--accent)] border border-[var(--border)] rounded-lg p-5">
          <h2 className="font-semibold mb-2">AI Summary</h2>
          <p className="text-sm whitespace-pre-line">{creator.summary}</p>
        </div>
      )}

      {/* Knowledge Panel */}
      <KnowledgePanel creatorId={creatorId} />

      {/* Recent Scrape Jobs */}
      {jobs.length > 0 && (
        <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5">
          <h2 className="font-semibold mb-3">Recent Scrape Jobs</h2>
          <div className="space-y-1">
            {jobs.slice(0, 5).map((job) => (
              <div
                key={job.id}
                className="flex items-center justify-between text-sm py-1"
              >
                <span>
                  <span
                    className={`inline-block w-2 h-2 rounded-full mr-2 ${
                      job.status === "completed"
                        ? "bg-green-500"
                        : job.status === "running"
                        ? "bg-yellow-500 animate-pulse"
                        : job.status === "failed"
                        ? "bg-red-500"
                        : "bg-gray-500"
                    }`}
                  />
                  {job.status}
                </span>
                <span className="text-[var(--muted-foreground)]">
                  {job.new_items_found} new items |{" "}
                  {job.started_at
                    ? new Date(job.started_at).toLocaleString()
                    : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Content Table */}
      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg overflow-hidden">
        <div className="p-4 border-b border-[var(--border)] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <h2 className="font-semibold">Content</h2>
          <div className="flex gap-2 flex-wrap">
            <select
              value={platformFilter}
              onChange={(e) => setPlatformFilter(e.target.value)}
              className="px-2 py-1 bg-[var(--background)] border border-[var(--border)] rounded-md text-xs"
            >
              <option value="">All platforms</option>
              <option value="instagram">Instagram</option>
              <option value="youtube">YouTube</option>
            </select>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="px-2 py-1 bg-[var(--background)] border border-[var(--border)] rounded-md text-xs"
            >
              <option value="timestamp">Date</option>
              <option value="views">Views</option>
              <option value="likes">Likes</option>
              <option value="comments">Comments</option>
            </select>
            <select
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value)}
              className="px-2 py-1 bg-[var(--background)] border border-[var(--border)] rounded-md text-xs"
            >
              <option value="desc">Desc</option>
              <option value="asc">Asc</option>
            </select>
          </div>
        </div>

        {content.length === 0 ? (
          <p className="p-6 text-center text-sm text-[var(--muted-foreground)]">
            No content yet. Click &quot;Scrape Now&quot; to fetch content.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-[var(--muted)]">
                <tr>
                  <th className="text-left p-3 font-medium">Platform</th>
                  <th className="text-left p-3 font-medium">Title / ID</th>
                  <th className="text-right p-3 font-medium">Views</th>
                  <th className="text-right p-3 font-medium">Likes</th>
                  <th className="text-right p-3 font-medium">Comments</th>
                  <th className="text-left p-3 font-medium">Date</th>
                </tr>
              </thead>
              <tbody>
                {content.map((item) => (
                  <tr
                    key={item.id}
                    className="border-t border-[var(--border)] hover:bg-[var(--muted)]"
                  >
                    <td className="p-3">
                      <PlatformBadge type={item.platform_type} />
                    </td>
                    <td className="p-3">
                      <a
                        href={item.url || "#"}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hover:text-[var(--primary)] hover:underline"
                      >
                        {item.title || item.external_id}
                      </a>
                      {item.caption && (
                        <p className="text-xs text-[var(--muted-foreground)] mt-0.5 line-clamp-1">
                          {item.caption.slice(0, 80)}
                        </p>
                      )}
                    </td>
                    <td className="p-3 text-right">{formatNumber(item.views)}</td>
                    <td className="p-3 text-right">{formatNumber(item.likes)}</td>
                    <td className="p-3 text-right">
                      {formatNumber(item.comments)}
                    </td>
                    <td className="p-3 text-[var(--muted-foreground)]">
                      {item.timestamp
                        ? new Date(item.timestamp).toLocaleDateString()
                        : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
