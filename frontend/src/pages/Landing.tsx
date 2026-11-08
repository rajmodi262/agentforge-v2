import React, { useRef, useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import Scene from '../canvas/Scene';
import Navbar from '../components/Navbar';
import CustomCursor from '../components/CustomCursor';
import ScrollProgress from '../components/ScrollProgress';
import Preloader from '../components/Preloader';
import MagneticButton from '../components/MagneticButton';
import CountUp from '../components/CountUp';
import ClipReveal, { DashboardPreview } from '../components/ClipReveal';
import MagnifierLens from '../components/MagnifierLens';
import TextScramble from '../components/TextScramble';
import InfiniteMarquee from '../components/InfiniteMarquee';
import TiltCard from '../components/TiltCard';
import ParticleTrail from '../components/ParticleTrail';
import SplitTextReveal from '../components/SplitTextReveal';
import DynamicIsland from '../components/DynamicIsland';
import HoverScramble from '../components/HoverScramble';
import { API_BASE } from '../services/api';
import VelocityWrapper from '../components/VelocityWrapper';
import CodePreview from '../components/CodePreview';
import DataFlowLines from '../components/DataFlowLines';
import FluidText from '../components/FluidText';
import { AGENTS, STATS, TESTIMONIALS, TERMINAL_LINES } from '../utils/constants';
import { useInView } from '../hooks/useInView';
import { useMousePosition } from '../hooks/useMousePosition';
import { useWorkflowSocket } from '../hooks/useWorkflowSocket';
import { createProject, startWorkflow } from '../services/api';
import TemplateGallery from '../components/TemplateGallery';

gsap.registerPlugin(ScrollTrigger);

const TECH_BADGES = [
  { text: 'React 19', icon: '⚛️' },
  { text: 'Three.js', icon: '🔮' },
  { text: 'Claude AI', icon: '🧠' },
  { text: 'WebSocket', icon: '⚡' },
  { text: 'FastAPI', icon: '🐍' },
  { text: 'PostgreSQL', icon: '🐘' },
  { text: 'GSAP', icon: '🎭' },
  { text: 'WebGL', icon: '💎' },
  { text: 'Docker', icon: '🐳' },
  { text: 'TypeScript', icon: '📘' },
  { text: 'Framer Motion', icon: '🎬' },
  { text: 'Lenis', icon: '🌊' },
];

export default function Landing() {
  const [loaded, setLoaded] = useState(false);
  const [scrollProgress, setScrollProgress] = useState(0);
  const [activeAgent, setActiveAgent] = useState(-1);
  const [showScene, setShowScene] = useState(false);
  const [thermalProgress, setThermalProgress] = useState(0);
  const [magnifierActive, setMagnifierActive] = useState(false);
  const [businessIdea, setBusinessIdea] = useState('');
  const [isLaunching, setIsLaunching] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const mousePos = useMousePosition();
  const workflow = useWorkflowSocket();

  const handleLaunch = useCallback(async (idea: string) => {
    if (!idea.trim() || isLaunching) return;
    setIsLaunching(true);
    try {
      const project = await createProject({ title: idea.slice(0, 80), business_idea: idea });
      const { workflow_id } = await startWorkflow(project.id);
      workflow.connect(workflow_id);
      // Immediately bring the live agent stream into view so the click has
      // obvious feedback (the pipeline renders in a section further down).
      // Native scrollIntoView doesn't work under Lenis — use its scrollTo.
      setTimeout(() => {
        const lenis = (window as unknown as { __lenis?: { scrollTo: (t: string, o?: object) => void } }).__lenis;
        if (lenis?.scrollTo) lenis.scrollTo('#live-stream', { offset: -80, duration: 1.4 });
        else document.getElementById('live-stream')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 150);
    } catch (err) {
      console.error('Launch failed:', err);
    } finally {
      setIsLaunching(false);
    }
  }, [isLaunching, workflow]);

  const handlePreloaderComplete = useCallback(() => {
    setLoaded(true);
    setShowScene(true);
  }, []);

  const scrollToSection = useCallback((id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  useEffect(() => {
    if (!loaded) return;
    const trigger = ScrollTrigger.create({
      trigger: containerRef.current,
      start: 'top top',
      end: 'bottom bottom',
      onUpdate: (self) => {
        setScrollProgress(self.progress);
        const ap = self.progress * 10;
        setActiveAgent(Math.min(Math.floor(ap) - 1, 6));
        if (self.progress > 0.35 && self.progress < 0.5) {
          setThermalProgress(Math.min((self.progress - 0.35) / 0.1, 1));
        } else if (self.progress >= 0.5) {
          setThermalProgress(Math.max(1 - (self.progress - 0.5) / 0.05, 0));
        } else {
          setThermalProgress(0);
        }
        setMagnifierActive(self.progress > 0.18 && self.progress < 0.28);
      },
    });
    return () => trigger.kill();
  }, [loaded]);

  return (
    <>
      <AnimatePresence>
        {!loaded && <Preloader onComplete={handlePreloaderComplete} />}
      </AnimatePresence>
      <div className="landing-container" style={{ background: 'var(--void)', minHeight: '100vh', color: 'var(--text-primary)', cursor: 'none' }}>
        <CustomCursor />
        <ParticleTrail />
        <ScrollProgress progress={scrollProgress} />
        <DynamicIsland
          workflowStatus={workflow.status}
          currentAgent={workflow.currentAgent}
          completedCount={workflow.completedAgents.length}
          mode={workflow.mode}
        />
        <Navbar scrollProgress={scrollProgress} />
        <Scene
          scrollProgress={scrollProgress}
          activeAgent={activeAgent}
          thermalProgress={thermalProgress}
          mousePosition={mousePos}
          visible={showScene}
        />
        <MagnifierLens active={magnifierActive} />
        <VelocityWrapper>
          <div ref={containerRef} className="content-layer">
            <HeroSection onGetStarted={() => scrollToSection('launch')} onWatchDemo={() => scrollToSection('agents')} />
            <MarqueeSection />
            <AgentsSection activeAgent={activeAgent} />
            <ThermalVisionSection thermalProgress={thermalProgress} />
            <InputSection
              businessIdea={businessIdea}
              setBusinessIdea={setBusinessIdea}
              onLaunch={handleLaunch}
              isLaunching={isLaunching}
              workflowStatus={workflow.status}
              downloadUrl={workflow.downloadUrl}
            />
            <AgentDiveSection
              liveLines={workflow.terminalLines}
              workflowStatus={workflow.status}
            />
            <div id="clip-trigger" style={{ height: '150vh', position: 'relative' }}>
              <ClipReveal triggerSelector="#clip-trigger" startOffset="top center" endOffset="bottom center">
                <DashboardPreview />
              </ClipReveal>
            </div>
            <OutputSection completedAgents={workflow.completedAgents} />
            <ProofSection />
            <CTASection onGetStarted={() => scrollToSection('launch')} />
            <Footer />
          </div>
        </VelocityWrapper>
      </div>
    </>
  );
}

/* ─── HERO with SplitTextReveal ─── */
function HeroSection({ onGetStarted, onWatchDemo }: { onGetStarted: () => void; onWatchDemo: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <section ref={ref} className="scroll-section section-hero" id="platform">
      <div style={{ position: 'relative', zIndex: 2, maxWidth: '900px' }}>
        <motion.div className="mono-label" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 2.8, duration: 0.6 }} style={{ color: 'var(--primary)', marginBottom: 'var(--space-lg)' }}>
          ⚡ Powered by Seven AI Agents
        </motion.div>

        <SplitTextReveal
          text="Your Startup. Seven AI Minds. One Blueprint."
          className="display-xl"
          tag="h1"
          delay={3.0}
          staggerDelay={0.025}
          highlightWords={['Seven', 'AI', 'Minds.']}
        />

        <motion.p className="body-lg" style={{ color: 'var(--text-secondary)', maxWidth: '580px', margin: 'var(--space-xl) auto 0', textAlign: 'center' }} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 4.2, duration: 0.8 }}>
          Drop your business idea into the neural core. Seven specialized AI agents will dissect, analyze, strategize, and build your complete business blueprint — in under two minutes.
        </motion.p>
        <motion.div className="section-hero__cta-group" style={{ justifyContent: 'center' }} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 4.6, duration: 0.8 }}>
          <MagneticButton onClick={onGetStarted}>Launch Your Blueprint →</MagneticButton>
          <MagneticButton variant="outline" onClick={onWatchDemo}>Watch Demo</MagneticButton>
        </motion.div>
      </div>
      <motion.div className="section-hero__scroll-hint" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 5.2, duration: 1 }}>
        <span>Scroll to explore</span>
        <motion.div animate={{ y: [0, 8, 0] }} transition={{ repeat: Infinity, duration: 1.5, ease: 'easeInOut' }} style={{ fontSize: '18px' }}>↓</motion.div>
      </motion.div>
    </section>
  );
}

/* ─── INFINITE MARQUEE BANNER ─── */
function MarqueeSection() {
  return (
    <div className="marquee-section" style={{ background: 'var(--void)' }}>
      <InfiniteMarquee items={TECH_BADGES} speed={25} direction="left" />
    </div>
  );
}

/* ─── AGENTS with TextScramble headings ─── */
function AgentsSection({ activeAgent }: { activeAgent: number }) {
  const [ref, isInView] = useInView();

  return (
    <section ref={ref} className="scroll-section" id="agents" style={{ minHeight: '120vh', flexDirection: 'column', gap: 'var(--space-3xl)', padding: 'var(--space-4xl) var(--space-2xl)' }}>
      <motion.div className="text-center" initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true, margin: '-100px' }} transition={{ duration: 0.8 }}>
        <div className="mono-label" style={{ marginBottom: 'var(--space-md)', color: 'var(--secondary)' }}>The Neural Pipeline</div>
        <TextScramble text="Seven Minds. One Mission." trigger={isInView} className="display-lg" tag="h2" />
      </motion.div>
      <div className="agents-grid">
        {AGENTS.map((agent, i) => (
          <motion.div key={agent.id} className="agent-node" initial={{ opacity: 0, y: 30, scale: 0.8 }} whileInView={{ opacity: 1, y: 0, scale: 1 }} viewport={{ once: true }} transition={{ delay: i * 0.1, duration: 0.6, ease: [0.25, 1, 0.5, 1] }}>
            <div className={`agent-node__circle ${i <= activeAgent ? 'agent-node__circle--active' : ''}`} style={{ borderColor: i <= activeAgent ? agent.color : undefined, boxShadow: i <= activeAgent ? `0 0 20px ${agent.color}40, 0 0 40px ${agent.color}15` : undefined }}>{agent.icon}</div>
            <div className="agent-node__label" style={{ color: i <= activeAgent ? agent.color : undefined }}>{agent.name}</div>
            <motion.div className="mono-label" style={{ fontSize: '9px', color: agent.color, maxWidth: '100px', textAlign: 'center' }} animate={{ opacity: i <= activeAgent ? 1 : 0 }} transition={{ duration: 0.4 }}>{agent.label}</motion.div>
          </motion.div>
        ))}
      </div>
    </section>
  );
}

/* ─── THERMAL VISION ─── */
function ThermalVisionSection({ thermalProgress }: { thermalProgress: number }) {
  const isActive = thermalProgress > 0.1;
  return (
    <section className={`thermal-section scroll-section scan-lines ${isActive ? 'thermal-section--active' : ''}`} style={{ minHeight: '100vh', flexDirection: 'column', gap: 'var(--space-2xl)', padding: 'var(--space-4xl) var(--space-2xl)' }}>
      <motion.div className="text-center" initial={{ opacity: 0, y: 40 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.8 }}>
        <div className="mono-label" style={{ color: isActive ? '#ff4400' : 'var(--text-muted)', marginBottom: 'var(--space-md)', transition: 'color 0.5s' }}>
          {isActive ? '● THERMAL SCAN ACTIVE' : '○ THERMAL VISION'}
        </div>
        <h2 className="display-lg" style={{ transition: 'color 0.5s' }}>
          See What <span style={{ color: isActive ? '#ff4400' : undefined, transition: 'color 0.5s' }}>{isActive ? 'Burns Brightest' : 'Others Miss'}</span>
        </h2>
        <p className="body-md" style={{ maxWidth: '500px', margin: 'var(--space-lg) auto 0' }}>
          Thermal analysis maps activity density, data flow intensity, and strategic hotspots across your entire business model.
        </p>
      </motion.div>
      <motion.div className="text-center" initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true }} transition={{ delay: 0.4 }}>
        <div className={`thermal-toggle ${isActive ? 'thermal-toggle--active' : ''}`}>
          <span className="thermal-toggle__dot" />
          {isActive ? 'SCANNING...' : 'SCROLL TO ACTIVATE'}
        </div>
      </motion.div>
      {isActive && (
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="glass-card" style={{ maxWidth: '600px', width: '100%', margin: '0 auto', background: 'rgba(255,68,0,0.03)', borderColor: 'rgba(255,68,0,0.15)' }}>
          <div className="mono-label" style={{ color: '#ff4400', marginBottom: 'var(--space-md)' }}>THERMAL ANALYSIS</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 'var(--space-md)' }}>
            {[{ label: 'PEAK ACTIVITY', value: 'CEO Node', color: '#ff4400' }, { label: 'DATA FLOW', value: '847 MB/s', color: '#ffcc00' }, { label: 'SYNC RATE', value: '99.7%', color: '#00ffcc' }].map((d, i) => (
              <div key={i} style={{ textAlign: 'center' }}>
                <div style={{ fontFamily: "'Space Grotesk'", fontSize: '20px', fontWeight: 700, color: d.color }}>{d.value}</div>
                <div style={{ fontFamily: "'JetBrains Mono'", fontSize: '9px', color: 'rgba(255,255,255,0.4)', letterSpacing: '0.1em', marginTop: '4px' }}>{d.label}</div>
              </div>
            ))}
          </div>
        </motion.div>
      )}
    </section>
  );
}

/* ─── INPUT with editable text + launch button ─── */
interface InputSectionProps {
  businessIdea: string;
  setBusinessIdea: (val: string) => void;
  onLaunch: (val: string) => void;
  isLaunching: boolean;
  workflowStatus: string;
  downloadUrl?: string;
}

function InputSection({ businessIdea, setBusinessIdea, onLaunch, isLaunching, workflowStatus, downloadUrl }: InputSectionProps) {
  const [inViewRef, isInView] = useInView();
  const [typedText, setTypedText] = useState('');
  const fullText = 'An AI-powered sustainability analytics platform for enterprise carbon tracking...';
  const [hasTyped, setHasTyped] = useState(false);

  // Typewriter demo — only if user hasn't started typing
  useEffect(() => {
    if (!isInView || hasTyped) return;
    let i = 0;
    const interval = setInterval(() => {
      if (i < fullText.length) { setTypedText(fullText.slice(0, i + 1)); i++; } else clearInterval(interval);
    }, 45);
    return () => clearInterval(interval);
  }, [isInView, hasTyped]);

  const displayText = hasTyped ? businessIdea : typedText;
  const isRunning = workflowStatus === 'running' || workflowStatus === 'connecting';
  const isDone = workflowStatus === 'completed';

  const handleTemplateSelect = (prompt: string) => {
    setHasTyped(true);
    setBusinessIdea(prompt);
    // Auto scroll to text area or just set it
    const textarea = document.getElementById('idea-input');
    if (textarea) {
      textarea.focus();
      // Scroll into view if needed
      textarea.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  };

  return (
    <section className="scroll-section" id="launch" style={{ minHeight: '100vh', flexDirection: 'column', gap: 'var(--space-2xl)', padding: 'var(--space-4xl) var(--space-2xl)' }} ref={inViewRef}>
      <motion.div className="text-center" initial={{ opacity: 0, y: 30 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.8 }}>
        <SplitTextReveal text="Drop Your Vision Into The Machine" className="display-lg" tag="h2" highlightWords={['Into', 'The', 'Machine']} />
        <p className="body-md" style={{ maxWidth: '500px', margin: 'var(--space-lg) auto 0' }}>Every empire started with a single sentence.</p>
      </motion.div>
      <motion.div className="glass-card" style={{ maxWidth: '700px', width: '100%', margin: '0 auto', padding: 'var(--space-xl) var(--space-2xl)' }} initial={{ opacity: 0, y: 30, scale: 0.95 }} whileInView={{ opacity: 1, y: 0, scale: 1 }} viewport={{ once: true }} transition={{ delay: 0.3, duration: 0.8 }}>
        <div className="mono-label" style={{ marginBottom: 'var(--space-md)' }}>YOUR BUSINESS IDEA</div>
        <textarea
          id="idea-input"
          value={displayText}
          onChange={(e) => { setHasTyped(true); setBusinessIdea(e.target.value); }}
          onFocus={() => { if (!hasTyped) { setHasTyped(true); setBusinessIdea(typedText); } }}
          placeholder="Describe your startup idea here..."
          disabled={isRunning}
          style={{
            width: '100%', minHeight: '100px', background: 'transparent', border: 'none', outline: 'none',
            fontFamily: "'Inter'", fontSize: '18px', lineHeight: 1.7, color: 'var(--text-primary)', resize: 'vertical',
            cursor: isRunning ? 'not-allowed' : 'text', opacity: isRunning ? 0.6 : 1,
          }}
        />
      </motion.div>
      <motion.div className="text-center" initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true }} transition={{ delay: 0.6, duration: 0.8 }}>
        <MagneticButton
          onClick={() => onLaunch(displayText)}
          disabled={isLaunching || isRunning || isDone}
        >
          {isRunning ? '⚡ Pipeline Running...' : isDone ? '✓ Blueprint Generated' : isLaunching ? 'Initializing...' : 'Initialize Sequence →'}
        </MagneticButton>
        {isDone && downloadUrl && (
          <motion.a
            href={`${API_BASE.replace(/\/api\/v1$/, '')}${downloadUrl}`}
            target="_blank"
            rel="noopener noreferrer"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            style={{
              display: 'inline-block', marginTop: 'var(--space-md)', padding: '14px 28px', borderRadius: 12,
              background: 'var(--gradient-aura)', color: 'var(--text-primary)', textDecoration: 'none',
              fontFamily: "'Space Grotesk'", fontWeight: 600, fontSize: 16, boxShadow: '0 0 32px var(--primary-glow)',
            }}
          >
            📄 Download Blueprint PDF
          </motion.a>
        )}
      </motion.div>

      {/* Template Gallery */}
      <div style={{ marginTop: 'var(--space-2xl)', width: '100%' }}>
        <TemplateGallery onSelect={handleTemplateSelect} disabled={isRunning || isLaunching || isDone} />
      </div>
    </section>
  );
}

/* ─── AGENT DIVE ─── */
function AgentDiveSection({ liveLines, workflowStatus }: { liveLines?: any[]; workflowStatus?: string }) {
  const [sectionRef, isInView] = useInView();
  const isLive = workflowStatus === 'running' || workflowStatus === 'completed';

  return (
    <section id="pipeline" ref={sectionRef} className="scroll-section" style={{ minHeight: '140vh', flexDirection: 'column', gap: 'var(--space-2xl)', padding: 'var(--space-4xl) var(--space-2xl)' }}>
      {AGENTS.slice(0, 4).map((agent, i) => (
        <motion.div key={agent.id} className="text-center" initial={{ opacity: 0, x: i % 2 === 0 ? -60 : 60 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true, margin: '-50px' }} transition={{ duration: 0.8, ease: [0.25, 1, 0.5, 1] }} style={{ marginBottom: 'var(--space-xl)' }}>
          <div className="mono-label" style={{ color: agent.color, marginBottom: 'var(--space-sm)' }}>{agent.icon} {agent.name} Agent</div>
          <h3 className="headline-xl" style={{ color: agent.color }}>{agent.label}</h3>
          <p className="body-md" style={{ maxWidth: '500px', margin: 'var(--space-md) auto 0' }}>{agent.stat}</p>
        </motion.div>
      ))}
      <div id="live-stream" style={{ maxWidth: '1000px', width: '100%', margin: '0 auto', scrollMarginTop: '90px' }}>
        <CodePreview
          lines={TERMINAL_LINES}
          liveLines={isLive ? liveLines : undefined}
          isInView={isInView}
          title={isLive ? '● LIVE — Neural Pipeline' : undefined}
        />
      </div>
    </section>
  );
}

/* ─── OUTPUT with Bento Grid + TiltCards (unlocks as agents complete) ─── */
function OutputSection({ completedAgents = [] }: { completedAgents?: string[] }) {
  const [ref, isInView] = useInView();

  // Map bento cards to agent keys that unlock them
  const FEATURES = [
    { icon: '📊', title: 'Market Analysis', desc: 'TAM, SAM, SOM breakdown + competitive landscape with 47 data points', wide: true, back: 'Deep market intelligence', agentKey: 'research' },
    { icon: '🚀', title: 'Go-To-Market', desc: '12-channel acquisition strategy with CAC projections', back: 'Scalable growth tactics', agentKey: 'marketing' },
    { icon: '⚡', title: 'Tech Architecture', desc: 'Full-stack blueprint, API contracts, cloud infra, CI/CD pipeline', back: 'Robust system design', agentKey: 'developer' },
    { icon: '💎', title: 'Financial Model', desc: '5-year projections, burn rate, Series A readiness score', wide: false, back: 'Investor-ready metrics', agentKey: 'finance' },
    { icon: '📡', title: 'Marketing Plan', desc: 'Brand identity, content calendar, viral loops, SEO strategy', back: 'Viral loop mechanics', agentKey: 'analytics' },
    { icon: '⚙️', title: 'Operations', desc: 'Hiring roadmap, supply chain, compliance, launch timeline', wide: true, back: 'Operational excellence', agentKey: 'operations' },
  ];

  const hasWorkflow = completedAgents.length > 0;

  return (
    <section ref={ref} className="scroll-section" id="results" style={{ minHeight: '100vh', flexDirection: 'column', gap: 'var(--space-3xl)', padding: 'var(--space-4xl) var(--space-2xl)' }}>
      <DataFlowLines />
      <motion.div className="text-center" initial={{ opacity: 0, y: 40 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}>
        <div className="mono-label" style={{ color: 'var(--accent)', marginBottom: 'var(--space-md)' }}>The Result</div>
        <TextScramble text="42 Pages. 7 Minds. Under 2 Min." trigger={isInView} className="display-xl" tag="h2" speed={25} />
        <p className="body-lg" style={{ maxWidth: '600px', margin: 'var(--space-xl) auto 0', color: 'var(--text-secondary)' }}>Every dimension of your business, analyzed and architected.</p>
      </motion.div>
      <div className="bento-grid">
        {FEATURES.map((item, i) => {
          const isUnlocked = !hasWorkflow || completedAgents.includes(item.agentKey);
          return (
            <motion.div key={i} className={item.wide ? 'bento-grid__item--wide' : ''} initial={{ opacity: 0, y: 40 }} whileInView={{ opacity: isUnlocked ? 1 : 0.3, y: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.08, duration: 0.6 }} animate={hasWorkflow ? { opacity: isUnlocked ? 1 : 0.3, scale: isUnlocked ? 1 : 0.96 } : undefined}>
              <TiltCard style={{ padding: 'var(--space-xl)', height: '100%', filter: isUnlocked ? 'none' : 'grayscale(0.8)' }} backContent={item.back}>
                <div className="card-icon">{item.icon}</div>
                <h4 style={{ fontFamily: "'Space Grotesk'", fontSize: '18px', fontWeight: 600, marginBottom: 'var(--space-sm)' }}>{item.title}</h4>
                <p className="body-md" style={{ fontSize: '14px' }}>{item.desc}</p>
                {hasWorkflow && isUnlocked && (
                  <motion.div initial={{ opacity: 0, scale: 0.5 }} animate={{ opacity: 1, scale: 1 }} style={{ marginTop: 'var(--space-sm)', fontFamily: "'JetBrains Mono'", fontSize: '10px', color: '#10b981' }}>✓ AGENT COMPLETE</motion.div>
                )}
              </TiltCard>
            </motion.div>
          );
        })}
      </div>
    </section>
  );
}

/* ─── PROOF ─── */
function ProofSection() {
  const [ref, isInView] = useInView();
  return (
    <section ref={ref} className="scroll-section" id="proof" style={{ minHeight: '100vh', flexDirection: 'column', gap: 'var(--space-4xl)', padding: 'var(--space-5xl) var(--space-2xl)' }}>
      <motion.div initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true }} transition={{ duration: 0.8 }}>
        <div className="mono-label text-center" style={{ marginBottom: 'var(--space-md)', color: 'var(--secondary)' }}>The Proof Is In The Blueprint</div>
        <TextScramble text="Built Different." trigger={isInView} className="display-lg text-center" tag="h2" />
        <div className="stats-row" style={{ marginTop: 'var(--space-2xl)' }}>
          {STATS.map((stat, i) => <CountUp key={i} end={stat.value} suffix={stat.suffix} prefix={'prefix' in stat ? stat.prefix : ''} label={stat.label} />)}
        </div>
      </motion.div>
      <div className="features-grid" style={{ maxWidth: '1200px' }}>
        {TESTIMONIALS.map((t, i) => (
          <motion.div key={i} initial={{ opacity: 0, y: 30 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.15, duration: 0.6 }}>
            <TiltCard className="testimonial-card" maxTilt={8}>
              <div style={{ color: 'var(--primary)', fontSize: '24px', marginBottom: 'var(--space-md)' }}>"</div>
              <p className="testimonial-card__quote">{t.quote}</p>
              <div className="testimonial-card__author">{t.author}</div>
              <div className="testimonial-card__role">{t.role}</div>
            </TiltCard>
          </motion.div>
        ))}
      </div>
      <InfiniteMarquee
        items={[
          { text: 'Claude Sonnet 4' }, { text: 'Real-Time WebSocket' },
          { text: 'PDF Export' }, { text: '7-Agent Pipeline' },
          { text: 'Open Source' }, { text: '42-Page Blueprint' },
          { text: 'Series A Ready' }, { text: 'Under 2 Minutes' },
        ]}
        speed={35}
        direction="right"
        separator="—"
      />
    </section>
  );
}

/* ─── CTA ─── */
function CTASection({ onGetStarted }: { onGetStarted: () => void }) {
  return (
    <section className="section-cta scroll-section" id="cta" style={{ flexDirection: 'column', gap: 'var(--space-2xl)' }}>
      <motion.div className="text-center" initial={{ opacity: 0, y: 40, scale: 0.95 }} whileInView={{ opacity: 1, y: 0, scale: 1 }} viewport={{ once: true }} transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}>
        <SplitTextReveal text="Your Startup Is Waiting." className="display-xl" tag="h2" highlightWords={['Is', 'Waiting.']} />
        <p className="body-lg" style={{ color: 'var(--text-secondary)', maxWidth: '500px', margin: 'var(--space-lg) auto var(--space-2xl)' }}>Seven minds are standing by. All they need is your idea.</p>
        <MagneticButton onClick={onGetStarted}>Launch Your Blueprint →</MagneticButton>
      </motion.div>
    </section>
  );
}

/* ─── FOOTER ─── */
function Footer() {
  return (
    <footer className="footer">
      <div className="footer__copyright">© 2026 AgentForge AI. Seven minds. One blueprint.</div>
      <ul className="footer__links">
        {['GitHub', 'Documentation', 'Privacy', 'Terms'].map(l => <li key={l}><a href="#" className="footer__link">{l}</a></li>)}
      </ul>
    </footer>
  );
}
