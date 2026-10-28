/* ── Sidebar navigation layout ────────────────────────────────────────────── */

import { NavLink, Outlet } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Home,
  Mic,
  ToggleRight,
} from 'lucide-react';

const NAV = [
  { to: '/', icon: Home, label: 'Dashboard' },
  { to: '/voice', icon: Mic, label: 'Voice Assistant' },
  { to: '/devices', icon: ToggleRight, label: 'Devices' },
  { to: '/activity', icon: Activity, label: 'Activity' },
  { to: '/emergency', icon: AlertTriangle, label: 'Emergency' },
  { to: '/evaluation', icon: BarChart3, label: 'Evaluation' },
];

export default function Layout() {
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-60 flex-shrink-0 bg-bg-secondary border-r border-border flex flex-col">
        <div className="p-5 border-b border-border">
          <h1 className="text-xl font-bold text-accent tracking-wide">
            ⚡ VoxEdge
          </h1>
          <p className="text-xs text-text-muted mt-1">
            Reliability-Aware Voice Assistant
          </p>
        </div>

        <nav className="flex-1 py-4 space-y-1 px-3">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-accent/15 text-accent'
                    : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-border text-xs text-text-muted">
          v2.0.0 · Phase 2
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto p-6">
        <Outlet />
      </main>
    </div>
  );
}
