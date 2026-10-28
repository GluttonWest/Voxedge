/* ── Dashboard page ───────────────────────────────────────────────────────── */

import { useEffect, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Mic,
  ToggleRight,
  Zap,
} from 'lucide-react';
import { getActivity, getSystemStatus, listDevices } from '../api/client';
import type { ActivityResponse, Device, SystemStatus } from '../api/types';

function StatCard({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  color: string;
}) {
  return (
    <div className="bg-bg-card border border-border rounded-xl p-5 animate-fade-in">
      <div className="flex items-center gap-3 mb-3">
        <div className={`p-2 rounded-lg ${color}`}>
          <Icon size={20} />
        </div>
        <span className="text-sm text-text-secondary">{label}</span>
      </div>
      <p className="text-2xl font-bold">{value}</p>
    </div>
  );
}

export default function Dashboard() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [activity, setActivity] = useState<ActivityResponse | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([getSystemStatus(), listDevices(), getActivity(10)])
      .then(([s, d, a]) => {
        setStatus(s);
        setDevices(d.devices);
        setActivity(a);
      })
      .catch((e) => setError(e.message));
  }, []);

  if (error) {
    return (
      <div className="bg-danger-dim/30 border border-danger/30 rounded-xl p-6 text-danger">
        <AlertTriangle className="inline mr-2" size={18} />
        Backend unreachable: {error}. Start the backend with{' '}
        <code className="bg-bg-secondary px-2 py-0.5 rounded">
          cd backend && .venv\Scripts\python -m uvicorn app.main:app --reload
        </code>
      </div>
    );
  }

  if (!status) {
    return <p className="text-text-muted animate-pulse">Loading dashboard…</p>;
  }

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h1 className="text-2xl font-bold mb-1">Dashboard</h1>
        <p className="text-text-secondary text-sm">
          VoxEdge system overview
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={Cpu}
          label="System Status"
          value={status.status === 'healthy' ? 'Healthy' : status.status}
          color="bg-success/15 text-success"
        />
        <StatCard
          icon={ToggleRight}
          label="Active Devices"
          value={`${status.active_devices} / ${status.total_devices}`}
          color="bg-accent/15 text-accent"
        />
        <StatCard
          icon={Activity}
          label="Interactions"
          value={status.total_interactions}
          color="bg-info/15 text-info"
        />
        <StatCard
          icon={AlertTriangle}
          label="Active Emergencies"
          value={status.active_emergencies}
          color={
            status.active_emergencies > 0
              ? 'bg-danger/15 text-danger'
              : 'bg-success/15 text-success'
          }
        />
      </div>

      {/* Subsystem checks */}
      <div className="bg-bg-card border border-border rounded-xl p-5">
        <h2 className="text-lg font-semibold mb-4">Subsystem Status</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[
            { label: 'Vosk Model', ok: status.vosk_model_loaded },
            { label: 'Voice Enrolled', ok: status.voice_enrolled },
            { label: 'Backend API', ok: true },
          ].map((s) => (
            <div
              key={s.label}
              className="flex items-center gap-2 text-sm"
            >
              {s.ok ? (
                <CheckCircle2 size={16} className="text-success" />
              ) : (
                <AlertTriangle size={16} className="text-warning" />
              )}
              <span className={s.ok ? 'text-text-primary' : 'text-warning'}>
                {s.label}
              </span>
              <span className="ml-auto text-text-muted text-xs">
                {s.ok ? 'Ready' : 'Not available'}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Device overview + Recent activity side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Devices */}
        <div className="bg-bg-card border border-border rounded-xl p-5">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Zap size={18} className="text-accent" /> Devices
          </h2>
          {devices.length === 0 ? (
            <p className="text-text-muted text-sm">No devices found</p>
          ) : (
            <div className="space-y-3">
              {devices.map((d) => (
                <div
                  key={d.id}
                  className="flex items-center justify-between bg-bg-primary/50 rounded-lg px-4 py-3"
                >
                  <div>
                    <p className="font-medium text-sm">{d.name}</p>
                    <p className="text-xs text-text-muted capitalize">
                      {d.location.replace('_', ' ')} · {d.device_type}
                    </p>
                  </div>
                  <span
                    className={`px-3 py-1 rounded-full text-xs font-semibold ${
                      d.state === 'ON'
                        ? 'bg-success/15 text-success'
                        : 'bg-bg-hover text-text-muted'
                    }`}
                  >
                    {d.state}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Recent interactions */}
        <div className="bg-bg-card border border-border rounded-xl p-5">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Mic size={18} className="text-accent" /> Recent Activity
          </h2>
          {!activity || activity.interactions.length === 0 ? (
            <p className="text-text-muted text-sm">
              No interactions yet. Try the Voice Assistant.
            </p>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {activity.interactions.slice(0, 8).map((i) => (
                <div
                  key={i.id}
                  className="flex items-center gap-3 bg-bg-primary/50 rounded-lg px-4 py-2.5 animate-slide-in"
                >
                  <DecisionDot decision={i.decision_outcome} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm truncate">
                      {i.recognized_text || '—'}
                    </p>
                    <p className="text-xs text-text-muted">
                      {i.intent} → {i.decision_outcome}
                    </p>
                  </div>
                  <span className="text-xs text-text-muted whitespace-nowrap">
                    {new Date(i.created_at).toLocaleTimeString()}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DecisionDot({ decision }: { decision: string | null }) {
  const colors: Record<string, string> = {
    EXECUTE: 'bg-success',
    CLARIFY: 'bg-warning',
    REJECT: 'bg-danger',
    ESCALATE: 'bg-escalate',
  };
  return (
    <span
      className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
        colors[decision ?? ''] ?? 'bg-text-muted'
      }`}
    />
  );
}
