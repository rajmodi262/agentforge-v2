/**
 * useWorkflowSocket — Real-time WebSocket hook for agent streaming (A+ Edition)
 *
 * Features:
 * - Auto-reconnect with exponential backoff
 * - Catch-up event processing on reconnect
 * - Connection status tracking
 * - Keep-alive ping/pong
 */

import { useState, useEffect, useRef, useCallback } from 'react';

/* ─── Event types from the backend WebSocketManager ─── */
export interface WorkflowStartedEvent {
  type: 'workflow_started';
  mode: 'live' | 'mock';
  provider: string;
}

export interface AgentStartedEvent {
  type: 'agent_started';
  agent: string;
}

export interface AgentThinkingEvent {
  type: 'agent_thinking';
  agent: string;
  content: string;
}

export interface AgentToolCallEvent {
  type: 'agent_tool_call';
  agent: string;
  tool: string;
  query: string;
}

export interface AgentCompletedEvent {
  type: 'agent_completed';
  agent: string;
  output_preview: string;
}

export interface InterAgentMessageEvent {
  type: 'inter_agent_message';
  from: string;
  to: string;
  message: string;
}

export interface AgentReasoningStepEvent {
  type: 'agent_reasoning_step';
  agent: string;
  step: number;
  total_steps: number;
  label: string;
  content: string;
}

export interface BoardMeetingRoundEvent {
  type: 'board_meeting_round';
  round: number;
  challenger: string;
  target: string;
  content: string;
}

export interface WorkflowCompletedEvent {
  type: 'workflow_completed';
  project_id?: string;
  download_url: string;
}

export interface WorkflowErrorEvent {
  type: 'workflow_error';
  agent: string;
  error: string;
  recoverable: boolean;
}

export interface CatchupEvent {
  type: 'catchup';
  events: WorkflowEvent[];
}

export type WorkflowEvent =
  | WorkflowStartedEvent
  | AgentStartedEvent
  | AgentThinkingEvent
  | AgentToolCallEvent
  | AgentReasoningStepEvent
  | BoardMeetingRoundEvent
  | AgentCompletedEvent
  | InterAgentMessageEvent
  | WorkflowCompletedEvent
  | WorkflowErrorEvent;

/* ─── Terminal line (for CodePreview) ─── */
export interface TerminalLine {
  type: 'command' | 'output' | 'success' | 'error' | 'info';
  text: string;
  delay?: number;
}

/* ─── Workflow status ─── */
export type WorkflowStatus = 'idle' | 'connecting' | 'running' | 'completed' | 'error' | 'reconnecting';

/* ─── Agent name → key mapping ─── */
const AGENT_KEYS: Record<string, string> = {
  'CEO Agent': 'ceo',
  'Research Agent': 'research',
  'Marketing Agent': 'marketing',
  'Developer Agent': 'developer',
  'Finance Agent': 'finance',
  'Analytics Agent': 'analytics',
  'Operations Agent': 'operations',
};

/* ─── Reconnect config ─── */
const RECONNECT_BASE_DELAY = 1000; // 1 second
const RECONNECT_MAX_DELAY = 30000; // 30 seconds
const RECONNECT_MAX_ATTEMPTS = 10;

/* ─── The Hook ─── */
export function useWorkflowSocket() {
  const [status, setStatus] = useState<WorkflowStatus>('idle');
  const [mode, setMode] = useState<'live' | 'mock' | ''>('');
  const [provider, setProvider] = useState<string>('');
  const [currentAgent, setCurrentAgent] = useState<string>('');
  const [completedAgents, setCompletedAgents] = useState<string[]>([]);
  const [terminalLines, setTerminalLines] = useState<TerminalLine[]>([]);
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [downloadUrl, setDownloadUrl] = useState<string>('');
  const [error, setError] = useState<string>('');

  const wsRef = useRef<WebSocket | null>(null);
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const workflowIdRef = useRef<string>('');
  const isTerminalRef = useRef(false); // true when workflow completed/errored

  /* ─── Push a line to the terminal ─── */
  const pushLine = useCallback((line: TerminalLine) => {
    setTerminalLines((prev) => [...prev, line]);
  }, []);

  /* ─── Process a single event ─── */
  const processEvent = useCallback((data: WorkflowEvent) => {
    setEvents((prev) => [...prev, data]);

    switch (data.type) {
      case 'workflow_started': {
        setMode(data.mode);
        setProvider(data.provider);
        if (data.mode === 'mock') {
          pushLine({ type: 'error', text: '  ⚠ DEMO MODE — responses below are SIMULATED mock data, not a live LLM.' });
          pushLine({ type: 'info', text: '    Set a free GROQ_API_KEY to run real multi-agent analysis.' });
          pushLine({ type: 'info', text: '' });
        } else {
          pushLine({ type: 'success', text: `  ● LIVE — running on ${data.provider}` });
          pushLine({ type: 'info', text: '' });
        }
        break;
      }

      case 'agent_started': {
        setCurrentAgent(data.agent);
        const agentKey = AGENT_KEYS[data.agent] || data.agent;
        pushLine({ type: 'command', text: `> [${agentKey.toUpperCase()}] Agent initializing...` });
        break;
      }

      case 'agent_thinking': {
        const agentKey = AGENT_KEYS[data.agent] || data.agent;
        pushLine({ type: 'output', text: `  [${agentKey}] ${data.content}` });
        break;
      }

      case 'agent_tool_call': {
        pushLine({ type: 'info', text: `  ⚡ Tool: ${data.tool} → ${data.query}` });
        break;
      }

      case 'agent_reasoning_step': {
        pushLine({ type: 'output', text: `  🧠 [Step ${data.step}/${data.total_steps}] ${data.label} — ${data.content}` });
        break;
      }

      case 'board_meeting_round': {
        pushLine({ type: 'command', text: `  ⚔️ [DEBATE R${data.round}] ${data.challenger} vs ${data.target}` });
        pushLine({ type: 'output', text: `     ${data.content}` });
        break;
      }

      case 'agent_completed': {
        const agentKey = AGENT_KEYS[data.agent] || data.agent;
        setCompletedAgents((prev) => [...prev, agentKey]);
        setCurrentAgent('');
        pushLine({ type: 'success', text: `  ✓ [${agentKey.toUpperCase()}] Complete — ${data.output_preview.slice(0, 80)}` });
        pushLine({ type: 'info', text: '' });
        break;
      }

      case 'inter_agent_message': {
        pushLine({ type: 'info', text: `  📨 ${data.from} → ${data.to}: ${data.message}` });
        break;
      }

      case 'workflow_completed': {
        setStatus('completed');
        isTerminalRef.current = true;
        setCurrentAgent('');
        setDownloadUrl(data.download_url);
        pushLine({ type: 'info', text: '' });
        pushLine({ type: 'success', text: '╔══════════════════════════════════════════════╗' });
        pushLine({ type: 'success', text: '║   ✓ BLUEPRINT GENERATION COMPLETE            ║' });
        pushLine({ type: 'success', text: '╚══════════════════════════════════════════════╝' });
        pushLine({ type: 'success', text: `  📄 Report ready: ${data.download_url}` });
        break;
      }

      case 'workflow_error': {
        if (data.recoverable) {
          pushLine({ type: 'error', text: `  ⚠ [${data.agent}] Error (recoverable): ${data.error}` });
        } else {
          setStatus('error');
          isTerminalRef.current = true;
          setError(data.error);
          pushLine({ type: 'error', text: `  ✗ [${data.agent}] Fatal error: ${data.error}` });
        }
        break;
      }
    }
  }, [pushLine]);

  /* ─── Attempt reconnection with exponential backoff ─── */
  const attemptReconnect = useCallback((workflowId: string) => {
    if (isTerminalRef.current) return; // Don't reconnect after completion/error
    if (reconnectAttemptRef.current >= RECONNECT_MAX_ATTEMPTS) {
      setStatus('error');
      setError('Lost connection to server. Please refresh the page.');
      pushLine({ type: 'error', text: '  ✗ Max reconnection attempts reached' });
      return;
    }

    const delay = Math.min(
      RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttemptRef.current),
      RECONNECT_MAX_DELAY
    );
    reconnectAttemptRef.current++;
    setStatus('reconnecting');
    pushLine({ type: 'info', text: `  ↻ Reconnecting in ${delay / 1000}s (attempt ${reconnectAttemptRef.current}/${RECONNECT_MAX_ATTEMPTS})...` });

    reconnectTimeoutRef.current = setTimeout(() => {
      connectInternal(workflowId, true);
    }, delay);
  }, [pushLine]);

  /* ─── Internal connect (shared by initial connect and reconnect) ─── */
  const connectInternal = useCallback((workflowId: string, isReconnect = false) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.close();
    }

    const wsUrl = `ws://localhost:8000/api/v1/ws/${workflowId}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus('running');
      reconnectAttemptRef.current = 0; // Reset on successful connect

      if (isReconnect) {
        pushLine({ type: 'success', text: '  ✓ Reconnected successfully' });
      } else {
        pushLine({ type: 'success', text: '✓ Connected to neural pipeline' });
        pushLine({ type: 'command', text: '> Initializing pipeline: 7 agents + board debate + synthesis...' });
        pushLine({ type: 'info', text: '' });
      }

      // Keep-alive ping
      pingIntervalRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, 25000);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        // Skip pong responses
        if (data.type === 'pong') return;

        // Handle catch-up batch from server
        if (data.type === 'catchup' && Array.isArray(data.events)) {
          pushLine({ type: 'info', text: `  ↻ Processing ${data.events.length} catch-up events...` });
          // Reset state and replay
          setCompletedAgents([]);
          setCurrentAgent('');
          for (const evt of data.events) {
            processEvent(evt as WorkflowEvent);
          }
          return;
        }

        processEvent(data as WorkflowEvent);
      } catch {
        // Ignore parse errors for non-JSON messages
      }
    };

    ws.onerror = () => {
      if (!isTerminalRef.current) {
        pushLine({ type: 'error', text: '  ✗ WebSocket connection error' });
      }
    };

    ws.onclose = () => {
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }

      if (!isTerminalRef.current) {
        attemptReconnect(workflowId);
      }
    };
  }, [processEvent, pushLine, attemptReconnect]);

  /* ─── Public connect ─── */
  const connect = useCallback((workflowId: string) => {
    // Clean up any existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }

    workflowIdRef.current = workflowId;
    isTerminalRef.current = false;
    reconnectAttemptRef.current = 0;

    setStatus('connecting');
    setMode('');
    setProvider('');
    setCompletedAgents([]);
    setTerminalLines([
      { type: 'info', text: '╔══════════════════════════════════════════════╗' },
      { type: 'info', text: '║   AGENTFORGE AI — NEURAL PIPELINE ACTIVATED  ║' },
      { type: 'info', text: '╚══════════════════════════════════════════════╝' },
      { type: 'command', text: '> Connecting to orchestrator...' },
    ]);
    setEvents([]);
    setError('');

    connectInternal(workflowId, false);
  }, [connectInternal]);

  /* ─── Disconnect ─── */
  const disconnect = useCallback(() => {
    isTerminalRef.current = true; // Prevent reconnect
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
  }, []);

  /* ─── Cleanup on unmount ─── */
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return {
    status,
    mode,
    provider,
    currentAgent,
    completedAgents,
    terminalLines,
    events,
    downloadUrl,
    error,
    connect,
    disconnect,
  };
}
