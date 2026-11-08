/**
 * Phantom Hunter — project dossier
 *
 * The evidence ladder, every verified quote linked to its article, the score
 * breakdown term by term, the weakest assumption, anomalies, who-to-call per
 * segment, the Bull vs Bear debate, and the verifier's verdict on every claim.
 */
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout';
import { colors, radii } from '../styles/tokens';
import { phantom, fmtMW, scoreColor, STAGE_COLORS, type ProjectDetail } from '../services/phantom';
import { ScorePill, StagePill } from './PhantomHunter';

const card: React.CSSProperties = { background: colors.bgCard, border: `1px solid ${colors.border}`, borderRadius: radii.lg, padding: '1.25rem' };
const mono = "'JetBrains Mono', monospace";
const H = ({ children }: { children: React.ReactNode }) => <div style={{ fontWeight: 600, marginBottom: 12 }}>{children}</div>;

function Gauge({ s }: { s: number }) {
  const c = scoreColor(s), a = Math.PI * s;
  const x = 60 - 50 * Math.cos(a), y = 60 - 50 * Math.sin(a);
  return (
    <svg width="120" height="72" viewBox="0 0 120 72" aria-label={`reality score ${Math.round(s * 100)}%`}>
      <path d="M10 60 A50 50 0 0 1 110 60" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="10" strokeLinecap="round" />
      <path d={`M10 60 A50 50 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}`} fill="none" stroke={c} strokeWidth="10" strokeLinecap="round" />
      <text x="60" y="58" textAnchor="middle" fill="#fff" fontSize="22" fontWeight="700" fontFamily="Space Grotesk">{Math.round(s * 100)}%</text>
    </svg>
  );
}

export default function PhantomProject() {
  const { id } = useParams();
  const nav = useNavigate();
  const [p, setP] = useState<ProjectDetail | null>(null);
  const [err, setErr] = useState('');
  const [debating, setDebating] = useState(false);
  const [showChecks, setShowChecks] = useState(false);

  useEffect(() => { if (id) phantom.project(id).then(setP).catch((e) => setErr(e.message)); }, [id]);

  const runDebate = async (refresh = false) => {
    if (!id) return;
    setDebating(true);
    try { const d = await phantom.debate(id, refresh); setP((x) => (x ? { ...x, debate: d } : x)); } catch (e) { setErr((e as Error).message); }
    setDebating(false);
  };

  if (err) return <DashboardLayout><div style={{ ...card, color: colors.error }}>{err}</div></DashboardLayout>;
  if (!p) return <DashboardLayout><div style={{ color: colors.textMuted }}>Loading dossier…</div></DashboardLayout>;

  const evId = (i: number) => `E${i + 1}`;
  const verdictColor = p.debate ? (p.debate.verdict === 'LIKELY BUILT' ? colors.emerald : p.debate.verdict === 'LIKELY PHANTOM' ? colors.error : colors.amber) : colors.textMuted;

  return (
    <DashboardLayout>
      <div style={{ maxWidth: 1180, margin: '0 auto' }}>
        <button onClick={() => nav('/phantom')} style={{ background: 'none', border: 'none', color: colors.textMuted, cursor: 'pointer', marginBottom: 10 }}>← All projects</button>

        {/* Header */}
        <div style={{ ...card, display: 'flex', gap: 20, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
          <Gauge s={p.reality_score} />
          <div style={{ flex: 1, minWidth: 280 }}>
            <div style={{ fontFamily: mono, fontSize: 11, color: colors.secondary, letterSpacing: '0.15em' }}>REALITY SCORE · PROBABILITY IT GETS BUILT</div>
            <h1 style={{ margin: '4px 0', fontSize: '1.7rem', fontFamily: "'Space Grotesk', sans-serif" }}>{p.name}</h1>
            <div style={{ color: colors.textMuted, fontSize: 14 }}>
              {p.developer || 'Developer unknown'} · {[p.city, p.state, p.country].filter(Boolean).join(', ') || 'location unknown'} ·{' '}
              <b style={{ color: '#fff' }}>{fmtMW(p.capacity_mw)}</b>{p.capacity_basis && p.capacity_basis !== 'unknown' ? ` (${p.capacity_basis})` : ''} ·{' '}
              target {p.target_year || 'not stated'} · power partner {p.power_partner || 'none named'}
              {p.ai_density && ' · 🧠 built for AI'}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontFamily: mono, fontSize: 11, color: colors.textDim }}>REALITY-WEIGHTED</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 700, color: scoreColor(p.reality_score) }}>{fmtMW(p.reality_mw)}</div>
            <div style={{ fontSize: 12, color: colors.textDim }}>{p.n_sources} source{p.n_sources === 1 ? '' : 's'}</div>
          </div>
        </div>

        {/* Weakest assumption */}
        <div style={{ ...card, borderColor: 'rgba(245,158,11,0.4)', background: 'rgba(245,158,11,0.06)', marginBottom: 16 }}>
          <div style={{ fontFamily: mono, fontSize: 11, color: colors.amber, letterSpacing: '0.15em' }}>⚠ WEAKEST ASSUMPTION</div>
          <div style={{ marginTop: 6, fontSize: 15 }}>{p.weakest_assumption}</div>
        </div>

        {/* Ladder */}
        <div style={{ ...card, marginBottom: 16 }}>
          <H>🪜 Evidence ladder</H>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            {p.ladder.map((l, i) => {
              const c = STAGE_COLORS[l.layer];
              return (
                <div key={l.layer} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{ padding: '8px 12px', borderRadius: 10, border: `1px solid ${l.verified ? c : colors.border}`, background: l.verified ? `${c}22` : 'transparent', color: l.verified ? '#fff' : colors.textDark, fontFamily: mono, fontSize: 12 }}>
                    {l.verified ? '✓' : '○'} {l.layer}
                  </div>
                  {i < p.ladder.length - 1 && <span style={{ color: colors.textDark }}>→</span>}
                </div>
              );
            })}
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.35fr) minmax(0,1fr)', gap: 16, marginBottom: 16 }}>
          {/* Evidence */}
          <div style={card}>
            <H>🧾 Verified evidence <span style={{ fontSize: 11.5, color: colors.textDim, fontWeight: 400 }}>— every quote is checked against its article</span></H>
            {p.evidence.length === 0 && <div style={{ color: colors.textDim, fontSize: 13 }}>No verified stage evidence yet — only the announcement itself.</div>}
            {p.evidence.map((e, i) => (
              <div key={i} style={{ borderLeft: `3px solid ${STAGE_COLORS[e.layer] || '#94a3b8'}`, padding: '6px 0 6px 12px', marginBottom: 12 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <b style={{ fontFamily: mono, fontSize: 12, color: colors.textDim }}>{evId(i)}</b><StagePill stage={e.layer} />
                  <span style={{ fontSize: 11.5, color: colors.textDim }}>{e.date?.slice(0, 10)}</span>
                </div>
                <div style={{ fontSize: 13.5, marginTop: 5, lineHeight: 1.55 }}>“{e.quote}”</div>
                {e.article && (
                  <a href={e.article.url} target="_blank" rel="noreferrer" style={{ fontSize: 11.5, color: colors.secondary }}>
                    {e.article.source} — {e.article.title.slice(0, 90)}{e.article.text_kind === 'summary' ? ' (headline only)' : ''} ↗
                  </a>
                )}
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Score breakdown */}
            <div style={card}>
              <H>🧮 Why this score <span style={{ fontSize: 11.5, color: colors.textDim, fontWeight: 400 }}>— a transparent log-odds model</span></H>
              {p.score_breakdown.map((b, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '6px 0', borderBottom: `1px solid ${colors.border}`, fontSize: 13 }}>
                  <div><div>{b.term}</div><div style={{ fontSize: 11.5, color: colors.textDim }}>{b.why}</div></div>
                  <div style={{ fontFamily: mono, color: b.delta == null ? '#fff' : b.delta > 0 ? colors.emerald : colors.error, whiteSpace: 'nowrap' }}>
                    {b.delta == null ? `prior ${Math.round((b.value || 0) * 100)}%` : `${b.delta > 0 ? '+' : ''}${b.delta} logit`}
                  </div>
                </div>
              ))}
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontWeight: 600 }}><span>Reality score</span><ScorePill s={p.reality_score} /></div>
            </div>

            {/* Anomalies */}
            <div style={card}>
              <H>🚨 Anomaly Watch</H>
              {p.anomalies.length === 0 && <div style={{ color: colors.textDim, fontSize: 13 }}>Nothing unusual detected.</div>}
              {p.anomalies.map((a, i) => (
                <div key={i} style={{ fontSize: 13, marginBottom: 8, display: 'flex', gap: 8 }}>
                  <span style={{ fontFamily: mono, fontSize: 10.5, color: a.severity === 'high' ? colors.error : a.severity === 'medium' ? colors.amber : colors.textDim, border: '1px solid currentColor', borderRadius: 5, padding: '1px 6px', height: 'fit-content' }}>{a.severity.toUpperCase()}</span>
                  <span>{a.message}</span>
                </div>
              ))}
            </div>

            {/* Who to call */}
            <div style={card}>
              <H>📞 Who should call this project</H>
              {Object.entries(p.call_segments || {}).sort((a, b) => b[1].priority - a[1].priority).map(([k, s]) => (
                <div key={k} style={{ marginBottom: 10 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}><span>{s.segment}</span><b style={{ fontFamily: mono, color: colors.amber }}>{s.priority}</b></div>
                  <div style={{ height: 5, background: 'rgba(255,255,255,0.05)', borderRadius: 3, margin: '4px 0' }}><div style={{ width: `${s.priority}%`, height: '100%', background: colors.amber, borderRadius: 3 }} /></div>
                  <div style={{ fontSize: 11.5, color: colors.textDim }}>{s.reasons.join(' · ')}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Debate */}
        <div style={{ ...card, marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ fontWeight: 600 }}>⚔️ Bull vs Bear <span style={{ fontSize: 11.5, color: colors.textDim, fontWeight: 400 }}>— two agents argue from the evidence only; uncited claims are discarded</span></div>
            <button onClick={() => runDebate(!!p.debate)} disabled={debating || p.evidence.length === 0} style={{ padding: '0.45rem 0.9rem', borderRadius: radii.md, border: `1px solid ${colors.borderLight}`, background: 'rgba(124,58,237,0.2)', color: '#fff', cursor: 'pointer' }}>
              {debating ? 'Agents debating…' : p.debate ? '↻ Re-run debate' : '▶ Run debate'}
            </button>
          </div>
          {p.debate ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                {[['🐂 BULL — it will be built', p.debate.bull, colors.emerald], ['🐻 BEAR — it is at risk', p.debate.bear, colors.error]].map(([title, pts, c]) => (
                  <div key={title as string} style={{ border: `1px solid ${(c as string)}44`, borderRadius: 12, padding: 12 }}>
                    <div style={{ fontFamily: mono, fontSize: 12, color: c as string, marginBottom: 8 }}>{title as string}</div>
                    {(pts as { claim: string; cites: string[]; from_missing_evidence?: boolean }[]).map((pt, i) => (
                      <div key={i} style={{ fontSize: 13, marginBottom: 8, lineHeight: 1.5 }}>
                        • {pt.claim} <span style={{ fontFamily: mono, fontSize: 11, color: colors.textDim }}>{pt.cites.length ? `[${pt.cites.join(', ')}]` : pt.from_missing_evidence ? '[missing evidence]' : ''}</span>
                      </div>
                    ))}
                    {(pts as unknown[]).length === 0 && <div style={{ fontSize: 12.5, color: colors.textDim }}>No cited arguments survived.</div>}
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 14, padding: 12, borderRadius: 12, background: `${verdictColor}14`, border: `1px solid ${verdictColor}55` }}>
                <div style={{ fontFamily: mono, fontSize: 12, color: verdictColor }}>⚖️ JUDGE: {p.debate.verdict}</div>
                <div style={{ fontSize: 13.5, marginTop: 6 }}>{p.debate.reasoning}</div>
                <div style={{ fontSize: 12.5, color: colors.textMuted, marginTop: 6 }}><b>Watch for:</b> {p.debate.watch_for}</div>
              </div>
            </>
          ) : (
            <div style={{ color: colors.textDim, fontSize: 13 }}>Not debated yet. The debate explains the score; it never changes it.</div>
          )}
        </div>

        {/* How we checked */}
        <div style={card}>
          <div onClick={() => setShowChecks((s) => !s)} style={{ fontWeight: 600, cursor: 'pointer' }}>
            {showChecks ? '▾' : '▸'} 🔍 How every claim was checked ({p.mentions.length} mention{p.mentions.length === 1 ? '' : 's'})
          </div>
          {showChecks && p.mentions.map((m, i) => (
            <div key={i} style={{ marginTop: 12, paddingTop: 10, borderTop: `1px solid ${colors.border}` }}>
              <div style={{ fontSize: 12.5 }}>
                {m.article ? <a href={m.article.url} target="_blank" rel="noreferrer" style={{ color: colors.secondary }}>{m.article.source}: {m.article.title.slice(0, 90)} ↗</a> : 'article'}
                <span style={{ color: colors.textDim }}> · {Math.round(m.verified_ratio * 100)}% of claims verified</span>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                {Object.entries(m.verification).filter(([k, v]) => k !== 'events' && k !== 'mined' && v && typeof v === 'object').map(([k, v]: [string, any]) => (
                  <span key={k} title={v.why} style={{ fontFamily: mono, fontSize: 11, padding: '2px 7px', borderRadius: 6, border: `1px solid ${v.ok ? colors.emerald : colors.error}66`, color: v.ok ? colors.emerald : colors.error }}>
                    {v.ok ? '✓' : '✗'} {k}
                  </span>
                ))}
                {(m.verification.events || []).map((e: any, j: number) => (
                  <span key={`e${j}`} title={e.why} style={{ fontFamily: mono, fontSize: 11, padding: '2px 7px', borderRadius: 6, border: `1px solid ${e.ok ? colors.emerald : colors.error}66`, color: e.ok ? colors.emerald : colors.error }}>
                    {e.ok ? '✓' : '✗'} event:{e.layer}
                  </span>
                ))}
                {(m.verification.mined || []).map((l: string, j: number) => (
                  <span key={`m${j}`} style={{ fontFamily: mono, fontSize: 11, padding: '2px 7px', borderRadius: 6, border: `1px solid ${colors.secondary}66`, color: colors.secondary }}>⛏ mined:{l}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </DashboardLayout>
  );
}
