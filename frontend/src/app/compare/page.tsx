"use client";

import { useEffect, useState } from "react";
import {
  getCreators,
  compareCreators,
  type Creator,
  type CompareResult,
} from "@/lib/api";

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

function StatRow({
  label,
  values,
}: {
  label: string;
  values: (number | string)[];
}) {
  const nums = values.map((v) => (typeof v === "number" ? v : 0));
  const max = Math.max(...nums);

  return (
    <tr className="border-t border-[var(--border)]">
      <td className="p-3 text-sm font-medium">{label}</td>
      {values.map((v, i) => {
        const isMax = typeof v === "number" && v === max && max > 0;
        return (
          <td
            key={i}
            className={`p-3 text-sm text-right ${
              isMax ? "font-bold text-[var(--primary)]" : ""
            }`}
          >
            {typeof v === "number" ? formatNumber(v) : v}
          </td>
        );
      })}
    </tr>
  );
}

export default function ComparePage() {
  const [creators, setCreators] = useState<Creator[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [results, setResults] = useState<CompareResult[] | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getCreators().then(setCreators);
  }, []);

  const toggleCreator = (id: number) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
    setResults(null);
  };

  const handleCompare = async () => {
    if (selected.length < 2) return;
    setLoading(true);
    try {
      const data = await compareCreators(selected);
      setResults(data);
    } catch (err) {
      console.error(err);
    }
    setLoading(false);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold">Compare Creators</h1>
        <p className="text-[var(--muted-foreground)] text-sm mt-1">
          Select 2 or more creators to compare side-by-side
        </p>
      </div>

      {/* Creator Selection */}
      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5">
        <h2 className="font-semibold mb-3">Select Creators</h2>
        <div className="flex flex-wrap gap-2">
          {creators.map((c) => (
            <button
              key={c.id}
              onClick={() => toggleCreator(c.id)}
              className={`px-3 py-1.5 rounded-md text-sm border ${
                selected.includes(c.id)
                  ? "border-[var(--primary)] bg-[var(--accent)] text-[var(--primary)]"
                  : "border-[var(--border)] hover:bg-[var(--muted)]"
              }`}
            >
              {c.name}
            </button>
          ))}
        </div>

        {creators.length === 0 && (
          <p className="text-sm text-[var(--muted-foreground)]">
            No creators to compare. Add some creators first.
          </p>
        )}

        <button
          onClick={handleCompare}
          disabled={selected.length < 2 || loading}
          className="mt-4 px-4 py-2 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-md text-sm font-medium hover:opacity-90 disabled:opacity-50"
        >
          {loading ? "Comparing..." : "Compare"}
        </button>
      </div>

      {/* Results */}
      {results && results.length > 0 && (
        <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-[var(--muted)]">
                <tr>
                  <th className="text-left p-3 font-medium">Metric</th>
                  {results.map((r) => (
                    <th key={r.creator_id} className="text-right p-3 font-medium">
                      {r.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <StatRow
                  label="Total Content"
                  values={results.map((r) => r.total_content)}
                />
                <StatRow
                  label="Total Views"
                  values={results.map((r) => r.total_views)}
                />
                <StatRow
                  label="Avg Views"
                  values={results.map((r) => r.avg_views)}
                />
                <StatRow
                  label="Avg Likes"
                  values={results.map((r) => r.avg_likes)}
                />
                <StatRow
                  label="Avg Comments"
                  values={results.map((r) => r.avg_comments)}
                />
                <StatRow
                  label="Platforms"
                  values={results.map((r) =>
                    r.platforms.map((p) => `${p.type}: @${p.handle}`).join(", ")
                  )}
                />
              </tbody>
            </table>
          </div>

          {/* Summaries */}
          <div className="p-5 border-t border-[var(--border)] space-y-4">
            <h3 className="font-semibold">Creator Summaries</h3>
            {results.map((r) => (
              <div key={r.creator_id}>
                <h4 className="text-sm font-medium">{r.name}</h4>
                <p className="text-sm text-[var(--muted-foreground)] mt-1 whitespace-pre-line">
                  {r.summary || "No summary generated yet."}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
