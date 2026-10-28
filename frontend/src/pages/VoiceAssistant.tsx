/* ── Voice Assistant page ─────────────────────────────────────────────────── */

import { useCallback, useRef, useState } from 'react';
import {
  ArrowRight,
  CheckCircle2,
  HelpCircle,
  Mic,
  Send,
  ShieldAlert,
  XCircle,
} from 'lucide-react';
import { confirmDecision, processCommand } from '../api/client';
import type { VoiceProcessResponse } from '../api/types';

const DECISION_STYLE: Record<string, { bg: string; border: string; icon: React.ElementType; label: string }> = {
  EXECUTE: { bg: 'bg-success/10', border: 'border-success/30', icon: CheckCircle2, label: 'Executed' },
  CLARIFY: { bg: 'bg-warning/10', border: 'border-warning/30', icon: HelpCircle, label: 'Clarification Needed' },
  REJECT: { bg: 'bg-danger/10', border: 'border-danger/30', icon: XCircle, label: 'Rejected' },
  ESCALATE: { bg: 'bg-escalate/10', border: 'border-escalate/30', icon: ShieldAlert, label: 'Escalated' },
};

interface HistoryEntry {
  role: 'user' | 'system';
  text: string;
  response?: VoiceProcessResponse;
}

export default function VoiceAssistant() {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [pendingClarification, setPendingClarification] = useState(false);
  const [lastInteractionId, setLastInteractionId] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    setTimeout(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }), 100);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const text = input.trim();
    setInput('');
    setHistory((h) => [...h, { role: 'user', text }]);
    setLoading(true);

    try {
      let resp: VoiceProcessResponse;

      if (pendingClarification && sessionId) {
        resp = await confirmDecision({
          session_id: sessionId,
          response: text,
          interaction_id: lastInteractionId ?? undefined,
        });
      } else {
        resp = await processCommand({
          text,
          input_mode: 'text',
          session_id: sessionId ?? undefined,
        });
      }

      setSessionId(resp.session_id);
      setLastInteractionId(resp.interaction_id);
      setPendingClarification(resp.decision === 'CLARIFY');

      setHistory((h) => [
        ...h,
        { role: 'system', text: resp.message, response: resp },
      ]);
    } catch (err: unknown) {
      setHistory((h) => [
        ...h,
        { role: 'system', text: `Error: ${err instanceof Error ? err.message : 'Unknown error'}` },
      ]);
    } finally {
      setLoading(false);
      scrollToBottom();
    }
  };

  return (
    <div className="max-w-3xl mx-auto flex flex-col h-[calc(100vh-3rem)]">
      <div className="mb-4">
        <h1 className="text-2xl font-bold mb-1 flex items-center gap-2">
          <Mic size={24} className="text-accent" /> Voice Assistant
        </h1>
        <p className="text-text-secondary text-sm">
          Type a command or paste transcribed speech.
          {sessionId && (
            <span className="ml-2 text-text-muted">
              Session: <code className="text-xs">{sessionId.slice(0, 8)}…</code>
            </span>
          )}
        </p>
      </div>

      {/* Chat history */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto space-y-3 pr-2 mb-4"
      >
        {history.length === 0 && (
          <div className="text-center py-16 text-text-muted space-y-2">
            <Mic size={48} className="mx-auto opacity-30" />
            <p className="text-lg">Try a command</p>
            <div className="space-y-1 text-sm">
              <p>"Turn on the bedroom light"</p>
              <p>"Turn off the fan"</p>
              <p>"Turn it off" (context-aware)</p>
              <p>"Turn off the light" (asks which one)</p>
              <p>"Help me I fell" (emergency)</p>
            </div>
          </div>
        )}

        {history.map((entry, idx) => (
          <div
            key={idx}
            className={`animate-fade-in ${
              entry.role === 'user' ? 'flex justify-end' : ''
            }`}
          >
            {entry.role === 'user' ? (
              <div className="bg-accent/15 text-accent-hover border border-accent/20 rounded-xl rounded-br-sm px-4 py-2.5 max-w-md">
                <p className="text-sm">{entry.text}</p>
              </div>
            ) : (
              <ResponseBubble entry={entry} />
            )}
          </div>
        ))}

        {loading && (
          <div className="flex gap-1.5 px-4 py-3 animate-fade-in">
            <span className="w-2 h-2 bg-accent rounded-full animate-pulse-dot" />
            <span className="w-2 h-2 bg-accent rounded-full animate-pulse-dot [animation-delay:200ms]" />
            <span className="w-2 h-2 bg-accent rounded-full animate-pulse-dot [animation-delay:400ms]" />
          </div>
        )}
      </div>

      {/* Input bar */}
      <form
        onSubmit={handleSubmit}
        className="flex gap-2 bg-bg-card border border-border rounded-xl p-2"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            pendingClarification
              ? 'Answer the question above…'
              : 'Type a command…'
          }
          className="flex-1 bg-transparent px-3 py-2 text-sm text-text-primary placeholder-text-muted outline-none"
          disabled={loading}
          autoFocus
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="bg-accent hover:bg-accent-hover disabled:opacity-30 text-bg-primary font-semibold px-4 py-2 rounded-lg text-sm transition-colors flex items-center gap-1.5"
        >
          <Send size={16} />
          Send
        </button>
      </form>
    </div>
  );
}

/* ── System response bubble ───────────────────────────────────────────────── */

function ResponseBubble({ entry }: { entry: HistoryEntry }) {
  const resp = entry.response;
  const style = resp ? DECISION_STYLE[resp.decision] : null;
  const Icon = style?.icon ?? ArrowRight;

  return (
    <div
      className={`rounded-xl rounded-bl-sm px-4 py-3 max-w-lg border ${
        style ? `${style.bg} ${style.border}` : 'bg-bg-card border-border'
      }`}
    >
      {/* Decision badge */}
      {style && (
        <div className="flex items-center gap-1.5 mb-2">
          <Icon size={14} />
          <span className="text-xs font-semibold uppercase tracking-wide">
            {style.label}
          </span>
        </div>
      )}

      <p className="text-sm">{entry.text}</p>

      {/* Details */}
      {resp && (
        <div className="mt-3 space-y-1.5 text-xs text-text-secondary border-t border-border/50 pt-2">
          {resp.intent && (
            <p>
              <span className="text-text-muted">Intent:</span> {resp.intent}
              {resp.intent_confidence != null &&
                ` (${(resp.intent_confidence * 100).toFixed(0)}%)`}
            </p>
          )}
          {resp.target_device && (
            <p>
              <span className="text-text-muted">Device:</span>{' '}
              {resp.target_device}
            </p>
          )}
          {resp.requested_action && (
            <p>
              <span className="text-text-muted">Action:</span>{' '}
              {resp.requested_action}
            </p>
          )}
          {resp.decision_reason && (
            <p>
              <span className="text-text-muted">Reason:</span>{' '}
              {resp.decision_reason}
            </p>
          )}
          {resp.entities &&
            Object.keys(resp.entities).length > 0 &&
            Boolean(resp.entities.resolved_from_context) && (
              <p className="text-info">↳ Resolved from context</p>
            )}
        </div>
      )}

      {/* Clarification prompt */}
      {resp?.clarification_question && (
        <p className="mt-2 text-sm font-medium text-warning">
          ❓ {resp.clarification_question}
        </p>
      )}
    </div>
  );
}
