import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import * as THREE from 'three';
import type { RfqSkillHistoryEntry } from '@/lib/accomplish';

/**
 * The formula engine as a processor: a chip with one core per real pipeline step, wired to the next step. A core's state is
 * the step's stored status: running cores glow and breathe, completed cores sit lit, a failed core rises as a spike, a flagged
 * core is amber. The panel beside the chip narrates the same events in plain words. Nothing is scripted: the chip changes only
 * when the live feed does, and it animates only while a step runs or a core is still moving to its new state. The narration is
 * written from each step's stored status and detail; it describes what the pipeline did, not the model's own reasoning.
 */

const COLOR: Record<string, number> = {
  running: 0x22d3ee,
  completed: 0x34d399,
  warning: 0xfbbf24,
  failed: 0xf87171,
  skipped: 0x475569,
};
const HEIGHT: Record<string, number> = { running: 1.3, completed: 1.0, warning: 1.15, failed: 1.9, skipped: 0.55 };
const VERB: Record<string, string> = { running: 'working through', completed: 'finished', warning: 'flagged', failed: 'stopped on', skipped: 'skipped' };
const TAG: Record<string, string> = { running: 'attention', completed: 'output', warning: 'uncertainty', failed: 'stack trace', skipped: 'pruned' };
const TARGET_COLOR: Record<string, THREE.Color> = Object.fromEntries(Object.entries(COLOR).map(([k, v]) => [k, new THREE.Color(v)]));
const CORE = 0.62;
const GAP = 0.95;
const EASE = 0.12;
const colorGap = (a: THREE.Color, b: THREE.Color) => Math.abs(a.r - b.r) + Math.abs(a.g - b.g) + Math.abs(a.b - b.b);

interface Core {
  mesh: THREE.Mesh;
  status: string;
}

/** Stored status as the one the chip shows: a step that ran but flagged something is a warning, as the timeline shows it. */
const statusOf = (e: RfqSkillHistoryEntry) => (e.stepStatus === 'completed' && e.warning ? 'warning' : e.stepStatus);

export function FormulaEngine3D({ entries, expanded = false }: { entries: RfqSkillHistoryEntry[]; expanded?: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const three = useRef<{
    renderer: THREE.WebGLRenderer;
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    group: THREE.Group;
    cores: Map<string, Core>;
    wires: THREE.LineSegments | null;
    pins: THREE.Group;
    substrate: THREE.Mesh;
    die: THREE.Mesh;
    frame: number;
    start: () => void;
  } | null>(null);
  const [webgl, setWebgl] = useState(true);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  // One renderer for the component's life. It draws when asked; its loop stops itself when nothing moves.
  useEffect(() => {
    const el = host.current;
    if (!el) return undefined;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setWebgl(false);
      return undefined;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
    scene.add(new THREE.AmbientLight(0xffffff, 0.5));
    const key = new THREE.DirectionalLight(0x9be7ff, 1.1);
    key.position.set(4, 8, 5);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xa78bfa, 0.7);
    rim.position.set(-5, 4, -4);
    scene.add(rim);

    const group = new THREE.Group();
    scene.add(group);
    const substrate = new THREE.Mesh(new THREE.BoxGeometry(1, 0.3, 1), new THREE.MeshStandardMaterial({ color: 0x0b1220, roughness: 0.6, metalness: 0.4 }));
    const die = new THREE.Mesh(new THREE.BoxGeometry(1, 0.08, 1), new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.3, metalness: 0.7 }));
    const pins = new THREE.Group();
    group.add(substrate, die, pins);

    const state = { renderer, scene, camera, group, cores: new Map<string, Core>(), wires: null as THREE.LineSegments | null, pins, substrate, die, frame: 0, start: () => undefined as void };
    three.current = state;

    const draw = () => renderer.render(scene, camera);
    // Eases every core toward its status; keeps going only while a core moves or a step runs.
    const tick = (t: number) => {
      let moving = false;
      state.cores.forEach((core) => {
        const m = core.mesh;
        const targetH = HEIGHT[core.status] ?? HEIGHT.skipped;
        const targetColor = TARGET_COLOR[core.status] ?? TARGET_COLOR.skipped;
        const mat = m.material as THREE.MeshStandardMaterial;
        if (Math.abs(targetH - m.scale.y) > 0.002) {
          m.scale.y += (targetH - m.scale.y) * EASE;
          moving = true;
        } else {
          m.scale.y = targetH;
        }
        if (colorGap(mat.color, targetColor) > 0.002) {
          mat.color.lerp(targetColor, EASE);
          moving = true;
        } else {
          mat.color.copy(targetColor);
        }
        // A running core breathes with real time; a failed core keeps a steady red glow; the rest are not lit beyond their colour.
        if (core.status === 'running') {
          mat.emissive.copy(targetColor).multiplyScalar(0.25 + 0.25 * Math.sin(t / 220));
          moving = true;
        } else if (core.status === 'failed') {
          mat.emissive.copy(targetColor).multiplyScalar(0.35);
        } else {
          mat.emissive.copy(targetColor).multiplyScalar(0.05);
        }
      });
      draw();
      state.frame = moving ? requestAnimationFrame(tick) : 0;
    };
    state.start = () => {
      if (!state.frame) state.frame = requestAnimationFrame(tick);
    };

    const resize = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (w === 0 || h === 0) return;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      draw();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    return () => {
      ro.disconnect();
      cancelAnimationFrame(state.frame);
      state.cores.forEach((core) => {
        core.mesh.geometry.dispose();
        (core.mesh.material as THREE.Material).dispose();
      });
      state.wires?.geometry.dispose();
      (state.wires?.material as THREE.Material | undefined)?.dispose();
      substrate.geometry.dispose();
      (substrate.material as THREE.Material).dispose();
      die.geometry.dispose();
      (die.material as THREE.Material).dispose();
      renderer.dispose();
      renderer.domElement.remove();
      three.current = null;
    };
  }, []);

  // The chip follows the steps: one core per step, in run order, wired to the next; the package and pins fit the grid.
  useEffect(() => {
    const s = three.current;
    if (!s) return;
    const n = entries.length;
    const cols = Math.max(1, Math.ceil(Math.sqrt(Math.max(n, 1))));
    const rows = Math.max(1, Math.ceil(Math.max(n, 1) / cols));
    const at = (i: number) => new THREE.Vector3(((i % cols) - (cols - 1) / 2) * GAP, 0, (Math.floor(i / cols) - (rows - 1) / 2) * GAP);

    const seen = new Set<string>();
    entries.forEach((entry, i) => {
      seen.add(entry.skillCode);
      const status = statusOf(entry);
      let core = s.cores.get(entry.skillCode);
      if (!core) {
        const mesh = new THREE.Mesh(
          new THREE.BoxGeometry(CORE, CORE * 1.2, CORE),
          new THREE.MeshStandardMaterial({ color: COLOR.skipped, roughness: 0.4, metalness: 0.3 }),
        );
        mesh.scale.y = 0.05;
        s.group.add(mesh);
        core = { mesh, status };
        s.cores.set(entry.skillCode, core);
      }
      core.status = status;
      core.mesh.position.copy(at(i));
    });
    s.cores.forEach((core, code) => {
      if (seen.has(code)) return;
      s.group.remove(core.mesh);
      core.mesh.geometry.dispose();
      (core.mesh.material as THREE.Material).dispose();
      s.cores.delete(code);
    });

    // Wires: each step feeds the next, as connections between neighbouring cores.
    s.wires?.geometry.dispose();
    (s.wires?.material as THREE.Material | undefined)?.dispose();
    if (s.wires) s.group.remove(s.wires);
    s.wires = null;
    if (n > 1) {
      const pts: number[] = [];
      for (let i = 0; i < n - 1; i += 1) {
        const a = at(i);
        const b = at(i + 1);
        pts.push(a.x, 0.45, a.z, b.x, 0.45, b.z);
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
      s.wires = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.45 }));
      s.group.add(s.wires);
    }

    // Package: substrate and die sized to the grid, with pins along each edge.
    const W = cols * GAP + 1.1;
    const D = rows * GAP + 1.1;
    s.substrate.scale.set(W, 1, D);
    s.die.scale.set(W - 0.5, 1, D - 0.5);
    s.die.position.y = 0.19;
    s.pins.clear();
    const pinMat = new THREE.MeshStandardMaterial({ color: 0xc0c8d4, metalness: 0.9, roughness: 0.25 });
    const pinGeo = new THREE.BoxGeometry(0.12, 0.12, 0.45);
    for (let c = 0; c < cols; c += 1) {
      for (const side of [-1, 1]) {
        const p = new THREE.Mesh(pinGeo, pinMat);
        p.position.set(((c - (cols - 1) / 2) * GAP), -0.12, side * (D / 2 + 0.2));
        s.pins.add(p);
      }
    }
    for (let r = 0; r < rows; r += 1) {
      for (const side of [-1, 1]) {
        const p = new THREE.Mesh(pinGeo, pinMat);
        p.rotation.y = Math.PI / 2;
        p.position.set(side * (W / 2 + 0.2), -0.12, (r - (rows - 1) / 2) * GAP);
        s.pins.add(p);
      }
    }

    // Framing: the whole package fits the view, from above and in front.
    const halfSpan = Math.max(W, D) / 2 + 0.6;
    const fov = THREE.MathUtils.degToRad(s.camera.fov / 2);
    // 0.8: the package fills the view with a margin; the pins and the grid stay inside the frame.
    const distance = 0.8 * halfSpan / (Math.tan(fov) * Math.min(1, s.camera.aspect || 1));
    s.camera.position.set(0, distance * 0.8, distance * 0.7);
    s.camera.lookAt(0, 0, 0);
    s.start();
  }, [entries]);

  const failed = entries.filter((e) => e.stepStatus === 'failed').length;
  const running = entries.filter((e) => e.stepStatus === 'running').length;
  // The narration: the newest steps first, each in a sentence built from its stored status and detail.
  const log = useMemo(() => {
    const rows = [...entries].map((e, i) => ({ e, core: i + 1 })).reverse();
    return expanded ? rows : rows.slice(0, 8);
  }, [entries, expanded]);

  const surface = (
    <div className={`grid overflow-hidden rounded-xl border border-white/10 bg-[#070b14] text-slate-200 ${expanded ? 'h-full min-h-[60vh] lg:grid-cols-[1.35fr_1fr]' : 'h-[240px] grid-cols-[1.3fr_1fr]'}`}>
      <div className="relative min-w-0">
        <div
          ref={host}
          className="absolute inset-0"
          style={{ pointerEvents: expanded ? 'auto' : 'none' }}
          role="img"
          aria-label={`Formula engine chip: ${entries.length} cores, ${running} running, ${failed} failed`}
        />
        {entries.length === 0 && <p className="absolute inset-0 flex items-center justify-center text-xs text-slate-400">No steps have run yet.</p>}
        {!webgl && <p role="alert" className="absolute inset-0 flex items-center justify-center text-xs text-slate-400">The chip view needs WebGL. The narration is still live.</p>}
      </div>
      <aside className="flex min-h-0 flex-col gap-2 overflow-hidden border-l border-white/10 p-4 font-mono text-[11px] leading-relaxed">
        <p className="text-slate-400">CPU · {entries.length} cores · {running} running · {failed} failed</p>
        <ol className="min-h-0 flex-1 space-y-2 overflow-y-auto" aria-label="What each core is doing">
          {log.length === 0 && <li className="text-slate-500">Waiting for the first step.</li>}
          {log.map(({ e, core }) => {
            const st = statusOf(e);
            return (
              <li key={e.skillCode} className="flex gap-2">
                <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ background: `#${(COLOR[st] ?? COLOR.skipped).toString(16).padStart(6, '0')}` }} aria-hidden />
                <span className="min-w-0">
                  <span className="text-slate-400">core {String(core).padStart(2, '0')}</span>
                  <span className="text-slate-100"> · {e.skillName}</span>
                  <span className="text-slate-500"> — {TAG[st] ?? 'state'}: </span>
                  <span className="text-slate-300">{VERB[st] ?? st}</span>
                  {(e.error || e.detail) && <span className="block truncate text-slate-500" title={e.error ?? e.detail}>{e.error ?? e.detail}</span>}
                </span>
              </li>
            );
          })}
        </ol>
        <p className="text-[10px] text-slate-600">Narration from each step&apos;s stored status and detail: what the pipeline did, not the model&apos;s own reasoning.</p>
      </aside>
    </div>
  );

  if (expanded) {
    return <div className="h-full p-4" data-testid="formula-engine-3d-expanded">{surface}</div>;
  }
  return (
    <div className="space-y-2 px-5" data-testid="formula-engine-3d">
      <div className="flex justify-end">
        <button type="button" onClick={() => setOpen(true)} className="rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground">
          Full screen
        </button>
      </div>
      {surface}
      {open &&
        createPortal(
          <div role="dialog" aria-modal="true" aria-label="Formula engine, full screen" className="fixed inset-0 z-[90] flex flex-col bg-background p-4" data-testid="formula-engine-fullscreen">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-semibold text-foreground">Formula engine: each pipeline step as a core</p>
              <button type="button" onClick={() => setOpen(false)} className="rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground">Close</button>
            </div>
            <div className="min-h-0 flex-1">
              <FormulaEngine3D entries={entries} expanded />
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
