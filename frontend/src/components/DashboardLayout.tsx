/**
 * AgentForge AI — Dashboard Layout
 * 
 * Glassmorphic sidebar + header shell for all dashboard pages.
 */

import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { colors, typography, spacing, radii, gradients } from '../styles/tokens';

const NAV_ITEMS = [
  { path: '/phantom', icon: '👻', label: 'Phantom Hunter' },
  { path: '/dashboard', icon: '📋', label: 'Projects' },
  { path: '/observability', icon: '📊', label: 'Observability' },
  { path: '/knowledge', icon: '🧠', label: 'Knowledge' },
  { path: '/prompts', icon: '✏️', label: 'Prompts' },
  { path: '/admin', icon: '⚙️', label: 'Admin' },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <div style={{
      display: 'flex',
      minHeight: '100vh',
      background: gradients.background,
      fontFamily: typography.fontFamily,
      color: colors.text,
    }}>
      {/* ─── Sidebar ─── */}
      <aside style={{
        width: '220px',
        borderRight: `1px solid ${colors.border}`,
        background: 'rgba(0,0,0,0.4)',
        backdropFilter: 'blur(20px)',
        display: 'flex',
        flexDirection: 'column',
        padding: `${spacing.lg} 0`,
        position: 'sticky',
        top: 0,
        height: '100vh',
      }}>
        {/* Logo */}
        <div
          onClick={() => navigate('/')}
          style={{
            padding: `0 ${spacing.lg} ${spacing.xl}`,
            cursor: 'pointer',
          }}
        >
          <div style={{
            fontSize: '1.2rem',
            fontWeight: typography.bold,
            background: gradients.hero,
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}>
            AgentForge
          </div>
          <div style={{ fontSize: '0.65rem', color: colors.textMuted, marginTop: '2px', letterSpacing: '0.05em' }}>
            AI PLATFORM
          </div>
        </div>

        {/* Nav Items */}
        <nav style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '2px', padding: `0 ${spacing.sm}` }}>
          {NAV_ITEMS.map(item => {
            const active = location.pathname === item.path || (item.path === '/phantom' && location.pathname.startsWith('/phantom/'));
            return (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: spacing.md,
                  padding: '0.65rem 0.75rem',
                  borderRadius: radii.md,
                  border: 'none',
                  cursor: 'pointer',
                  fontSize: typography.sm,
                  fontWeight: active ? typography.semibold : typography.regular,
                  color: active ? colors.white : colors.textMuted,
                  background: active
                    ? 'linear-gradient(135deg, rgba(124,58,237,0.15), rgba(6,182,212,0.1))'
                    : 'transparent',
                  transition: 'all 0.2s',
                  textAlign: 'left',
                }}
              >
                <span style={{ fontSize: '1.1rem' }}>{item.icon}</span>
                {item.label}
                {active && (
                  <div style={{
                    marginLeft: 'auto',
                    width: '3px',
                    height: '16px',
                    borderRadius: '2px',
                    background: gradients.hero,
                  }} />
                )}
              </button>
            );
          })}
        </nav>

        {/* User */}
        <div style={{
          padding: `${spacing.md} ${spacing.lg}`,
          borderTop: `1px solid ${colors.border}`,
        }}>
          <div style={{ fontSize: typography.xs, color: colors.textMuted, marginBottom: spacing.sm }}>
            {user?.email}
          </div>
          <button
            onClick={() => { logout(); navigate('/'); }}
            style={{
              width: '100%',
              padding: '0.4rem',
              background: 'rgba(255,255,255,0.05)',
              border: `1px solid ${colors.border}`,
              borderRadius: radii.sm,
              color: colors.textMuted,
              fontSize: typography.xs,
              cursor: 'pointer',
            }}
          >
            Sign Out
          </button>
        </div>
      </aside>

      {/* ─── Main Content ─── */}
      <main style={{ flex: 1, overflow: 'auto' }}>
        {children}
      </main>
    </div>
  );
}
