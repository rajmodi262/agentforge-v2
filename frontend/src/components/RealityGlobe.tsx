/**
 * Reality Globe — every project is a bar on a 3D globe.
 *
 * Ghost (translucent) bar height = announced MW. Solid inner bar = reality-
 * weighted MW (announced × reality score). The gap between the two is the
 * "phantom" capacity. Click a bar to open the project dossier.
 */
import { useMemo, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Html } from '@react-three/drei';
import * as THREE from 'three';
import type { PhProject } from '../services/phantom';
import { fmtMW, scoreColor } from '../services/phantom';

const R = 2;

function toVec(lat: number, lon: number, r = R) {
  const phi = (90 - lat) * (Math.PI / 180);
  const theta = (lon + 180) * (Math.PI / 180);
  return new THREE.Vector3(-r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta));
}

function Earth() {
  const dots = useMemo(() => {
    const pts: number[] = [];
    for (let i = 0; i < 6000; i++) {
      const y = 1 - (i / 5999) * 2, rad = Math.sqrt(1 - y * y), th = Math.PI * (3 - Math.sqrt(5)) * i;
      pts.push(Math.cos(th) * rad * R * 1.001, y * R * 1.001, Math.sin(th) * rad * R * 1.001);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    return g;
  }, []);
  const grid = useMemo(() => {
    const pts: number[] = [];
    const seg = (a: THREE.Vector3, b: THREE.Vector3) => pts.push(a.x, a.y, a.z, b.x, b.y, b.z);
    for (let lat = -75; lat <= 75; lat += 15)
      for (let lon = -180; lon < 180; lon += 3) seg(toVec(lat, lon, R * 1.002), toVec(lat, lon + 3, R * 1.002));
    for (let lon = -180; lon < 180; lon += 15)
      for (let lat = -84; lat < 84; lat += 3) seg(toVec(lat, lon, R * 1.002), toVec(lat + 3, lon, R * 1.002));
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    return g;
  }, []);
  return (
    <group>
      <mesh>
        <sphereGeometry args={[R, 64, 64]} />
        <meshStandardMaterial color="#0b0a1a" emissive="#1a1038" emissiveIntensity={0.35} roughness={0.9} />
      </mesh>
      <lineSegments geometry={grid}>
        <lineBasicMaterial color="#4c3b9e" transparent opacity={0.35} />
      </lineSegments>
      {[['INDIA', 22, 79], ['MALAYSIA', 4.2, 101.9], ['SINGAPORE', 1.35, 103.8], ['INDONESIA', -2, 113], ['THAILAND', 15.5, 101]].map(([label, lat, lon]) => {
        const v = toVec(lat as number, lon as number, R * 1.01);
        const hot = label === 'INDIA' || label === 'MALAYSIA';
        return (
          <Html key={label as string} position={[v.x, v.y, v.z]} center style={{ pointerEvents: 'none' }}>
            <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: hot ? 11 : 9, letterSpacing: '0.2em', color: hot ? '#c4b5fd' : '#4b4670', whiteSpace: 'nowrap', textShadow: '0 0 6px #000' }}>{label}</div>
          </Html>
        );
      })}
      <points geometry={dots}>
        <pointsMaterial color="#3b2d7a" size={0.012} transparent opacity={0.8} />
      </points>
      <mesh>
        <sphereGeometry args={[R * 1.06, 64, 64]} />
        <meshBasicMaterial color="#7c3aed" transparent opacity={0.06} side={THREE.BackSide} />
      </mesh>
    </group>
  );
}

function Bar({ p, maxMw, onPick, hovered, setHovered }: { p: PhProject; maxMw: number; onPick: (id: string) => void; hovered: string | null; setHovered: (id: string | null) => void }) {
  const base = toVec(p.lat!, p.lon!);
  const up = base.clone().normalize();
  const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), up);
  const mw = p.capacity_mw || 40;
  const hA = 0.06 + 1.1 * Math.sqrt(mw / maxMw);
  const hR = Math.max(0.02, hA * (p.reality_score || 0));
  const col = scoreColor(p.reality_score || 0);
  const isH = hovered === p.id;
  return (
    <group position={base} quaternion={q}
      onPointerOver={(e) => { e.stopPropagation(); setHovered(p.id); document.body.style.cursor = 'pointer'; }}
      onPointerOut={() => { setHovered(null); document.body.style.cursor = 'default'; }}
      onClick={(e) => { e.stopPropagation(); onPick(p.id); }}>
      <mesh position={[0, hA / 2, 0]}>
        <cylinderGeometry args={[0.022, 0.022, hA, 10]} />
        <meshBasicMaterial color="#c4b5fd" transparent opacity={isH ? 0.45 : 0.18} />
      </mesh>
      <mesh position={[0, hR / 2, 0]}>
        <cylinderGeometry args={[0.014, 0.014, hR, 10]} />
        <meshBasicMaterial color={col} />
      </mesh>
      <mesh position={[0, 0.005, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.03, 0.045, 24]} />
        <meshBasicMaterial color={col} transparent opacity={0.8} side={THREE.DoubleSide} />
      </mesh>
      {isH && (
        <Html position={[0, hA + 0.08, 0]} center style={{ pointerEvents: 'none' }}>
          <div style={{ background: 'rgba(10,8,20,0.92)', border: `1px solid ${col}`, borderRadius: 8, padding: '6px 10px', color: '#fff', fontSize: 12, whiteSpace: 'nowrap', fontFamily: 'Inter, sans-serif' }}>
            <b>{p.name}</b><br />
            {fmtMW(p.capacity_mw)} announced · <span style={{ color: col }}>{Math.round((p.reality_score || 0) * 100)}% real</span><br />
            <span style={{ color: '#94a3b8' }}>{p.stage_name} · {p.city || p.country}</span>
          </div>
        </Html>
      )}
    </group>
  );
}

function Spinner({ children }: { children: React.ReactNode }) {
  const g = useRef<THREE.Group>(null);
  // gentle sway around South/South-East Asia instead of a full spin, so the region stays in view
  useFrame(({ clock }) => { if (g.current) g.current.rotation.y = Math.sin(clock.elapsedTime * 0.15) * 0.25; });
  return <group ref={g}>{children}</group>;
}

export default function RealityGlobe({ projects, onPick, height = 460 }: { projects: PhProject[]; onPick: (id: string) => void; height?: number }) {
  const [hovered, setHovered] = useState<string | null>(null);
  const placed = projects.filter((p) => p.lat != null && p.lon != null);
  // jitter projects that share a city so their bars don't overlap
  const jittered = useMemo(() => {
    const seen: Record<string, number> = {};
    return placed.map((p) => {
      const k = `${p.lat},${p.lon}`; const n = (seen[k] = (seen[k] || 0) + 1) - 1;
      const a = n * 2.4, d = n ? 0.25 + 0.12 * Math.sqrt(n) : 0;
      return { ...p, lat: p.lat! + Math.sin(a) * d, lon: p.lon! + Math.cos(a) * d };
    });
  }, [placed]);
  const maxMw = Math.max(200, ...placed.map((p) => p.capacity_mw || 0));
  // look at South / South-East Asia
  const cam = toVec(14, 92, 4.6);
  return (
    <div style={{ height, borderRadius: 16, overflow: 'hidden', background: 'radial-gradient(ellipse at center, #140d2e 0%, #05040b 70%)', position: 'relative' }}>
      <Canvas camera={{ position: [cam.x, cam.y, cam.z], fov: 40 }} onPointerMissed={() => setHovered(null)}>
        <ambientLight intensity={0.6} />
        <pointLight position={[5, 5, 5]} intensity={40} color="#a78bfa" />
        <Spinner>
          <Earth />
          {jittered.map((p) => <Bar key={p.id} p={p} maxMw={maxMw} onPick={onPick} hovered={hovered} setHovered={setHovered} />)}
        </Spinner>
        <OrbitControls enablePan={false} minDistance={3} maxDistance={8} rotateSpeed={0.5} />
      </Canvas>
      <div style={{ position: 'absolute', left: 14, bottom: 12, fontSize: 11, color: '#94a3b8', fontFamily: 'JetBrains Mono, monospace', lineHeight: 1.6 }}>
        <span style={{ display: 'inline-block', width: 10, height: 10, background: '#c4b5fd', opacity: 0.4, marginRight: 6 }} />announced MW
        <span style={{ display: 'inline-block', width: 10, height: 10, background: '#10b981', margin: '0 6px 0 14px' }} />reality-weighted MW · drag to rotate · click a bar
      </div>
    </div>
  );
}
