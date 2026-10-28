/* ── API client — all fetch calls to the FastAPI backend ──────────────────── */

import type {
  ActivityResponse,
  ConfirmationRequest,
  Device,
  DeviceListResponse,
  EmergencyEvent,
  SystemStatus,
  VoiceProcessRequest,
  VoiceProcessResponse,
} from './types';

const BASE = '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `API error ${res.status}`);
  }
  return res.json();
}

/* ── Voice ─────────────────────────────────────────────────────────────────── */

export const processCommand = (body: VoiceProcessRequest) =>
  request<VoiceProcessResponse>('/voice/process', {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const confirmDecision = (body: ConfirmationRequest) =>
  request<VoiceProcessResponse>('/decisions/confirm', {
    method: 'POST',
    body: JSON.stringify(body),
  });

/* ── Devices ───────────────────────────────────────────────────────────────── */

export const listDevices = () =>
  request<DeviceListResponse>('/devices');

export const getDevice = (id: string) =>
  request<Device>(`/devices/${id}`);

export const commandDevice = (id: string, action: string) =>
  request<{ device_id: string; action: string; previous_state: string; new_state: string; success: boolean; message: string }>(
    `/devices/${id}/command`,
    { method: 'POST', body: JSON.stringify({ action }) },
  );

/* ── Activity ──────────────────────────────────────────────────────────────── */

export const getActivity = (limit = 50) =>
  request<ActivityResponse>(`/activity?limit=${limit}`);

/* ── Emergency ─────────────────────────────────────────────────────────────── */

export const triggerEmergency = (text = 'Emergency button pressed', severity = 'HIGH') =>
  request<EmergencyEvent>('/emergency/trigger', {
    method: 'POST',
    body: JSON.stringify({ trigger_text: text, severity }),
  });

export const listEmergencies = () =>
  request<EmergencyEvent[]>('/emergency');

export const updateEmergency = (id: number, status: string, notes?: string) =>
  request<EmergencyEvent>(`/emergency/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ status, notes }),
  });

/* ── System ────────────────────────────────────────────────────────────────── */

export const getSystemStatus = () =>
  request<SystemStatus>('/system/status');
