/* ── Activity & Safety page ───────────────────────────────────────────────── */

import { useEffect, useState } from 'react';
import { Activity, Filter, RefreshCw } from 'lucide-react';
import { getActivity } from '../api/client';
import type { ActivityResponse } from '../api/types';

const DECISION_COLORS: Record<string, string> = {
  EXECUTE: 'text-success',
  CLARIFY: 'text-warning',
  REJECT: 'text-danger',
  ESCALATE: 'text-escalate',
};

type FilterType = 'all' | 'EXECUTE' | 'CLARIFY' | 'REJECT' | 'ESCALATE';

export default function ActivityPage() {
  const [data, setData] = useState<ActivityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterType>('all');

  const load = () => {
    getActivity(100)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const filtered = data?.interactions.filter(
    (i) => filter === 'all' || i.decision_outcome === filter
  );

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold mb-1 flex items-center gap-2">
            <Activity size={24} className="text-accent" /> Activity & Safety
          </h1>
          <p className="text-text-secondary text-sm">
            {data
              ? `${data.total_interactions} interactions · ${data.total_actions} device actions`
              : 'Loading…'}
          </p>
        </div>
        <button onClick={load} className="text-text-muted hover:text-accent p-2">
          <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <Filter size={14} className="text-text-muted" />
        {(['all', 'EXECUTE', 'CLARIFY', 'REJECT', 'ESCALATE'] as FilterType[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              filter === f
                ? 'bg-accent/15 text-accent'
                : 'bg-bg-card text-text-muted hover:text-text-primary border border-border'
            }`}
          >
            {f === 'all' ? 'All' : f}
          </button>
        ))}
      </div>

      {/* Interaction table */}
      {!filtered || filtered.length === 0 ? (
        <p className="text-text-muted text-sm py-8 text-center">
          {loading ? 'Loading…' : 'No interactions match the current filter.'}
        </p>
      ) : (
        <div className="bg-bg-card border border-border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-text-muted text-left text-xs uppercase tracking-wide">
                <th className="px-4 py-3">#</th>
                <th className="px-4 py-3">Command</th>
                <th className="px-4 py-3">Intent</th>
                <th className="px-4 py-3">Decision</th>
                <th className="px-4 py-3">Device</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Time</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((i) => (
                <tr
                  key={i.id}
                  className="border-b border-border/50 hover:bg-bg-hover/50 transition-colors"
                >
                  <td className="px-4 py-3 text-text-muted">{i.id}</td>
                  <td className="px-4 py-3 max-w-[200px] truncate">
                    {i.recognized_text || '—'}
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {i.intent || '—'}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`font-semibold ${
                        DECISION_COLORS[i.decision_outcome ?? ''] ?? 'text-text-muted'
                      }`}
                    >
                      {i.decision_outcome || '—'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {i.target_device_id || '—'}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={i.execution_status} />
                  </td>
                  <td className="px-4 py-3 text-text-muted text-xs whitespace-nowrap">
                    {new Date(i.created_at).toLocaleTimeString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Device actions */}
      {data && data.device_actions.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3">Device State Changes</h2>
          <div className="bg-bg-card border border-border rounded-xl p-4 space-y-2">
            {data.device_actions.slice(0, 20).map((a) => (
              <div
                key={a.id}
                className="flex items-center gap-3 text-sm bg-bg-primary/50 rounded-lg px-4 py-2"
              >
                <span className={`font-mono text-xs ${a.success ? 'text-success' : 'text-danger'}`}>
                  {a.success ? '✓' : '✗'}
                </span>
                <span className="font-medium">{a.device_id}</span>
                <span className="text-text-muted">
                  {a.previous_state} → {a.new_state}
                </span>
                <span className="ml-auto text-xs text-text-muted">
                  {new Date(a.created_at).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="text-text-muted">—</span>;
  const styles: Record<string, string> = {
    SUCCESS: 'bg-success/15 text-success',
    FAILED: 'bg-danger/15 text-danger',
    PENDING: 'bg-warning/15 text-warning',
    SKIPPED: 'bg-bg-hover text-text-muted',
  };
  return (
    <span
      className={`text-xs font-semibold px-2 py-0.5 rounded ${
        styles[status] ?? 'bg-bg-hover text-text-muted'
      }`}
    >
      {status}
    </span>
  );
}
