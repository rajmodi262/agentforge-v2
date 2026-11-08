/**
 * Phantom Hunter — API client
 */
import { API_BASE } from './api';

export interface CallSegment { segment: string; priority: number; reasons: string[] }
export interface PhProject {
  id: string; name: string; developer: string | null; city: string | null; state: string | null; country: string | null;
  lat: number | null; lon: number | null; capacity_mw: number | null; capacity_basis: string | null; target_year: number | null;
  power_partner: string | null; ai_density: boolean; stage: number; stage_name: string; reality_score: number;
  reality_mw: number; weakest_assumption: string | null; n_sources: number;
  call_segments: Record<string, CallSegment> | null; has_debate: boolean; last_seen: string | null;
  priority?: number; reasons?: string[];
}
export interface ArticleRef { url: string; title: string; source: string; published: string | null; text_kind: string }
export interface EvidenceItem { layer: string; detail: string; quote: string; date: string | null; article: ArticleRef | null }
export interface DebatePoint { claim: string; cites: string[]; from_missing_evidence?: boolean }
export interface Debate { bull: DebatePoint[]; bear: DebatePoint[]; verdict: string; reasoning: string; watch_for: string; evidence_ids: string[] }
export interface ProjectDetail extends PhProject {
  score_breakdown: { term: string; delta: number | null; value?: number; why: string }[];
  debate: Debate | null;
  evidence: EvidenceItem[];
  anomalies: { kind: string; severity: string; message: string }[];
  mentions: { article: ArticleRef | null; verified_ratio: number; verification: Record<string, any>; data: Record<string, any> }[];
  ladder: { layer: string; reached: boolean; verified: boolean }[];
}
export interface Summary {
  projects: number; announced_mw: number; reality_mw: number;
  by_country: Record<string, { projects: number; announced_mw: number; reality_mw: number; with_capacity: number }>;
  by_state: { place: string; projects: number; announced_mw: number; reality_mw: number }[];
  stages: Record<string, number>;
  articles: { total: number; full_text: number; headline_only: number; relevant: number; extracted: number };
  mentions: number; claims_verified_pct: number | null; anomalies: Record<string, number>;
}
export interface Signal { project_id: string; project: string; layer: string; quote: string; date: string | null; source: string; url: string; reality_score: number; country: string | null }
export interface ChatAnswer { answer: string; sources: { id: string; project_id: string; name: string; url: string | null; title: string | null }[] }

function authHeaders(): Record<string, string> {
  const t = localStorage.getItem('agentforge_token');
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}/phantom${path}`, { headers: authHeaders() });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
  return r.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API_BASE}/phantom${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
  return r.json();
}

export const phantom = {
  summary: () => get<Summary>('/summary'),
  projects: (q = '') => get<{ total: number; projects: PhProject[] }>(`/projects${q}`),
  whoToCall: (segment: string) => get<{ segment: string; projects: PhProject[] }>(`/who-to-call?segment=${segment}&limit=8`),
  project: (id: string) => get<ProjectDetail>(`/projects/${id}`),
  debate: (id: string, refresh = false) => post<Debate>(`/projects/${id}/debate${refresh ? '?refresh=true' : ''}`),
  ask: (question: string) => post<ChatAnswer>('/ask', { question }),
  signals: () => get<{ signals: Signal[]; anomalies: { project_id: string; project: string; kind: string; severity: string; message: string }[] }>('/signals'),
  hunt: (region: string) => post<{ run_id: string; websocket_url: string }>('/hunt', { region, max_rounds: 2 }),
  run: (id: string) => get<{ status: string; stats: Record<string, unknown>; log: string[] }>(`/runs/${id}`),
  // Business exports — plain links (public, read-only data), so the browser handles the download
  exportXlsxUrl: `${API_BASE}/phantom/export.xlsx`,
  exportCsvUrl: (table: string) => `${API_BASE}/phantom/export/${table}.csv`,
};

export const WS_BASE = API_BASE.replace('http://', 'ws://').replace('https://', 'wss://').replace('/api/v1', '');

export const STAGE_COLORS: Record<string, string> = {
  ANNOUNCED: '#94a3b8', SITE: '#a78bfa', APPROVED: '#60a5fa', POWER: '#f59e0b', BUILDING: '#06b6d4', LIVE: '#10b981',
  FINANCED: '#e879f9', DELAYED: '#fb923c', CANCELLED: '#ef4444', OPPOSITION: '#f87171', SCALED_DOWN: '#fbbf24',
};

export const scoreColor = (s: number) => (s >= 0.7 ? '#10b981' : s >= 0.45 ? '#f59e0b' : '#ef4444');
export const fmtMW = (mw: number | null | undefined) =>
  mw == null ? '—' : mw >= 1000 ? `${(mw / 1000).toFixed(mw >= 10000 ? 0 : 1)} GW` : `${Math.round(mw)} MW`;
