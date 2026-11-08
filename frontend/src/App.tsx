import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom';
import Lenis from 'lenis';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { AuthProvider } from './hooks/useAuth';
import ErrorBoundary from './components/ErrorBoundary';
import ProtectedRoute from './components/ProtectedRoute';
import Landing from './pages/Landing';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Report from './pages/Report';
import ObservabilityPage from './pages/ObservabilityPage';
import KnowledgePage from './pages/KnowledgePage';
import PromptsPage from './pages/PromptsPage';
import AdminPage from './pages/AdminPage';
import SharedReport from './pages/SharedReport';
import PhantomHunter from './pages/PhantomHunter';
import PhantomProject from './pages/PhantomProject';

gsap.registerPlugin(ScrollTrigger);

/** Only enable Lenis smooth scroll on the landing page (scrollytelling) */
function LenisProvider({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const isLanding = location.pathname === '/';

  useEffect(() => {
    if (!isLanding) return;

    const lenis = new Lenis({
      lerp: 0.1,
      smoothWheel: true,
    });

    // Expose the instance so pages can drive smooth scroll (e.g. scroll to the
    // live pipeline on launch). Native scrollIntoView doesn't work under Lenis.
    (window as unknown as { __lenis?: Lenis }).__lenis = lenis;

    lenis.on('scroll', ScrollTrigger.update);
    const ticker = (time: number) => { lenis.raf(time * 1000); };
    gsap.ticker.add(ticker);
    gsap.ticker.lagSmoothing(0);

    return () => {
      gsap.ticker.remove(ticker);
      lenis.destroy();
      delete (window as unknown as { __lenis?: Lenis }).__lenis;
    };
  }, [isLanding]);

  return <>{children}</>;
}

export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <BrowserRouter>
          <LenisProvider>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/shared/:shareToken" element={<SharedReport />} />
              <Route path="/login" element={<Login />} />
              <Route path="/dashboard" element={
                <ProtectedRoute><Dashboard /></ProtectedRoute>
              } />
              <Route path="/report/:projectId" element={
                <ProtectedRoute><Report /></ProtectedRoute>
              } />
              <Route path="/phantom" element={
                <ProtectedRoute><PhantomHunter /></ProtectedRoute>
              } />
              <Route path="/phantom/:id" element={
                <ProtectedRoute><PhantomProject /></ProtectedRoute>
              } />
              <Route path="/observability" element={
                <ProtectedRoute><ObservabilityPage /></ProtectedRoute>
              } />
              <Route path="/knowledge" element={
                <ProtectedRoute><KnowledgePage /></ProtectedRoute>
              } />
              <Route path="/prompts" element={
                <ProtectedRoute><PromptsPage /></ProtectedRoute>
              } />
              <Route path="/admin" element={
                <ProtectedRoute><AdminPage /></ProtectedRoute>
              } />
            </Routes>
          </LenisProvider>
        </BrowserRouter>
      </AuthProvider>
    </ErrorBoundary>
  );
}

