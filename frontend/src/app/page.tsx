"use client";

import { useEffect, useState } from "react";
import { getCreators, type Creator } from "@/lib/api";

function StatCard({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5">
      <p className="text-sm text-[var(--muted-foreground)]">{label}</p>
      <p className="text-2xl font-bold mt-1">{String(value)}</p>
    </div>
  );
}

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

export default function Dashboard() {
  const [creators, setCreators] = useState<Creator[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getCreators()
      .then(setCreators)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const totalContent = creators.reduce((s, c) => s + c.total_content, 0);
  const totalPlatforms = creators.reduce(
    (s, c) => s + c.platforms.length,
    0
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-[var(--muted-foreground)]">Loading...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold">Dashboard</h1>
        <p className="text-[var(--muted-foreground)] text-sm mt-1">
          Overview of all tracked creators and content
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Creators" value={creators.length} />
        <StatCard label="Platforms Linked" value={totalPlatforms} />
        <StatCard
          label="Content Items"
          value={totalContent.toLocaleString()}
        />
        <StatCard
          label="Last Updated"
          value={
            creators.length > 0 && creators[0].last_scraped_at
              ? new Date(creators[0].last_scraped_at).toLocaleDateString()
              : "Never"
          }
        />
      </div>

      <div>
        <h2 className="text-lg font-semibold mb-3">Creators</h2>
        {creators.length === 0 ? (
          <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-8 text-center">
            <p className="text-[var(--muted-foreground)]">
              No creators added yet.
            </p>
            <a
              href="/creators"
              className="inline-block mt-3 px-4 py-2 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-md text-sm font-medium hover:opacity-90"
            >
              Add Creator
            </a>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {creators.map((creator) => (
              <a
                key={creator.id}
                href={`/creators/${creator.id}`}
                className="block bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 hover:border-[var(--primary)] transition-colors"
              >
                <div className="flex items-start justify-between">
                  <h3 className="font-semibold">{creator.name}</h3>
                  <span className="text-xs text-[var(--muted-foreground)]">
                    {creator.total_content} items
                  </span>
                </div>
                <div className="flex gap-2 mt-2">
                  {creator.platforms.map((p) => (
                    <div key={p.id} className="flex items-center gap-1">
                      <PlatformBadge type={p.type} />
                      <span className="text-xs text-[var(--muted-foreground)]">
                        @{p.handle}
                      </span>
                    </div>
                  ))}
                </div>
                {creator.last_scraped_at && (
                  <p className="text-xs text-[var(--muted-foreground)] mt-3">
                    Last scraped:{" "}
                    {new Date(creator.last_scraped_at).toLocaleDateString()}
                  </p>
                )}
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
