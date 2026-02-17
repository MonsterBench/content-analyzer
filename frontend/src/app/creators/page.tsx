"use client";

import { useEffect, useState } from "react";
import {
  getCreators,
  createCreator,
  deleteCreator,
  type Creator,
} from "@/lib/api";

interface PlatformInput {
  type: "instagram" | "youtube";
  handle: string;
}

export default function CreatorsPage() {
  const [creators, setCreators] = useState<Creator[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [schedule, setSchedule] = useState("manual");
  const [platforms, setPlatforms] = useState<PlatformInput[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const load = () => {
    getCreators()
      .then(setCreators)
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const addPlatformInput = (type: "instagram" | "youtube") => {
    setPlatforms([...platforms, { type, handle: "" }]);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    try {
      await createCreator({
        name: name.trim(),
        schedule_frequency: schedule,
        platforms: platforms
          .filter((p) => p.handle.trim())
          .map((p) => ({ type: p.type, handle: p.handle.trim() })),
      });
      setName("");
      setSchedule("manual");
      setPlatforms([]);
      setShowForm(false);
      load();
    } catch (err) {
      console.error(err);
      alert("Failed to create creator");
    }
    setSubmitting(false);
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this creator and all their data?")) return;
    await deleteCreator(id);
    load();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-[var(--muted-foreground)]">Loading...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold">Creators</h1>
          <p className="text-[var(--muted-foreground)] text-sm mt-1">
            Manage creators and their platform links
          </p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-md text-sm font-medium hover:opacity-90 self-start sm:self-auto"
        >
          {showForm ? "Cancel" : "Add Creator"}
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-6 space-y-4"
        >
          <div>
            <label className="block text-sm font-medium mb-1">
              Creator Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., William Perry III"
              className="w-full px-3 py-2 bg-[var(--background)] border border-[var(--border)] rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">
              Monitoring Schedule
            </label>
            <select
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              className="w-full px-3 py-2 bg-[var(--background)] border border-[var(--border)] rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
            >
              <option value="manual">Manual only</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">Platforms</label>
            <div className="space-y-2">
              {platforms.map((p, i) => (
                <div key={i} className="flex gap-2 items-center">
                  <span
                    className={`text-xs px-2 py-1 rounded-full font-medium ${
                      p.type === "instagram"
                        ? "bg-pink-100 text-pink-800 dark:bg-pink-900 dark:text-pink-200"
                        : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
                    }`}
                  >
                    {p.type === "instagram" ? "IG" : "YT"}
                  </span>
                  <input
                    type="text"
                    value={p.handle}
                    onChange={(e) => {
                      const updated = [...platforms];
                      updated[i].handle = e.target.value;
                      setPlatforms(updated);
                    }}
                    placeholder={
                      p.type === "instagram"
                        ? "@username"
                        : "@channel or URL"
                    }
                    className="flex-1 px-3 py-2 bg-[var(--background)] border border-[var(--border)] rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                  />
                  <button
                    type="button"
                    onClick={() =>
                      setPlatforms(platforms.filter((_, j) => j !== i))
                    }
                    className="text-[var(--destructive)] text-sm hover:underline"
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
            <div className="flex gap-2 mt-2">
              <button
                type="button"
                onClick={() => addPlatformInput("instagram")}
                className="text-sm px-3 py-1 border border-[var(--border)] rounded-md hover:bg-[var(--muted)]"
              >
                + Instagram
              </button>
              <button
                type="button"
                onClick={() => addPlatformInput("youtube")}
                className="text-sm px-3 py-1 border border-[var(--border)] rounded-md hover:bg-[var(--muted)]"
              >
                + YouTube
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={submitting || !name.trim()}
            className="px-4 py-2 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-md text-sm font-medium hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? "Creating..." : "Create Creator"}
          </button>
        </form>
      )}

      <div className="space-y-3">
        {creators.map((creator) => (
          <div
            key={creator.id}
            className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
          >
            <div className="min-w-0">
              <a
                href={`/creators/${creator.id}`}
                className="font-semibold hover:text-[var(--primary)]"
              >
                {creator.name}
              </a>
              <div className="flex flex-wrap gap-2 mt-1">
                {creator.platforms.map((p) => (
                  <span
                    key={p.id}
                    className="text-xs text-[var(--muted-foreground)]"
                  >
                    {p.type === "instagram" ? "IG" : "YT"}: @{p.handle} (
                    {p.content_count})
                  </span>
                ))}
              </div>
              <p className="text-xs text-[var(--muted-foreground)] mt-1">
                {creator.total_content} total items | Schedule:{" "}
                {creator.schedule_frequency}
                {creator.last_scraped_at &&
                  ` | Last scraped: ${new Date(
                    creator.last_scraped_at
                  ).toLocaleDateString()}`}
              </p>
            </div>
            <div className="flex gap-2 flex-shrink-0">
              <a
                href={`/creators/${creator.id}`}
                className="px-3 py-1.5 text-sm border border-[var(--border)] rounded-md hover:bg-[var(--muted)]"
              >
                View
              </a>
              <button
                onClick={() => handleDelete(creator.id)}
                className="px-3 py-1.5 text-sm text-[var(--destructive)] border border-[var(--border)] rounded-md hover:bg-red-50 dark:hover:bg-red-950"
              >
                Delete
              </button>
            </div>
          </div>
        ))}

        {creators.length === 0 && (
          <p className="text-center text-[var(--muted-foreground)] py-8">
            No creators yet. Click &quot;Add Creator&quot; to get started.
          </p>
        )}
      </div>
    </div>
  );
}
