/* ── API types matching the Pydantic schemas ─────────────────────────────── */

export interface Device {
  id: string;
  name: string;
  device_type: string;
  location: string;
  state: string;
  supported_actions: string[];
  is_active: boolean;
  updated_at: string;
}

export interface DeviceListResponse {
  devices: Device[];
  count: number;
}

export interface VoiceProcessRequest {
  text: string;
  input_mode?: string;
  session_id?: string;
}

export interface VoiceProcessResponse {
  interaction_id: number;
  session_id: string;
  recognized_text: string;
  intent: string | null;
  intent_confidence: number | null;
  entities: Record<string, unknown>;
  decision: string;
  decision_reason: string;
  target_device: string | null;
  requested_action: string | null;
  execution_status: string | null;
  new_device_state: string | null;
  clarification_question: string | null;
  requires_confirmation: boolean;
  message: string;
}

export interface ConfirmationRequest {
  session_id: string;
  response: string;
  interaction_id?: number;
}

export interface InteractionSummary {
  id: number;
  session_id: string;
  recognized_text: string | null;
  intent: string | null;
  decision_outcome: string | null;
  decision_reason: string | null;
  target_device_id: string | null;
  requested_action: string | null;
  execution_status: string | null;
  created_at: string;
}

export interface ActivityEntry {
  id: number;
  interaction_id: number | null;
  device_id: string;
  action: string;
  previous_state: string;
  new_state: string;
  success: boolean;
  error_message: string | null;
  created_at: string;
}

export interface ActivityResponse {
  interactions: InteractionSummary[];
  device_actions: ActivityEntry[];
  total_interactions: number;
  total_actions: number;
}

export interface EmergencyContact {
  name: string;
  relationship: string;
  phone: string;
  notified: boolean;
  notified_at: string | null;
}

export interface EmergencyEvent {
  id: number;
  trigger_text: string;
  status: string;
  severity: string;
  contacts: EmergencyContact[];
  notes: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

export interface SystemStatus {
  status: string;
  version: string;
  vosk_model_loaded: boolean;
  voice_enrolled: boolean;
  total_devices: number;
  active_devices: number;
  total_interactions: number;
  active_emergencies: number;
  uptime_seconds: number;
  timestamp: string;
}
