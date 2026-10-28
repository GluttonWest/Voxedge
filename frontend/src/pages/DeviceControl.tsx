/* ── Device control page ──────────────────────────────────────────────────── */

import { useEffect, useState } from 'react';
import { Lightbulb, Fan, Power, RefreshCw } from 'lucide-react';
import { commandDevice, listDevices } from '../api/client';
import type { Device } from '../api/types';

const ICONS: Record<string, React.ElementType> = {
  light: Lightbulb,
  fan: Fan,
};

export default function DeviceControl() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ id: string; msg: string } | null>(null);

  const load = () => {
    listDevices()
      .then((r) => setDevices(r.devices))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const toggle = async (device: Device) => {
    const newAction = device.state === 'ON' ? 'OFF' : 'ON';
    setActionLoading(device.id);
    try {
      const res = await commandDevice(device.id, newAction);
      setFeedback({ id: device.id, msg: res.message });
      load();
    } catch (err: unknown) {
      setFeedback({
        id: device.id,
        msg: err instanceof Error ? err.message : 'Failed',
      });
    } finally {
      setActionLoading(null);
      setTimeout(() => setFeedback(null), 3000);
    }
  };

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold mb-1">Device Control</h1>
          <p className="text-text-secondary text-sm">
            Manage simulated smart-home devices
          </p>
        </div>
        <button
          onClick={load}
          className="text-text-muted hover:text-accent transition-colors p-2"
        >
          <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {loading && devices.length === 0 ? (
        <p className="text-text-muted animate-pulse">Loading devices…</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {devices.map((d) => {
            const Icon = ICONS[d.device_type] ?? Power;
            const isOn = d.state === 'ON';
            return (
              <div
                key={d.id}
                className={`bg-bg-card border rounded-xl p-5 transition-all animate-fade-in ${
                  isOn
                    ? 'border-success/40 shadow-[0_0_20px_-6px_rgba(74,222,128,0.15)]'
                    : 'border-border'
                }`}
              >
                <div className="flex items-center justify-between mb-4">
                  <div
                    className={`p-3 rounded-xl ${
                      isOn ? 'bg-success/15 text-success' : 'bg-bg-hover text-text-muted'
                    }`}
                  >
                    <Icon size={24} />
                  </div>
                  <span
                    className={`text-xs font-bold px-2.5 py-1 rounded-full ${
                      isOn
                        ? 'bg-success/15 text-success'
                        : 'bg-bg-hover text-text-muted'
                    }`}
                  >
                    {d.state}
                  </span>
                </div>

                <h3 className="font-semibold mb-0.5">{d.name}</h3>
                <p className="text-xs text-text-muted capitalize mb-4">
                  {d.location.replace('_', ' ')} · {d.device_type}
                </p>

                <button
                  onClick={() => toggle(d)}
                  disabled={actionLoading === d.id}
                  className={`w-full py-2.5 rounded-lg text-sm font-semibold transition-all ${
                    isOn
                      ? 'bg-danger/15 text-danger hover:bg-danger/25 border border-danger/20'
                      : 'bg-success/15 text-success hover:bg-success/25 border border-success/20'
                  } disabled:opacity-50`}
                >
                  {actionLoading === d.id
                    ? 'Processing…'
                    : isOn
                      ? 'Turn OFF'
                      : 'Turn ON'}
                </button>

                {feedback?.id === d.id && (
                  <p className="text-xs text-text-secondary mt-2 text-center animate-fade-in">
                    {feedback.msg}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
