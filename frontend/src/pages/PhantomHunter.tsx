/**
 * Phantom Hunter — dashboard
 *
 * Announced vs reality-weighted capacity, the Reality Globe, who to call this
 * month per buyer segment, the anomaly feed, the full project table, a live
 * hunt log, and the "Ask the Tracker" chat.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout';
import RealityGlobe from '../components/RealityGlobe';
import { colors, radii, typography } from '../styles/tokens';
import { phantom, fmtMW, scoreColor, STAGE_COLORS, WS_BASE, type PhProject, type Summary, type ChatAnswer, type Signal } from '../services/phantom';

const card: React.CSSProperties = { background: colors.bgCard, border: `1px solid ${colors.border}`, borderRadius: radii.lg, padding: '1.25rem' };
const mono = "'JetBrains Mono', monospace";
const LADDER = ['ANNOUNCED', 'SITE', 'APPROVED', 'POWER', 'BUILDING', 'LIVE'];
const SEGMENTS = [
  { key: 'power', label: '⚡ Power & IPPs' },
  { key: 'electrical', label: '🔌 Electrical equipment' },
  { key: 'cooling', label: '❄️ Cooling' },
];

function Stat({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{ ...card, flex: 1, minWidth: 180 }}>
      <div style={{ fontSize: 11, letterSpacing: '0.12em', color: colors.textMuted, fontFamily: mono }}>{label}</div>
      <div style={{ fontSize: '2rem', fontWeight: 700, color: color || colors.white, marginTop: 6, fontFamily: "'Space Grotesk', sans-serif" }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: colors.textDim, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

export function ScorePill({ s }: { s: number }) {
  const c = scoreColor(s);
  return <span style={{ fontFamily: mono, fontSize: 12, fontWeight: 700, color: c, background: `${c}1f`, border: `1px solid ${c}55`, borderRadius: 20, padding: '2px 9px' }}>{Math.round(s * 100)}%</span>;
}

export function StagePill({ stage }: { stage: string }) {
  const c = STAGE_COLORS[stage] || '#94a3b8';
  return <span style={{ fontFamily: mono, fontSize: 10.5, color: c, border: `1px solid ${c}66`, borderRadius: 6, padding: '2px 7px', letterSpacing: '0.05em' }}>{stage}</span>;
}

export default function PhantomHunter() {
  const nav = useNavigate();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [projects, setProjects] = useState<PhProject[]>([]);
  const [segment, setSegment] = useState('power');
  const [calls, setCalls] = useState<PhProject[]>([]);
  const [country, setCountry] = useState('');
  const [error, setError] = useState('');
  const [hunting, setHunting] = useState(false);
  const [huntLog, setHuntLog] = useState<string[]>([]);
  const [q, setQ] = useState('');
  const [answer, setAnswer] = useState<ChatAnswer | null>(null);
  const [asking, setAsking] = useState(false);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [alerts, setAlerts] = useState<{ project_id: string; project: string; kind: string; severity: string; message: string }[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([phantom.summary(), phantom.projects(country ? `?country=${country}` : '')]);
      setSummary(s); setProjects(p.projects); setError('');
    } catch (e) { setError((e as Error).message); }
  }, [country]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { phantom.whoToCall(segment).then((r) => setCalls(r.projects)).catch(() => setCalls([])); }, [segment, summary]);
  useEffect(() => { phantom.signals().then((r) => { setSignals(r.signals); setAlerts(r.anomalies); }).catch(() => undefined); }, [summary]);
  useEffect(() => () => wsRef.current?.close(), []);

  const startHunt = async (region: string) => {
    try {
      setHunting(true); setHuntLog([`▶ Starting a hunt in ${region}…`]);
      const r = await phantom.hunt(region);
      const ws = new WebSocket(`${WS_BASE}${r.websocket_url}`);
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        const d = JSON.parse(ev.data);
        const events = d.type === 'catchup' ? d.events : [d];
        for (const e of events) {
          if (e.type === 'hunt_finished') { setHunting(false); setHuntLog((l) => [...l, `✓ Hunt ${e.status}`]); load(); }
          else if (e.content) setHuntLog((l) => [...l.slice(-40), `[${e.agent}] ${e.content}`]);
        }
      };
    } catch (e) { setHunting(false); setHuntLog((l) => [...l, `✗ ${(e as Error).message}`]); }
  };

  const ask = async () => {
    if (q.trim().length < 3) return;
    setAsking(true); setAnswer(null);
    try { setAnswer(await phantom.ask(q)); } catch (e) { setAnswer({ answer: `Error: ${(e as Error).message}`, sources: [] }); }
    setAsking(false);
  };

  const phantomMw = summary ? summary.announced_mw - summary.reality_mw : 0;
  const pctReal = summary && summary.announced_mw ? summary.reality_mw / summary.announced_mw : 0;

  return (
    <DashboardLayout>
      <div style={{ maxWidth: 1280, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 20 }}>
          <div>
            <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: '0.2em', color: colors.secondary }}>INDIA · MALAYSIA DATA-CENTRE PIPELINE</div>
            <h1 style={{ margin: '6px 0 4px', fontSize: '2rem', fontFamily: "'Space Grotesk', sans-serif" }}>👻 Phantom Hunter</h1>
            <div style={{ color: colors.textMuted, fontSize: typography.sm, maxWidth: 680 }}>
              Every announced data centre is a promise. Agents read the public news, verify every claim against its source, and score how likely each project is to really get built — and who should call them this month.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {['malaysia', 'india'].map((r) => (
              <button key={r} disabled={hunting} onClick={() => startHunt(r)} style={{ padding: '0.6rem 1rem', borderRadius: radii.md, border: `1px solid ${colors.borderLight}`, background: hunting ? 'rgba(255,255,255,0.04)' : 'linear-gradient(135deg, rgba(124,58,237,0.35), rgba(6,182,212,0.25))', color: '#fff', cursor: hunting ? 'wait' : 'pointer', fontWeight: 600 }}>
                {hunting ? '⏳ Hunting…' : `🛰️ Hunt ${r[0].toUpperCase() + r.slice(1)}`}
              </button>
            ))}
          </div>
        </div>
        {error && <div style={{ ...card, borderColor: colors.error, color: colors.error, marginBottom: 16 }}>{error}</div>}

        {/* Headline numbers */}
        {summary && (
          <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 16 }}>
            <Stat label="ANNOUNCED CAPACITY" value={fmtMW(summary.announced_mw)} sub={`${summary.projects} projects resolved`} />
            <Stat label="REALITY-WEIGHTED" value={fmtMW(summary.reality_mw)} sub={`${Math.round(pctReal * 100)}% of announced`} color={colors.emerald} />
            <Stat label="PHANTOM CAPACITY" value={fmtMW(phantomMw)} sub="announced × (1 − reality score)" color="#c4b5fd" />
            <Stat label="CLAIMS VERIFIED" value={summary.claims_verified_pct != null ? `${summary.claims_verified_pct}%` : '—'} sub={`${summary.mentions} mentions from ${summary.articles.extracted} articles read`} color={colors.secondary} />
          </div>
        )}

        {/* Globe + who to call */}
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.5fr) minmax(0, 1fr)', gap: 16, marginBottom: 16 }}>
          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <div style={{ fontWeight: 600 }}>🌏 Reality Globe</div>
              <select value={country} onChange={(e) => setCountry(e.target.value)} style={{ background: colors.bgInput, color: colors.text, border: `1px solid ${colors.border}`, borderRadius: 8, padding: '4px 8px' }}>
                <option value="">All countries</option><option>India</option><option>Malaysia</option>
              </select>
            </div>
            <RealityGlobe projects={projects} onPick={(id) => nav(`/phantom/${id}`)} />
          </div>
          <div style={card}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>📞 Who to call this month</div>
            <div style={{ fontSize: 12, color: colors.textDim, marginBottom: 10 }}>Real × open opportunity × right timing (specs are set 12–18 months before ground-break)</div>
            <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
              {SEGMENTS.map((s) => (
                <button key={s.key} onClick={() => setSegment(s.key)} style={{ padding: '4px 10px', borderRadius: 20, fontSize: 12, cursor: 'pointer', border: `1px solid ${segment === s.key ? colors.secondary : colors.border}`, background: segment === s.key ? 'rgba(6,182,212,0.15)' : 'transparent', color: segment === s.key ? '#fff' : colors.textMuted }}>{s.label}</button>
              ))}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 400, overflowY: 'auto' }}>
              {calls.length === 0 && <div style={{ color: colors.textDim, fontSize: 13 }}>No projects ranked yet.</div>}
              {calls.map((p, i) => (
                <div key={p.id} onClick={() => nav(`/phantom/${p.id}`)} style={{ padding: '10px 12px', borderRadius: 10, border: `1px solid ${colors.border}`, cursor: 'pointer', background: i === 0 ? 'rgba(124,58,237,0.08)' : 'transparent' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                    <div style={{ fontWeight: 600, fontSize: 13.5 }}>{i + 1}. {p.name}</div>
                    <div style={{ fontFamily: mono, fontSize: 12, color: colors.amber }}>{p.priority}</div>
                  </div>
                  <div style={{ fontSize: 11.5, color: colors.textDim, marginTop: 3 }}>{fmtMW(p.capacity_mw)} · {p.city || p.country} · <ScorePill s={p.reality_score} /></div>
                  <div style={{ fontSize: 11.5, color: colors.textMuted, marginTop: 4 }}>{(p.reasons || []).join(' · ')}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* By region + stage funnel */}
        {summary && (
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 16, marginBottom: 16 }}>
            <div style={card}>
              <div style={{ fontWeight: 600, marginBottom: 12 }}>📍 Announced vs real, by place</div>
              {summary.by_state.slice(0, 9).map((s) => {
                const max = summary.by_state[0]?.announced_mw || 1;
                return (
                  <div key={s.place} style={{ marginBottom: 9 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5 }}>
                      <span>{s.place} <span style={{ color: colors.textDim }}>· {s.projects}</span></span>
                      <span style={{ fontFamily: mono, color: colors.textMuted }}>{fmtMW(s.reality_mw)} / {fmtMW(s.announced_mw)}</span>
                    </div>
                    <div style={{ height: 8, background: 'rgba(196,181,253,0.15)', borderRadius: 4, marginTop: 4, width: `${(100 * s.announced_mw) / max}%`, position: 'relative' }}>
                      <div style={{ position: 'absolute', inset: 0, width: `${s.announced_mw ? (100 * s.reality_mw) / s.announced_mw : 0}%`, background: 'linear-gradient(90deg,#10b981,#06b6d4)', borderRadius: 4 }} />
                    </div>
                  </div>
                );
              })}
            </div>
            <div style={card}>
              <div style={{ fontWeight: 600, marginBottom: 12 }}>🪜 Evidence ladder — where projects really are</div>
              {LADDER.map((l) => {
                const n = summary.stages[l] || 0;
                const max = Math.max(1, ...Object.values(summary.stages));
                return (
                  <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 9 }}>
                    <div style={{ width: 90 }}><StagePill stage={l} /></div>
                    <div style={{ flex: 1, height: 14, background: 'rgba(255,255,255,0.04)', borderRadius: 4 }}>
                      <div style={{ width: `${(100 * n) / max}%`, height: '100%', background: STAGE_COLORS[l], borderRadius: 4, opacity: 0.85 }} />
                    </div>
                    <div style={{ width: 30, textAlign: 'right', fontFamily: mono, fontSize: 12 }}>{n}</div>
                  </div>
                );
              })}
              <div style={{ fontSize: 11.5, color: colors.textDim, marginTop: 10 }}>
                {summary.articles.total} articles collected ({summary.articles.full_text} full text, {summary.articles.headline_only} headline-only) · {summary.articles.relevant} relevant · anomalies: {Object.entries(summary.anomalies).map(([k, v]) => `${v} ${k.replace('_', ' ')}`).join(', ') || 'none'}
              </div>
            </div>
          </div>
        )}

        {/* Latest signals + anomaly watch */}
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.5fr) minmax(0,1fr)', gap: 16, marginBottom: 16 }}>
          <div style={card}>
            <div style={{ fontWeight: 600, marginBottom: 10 }}>📡 Latest verified signals <span style={{ fontSize: 11.5, color: colors.textDim, fontWeight: 400 }}>— what changed, newest first</span></div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9, maxHeight: 330, overflowY: 'auto' }}>
              {signals.length === 0 && <div style={{ color: colors.textDim, fontSize: 13 }}>No signals yet.</div>}
              {signals.map((s, i) => (
                <div key={i} onClick={() => nav(`/phantom/${s.project_id}`)} style={{ cursor: 'pointer', borderLeft: `3px solid ${STAGE_COLORS[s.layer] || '#94a3b8'}`, paddingLeft: 10 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12.5 }}>
                    <StagePill stage={s.layer} /><b>{s.project}</b>
                    <span style={{ color: colors.textDim, fontSize: 11.5 }}>{s.date?.slice(0, 10)} · {s.source}</span>
                  </div>
                  <div style={{ fontSize: 12.5, color: colors.textMuted, marginTop: 3 }}>“{s.quote}”</div>
                </div>
              ))}
            </div>
          </div>
          <div style={card}>
            <div style={{ fontWeight: 600, marginBottom: 10 }}>🚨 Anomaly Watch</div>
            {alerts.length === 0 && <div style={{ color: colors.textDim, fontSize: 13 }}>Nothing unusual detected across the tracked projects.</div>}
            {alerts.map((a, i) => (
              <div key={i} onClick={() => nav(`/phantom/${a.project_id}`)} style={{ cursor: 'pointer', fontSize: 12.5, marginBottom: 9, display: 'flex', gap: 8 }}>
                <span style={{ fontFamily: mono, fontSize: 10, color: a.severity === 'high' ? colors.error : a.severity === 'medium' ? colors.amber : colors.textDim, border: '1px solid currentColor', borderRadius: 5, padding: '1px 6px', height: 'fit-content' }}>{a.severity.toUpperCase()}</span>
                <span><b>{a.project}</b> — {a.message}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Ask the tracker + hunt log */}
        <div style={{ display: 'grid', gridTemplateColumns: huntLog.length ? 'minmax(0,1.4fr) minmax(0,1fr)' : '1fr', gap: 16, marginBottom: 16 }}>
          <div style={card}>
            <div style={{ fontWeight: 600, marginBottom: 10 }}>💬 Ask the Tracker <span style={{ fontSize: 11.5, color: colors.textDim, fontWeight: 400 }}>— every answer cites its sources</span></div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && ask()} placeholder="e.g. Which Johor projects are most likely real? Who should a transformer supplier call?"
                style={{ flex: 1, padding: '0.6rem 0.8rem', background: colors.bgInput, color: colors.text, border: `1px solid ${colors.border}`, borderRadius: radii.md, fontSize: 13.5 }} />
              <button onClick={ask} disabled={asking} style={{ padding: '0.6rem 1rem', borderRadius: radii.md, border: 'none', background: 'linear-gradient(135deg,#7c3aed,#06b6d4)', color: '#fff', fontWeight: 600, cursor: 'pointer' }}>{asking ? 'Thinking…' : 'Ask'}</button>
            </div>
            {answer && (
              <div style={{ marginTop: 12, fontSize: 13.5, lineHeight: 1.6 }}>
                <div>{answer.answer}</div>
                {answer.sources.length > 0 && (
                  <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {answer.sources.map((s) => (
                      <div key={s.id} style={{ fontSize: 12, color: colors.textMuted }}>
                        <b style={{ color: colors.secondary }}>[{s.id}]</b>{' '}
                        <span style={{ cursor: 'pointer', textDecoration: 'underline' }} onClick={() => nav(`/phantom/${s.project_id}`)}>{s.name}</span>
                        {s.url && <> · <a href={s.url} target="_blank" rel="noreferrer" style={{ color: colors.textDim }}>{s.title?.slice(0, 70)}</a></>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
          {huntLog.length > 0 && (
            <div style={{ ...card, fontFamily: mono, fontSize: 11.5, color: colors.textMuted, maxHeight: 260, overflowY: 'auto' }}>
              <div style={{ fontWeight: 600, color: colors.white, marginBottom: 8, fontFamily: typography.fontFamily }}>🛰️ Live hunt</div>
              {huntLog.map((l, i) => <div key={i} style={{ marginBottom: 3 }}>{l}</div>)}
            </div>
          )}
        </div>

        {/* How it works */}
        <div style={{ ...card, marginBottom: 16 }}>
          <div style={{ fontWeight: 600, marginBottom: 12 }}>🧭 How Phantom Hunter works</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 12 }}>
            {[
              ['🛰️ Scouts', 'Search Bing News, Google News and GDELT per city and developer; fetch articles politely (robots.txt, honest identity, rate-limited).'],
              ['🧾 Extractor', 'A local LLM (qwen2.5:7b) turns each article into projects, capacity and stage events — every claim with its quote.'],
              ['⛏ Evidence Miner', 'Deterministic rules find precise stage language ("broke ground", "commissioned") in sentences about the project; future tense never counts.'],
              ['✅ Verifier', 'No LLM: every quote must exist in the article, numbers must parse, and a stage quote must actually describe that stage.'],
              ['🧩 Resolver', 'Merges "same project, different names" using facility codes, developer aliases, place and capacity agreement.'],
              ['🧮 Scorer', 'Transparent log-odds reality score on the evidence ladder, the weakest assumption, anomalies and who-to-call per segment.'],
            ].map(([t, d]) => (
              <div key={t} style={{ padding: 12, borderRadius: 12, border: `1px solid ${colors.border}`, background: 'rgba(255,255,255,0.015)' }}>
                <div style={{ fontWeight: 600, fontSize: 13.5, marginBottom: 6 }}>{t}</div>
                <div style={{ fontSize: 12.5, color: colors.textMuted, lineHeight: 1.55 }}>{d}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 12, color: colors.textDim, marginTop: 10 }}>
            "Power" means secured — a PPA, grid connection or substation — never just a mention of power. Scores are stated priors anchored to public market data, not yet calibrated against outcomes.
          </div>
        </div>

        {/* Project table */}
        <div style={card}>
          <div style={{ fontWeight: 600, marginBottom: 10 }}>🗂️ All projects <span style={{ color: colors.textDim, fontWeight: 400, fontSize: 12 }}>({projects.length}, sorted by reality-weighted MW)</span></div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ color: colors.textDim, fontSize: 11, textAlign: 'left', fontFamily: mono }}>
                  {['PROJECT', 'DEVELOPER', 'WHERE', 'MW', 'STAGE', 'REALITY', 'SOURCES', 'WEAKEST ASSUMPTION'].map((h) => <th key={h} style={{ padding: '6px 8px', borderBottom: `1px solid ${colors.border}` }}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.id} onClick={() => nav(`/phantom/${p.id}`)} style={{ cursor: 'pointer', borderBottom: `1px solid ${colors.border}` }}>
                    <td style={{ padding: '8px', fontWeight: 600 }}>{p.name}{p.ai_density && <span title="built for AI / high density" style={{ marginLeft: 6 }}>🧠</span>}</td>
                    <td style={{ padding: '8px', color: colors.textMuted }}>{p.developer || '—'}</td>
                    <td style={{ padding: '8px', color: colors.textMuted }}>{p.city || p.state || p.country || '—'}</td>
                    <td style={{ padding: '8px', fontFamily: mono }}>{fmtMW(p.capacity_mw)}</td>
                    <td style={{ padding: '8px' }}><StagePill stage={p.stage_name} /></td>
                    <td style={{ padding: '8px' }}><ScorePill s={p.reality_score} /></td>
                    <td style={{ padding: '8px', fontFamily: mono, color: colors.textMuted }}>{p.n_sources}</td>
                    <td style={{ padding: '8px', color: colors.textDim, fontSize: 12, maxWidth: 360 }}>{p.weakest_assumption}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
