import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import * as THREE from 'three';
import type { RfqSkillHistoryEntry } from '@/lib/accomplish';

/**
 * The formula engine as a 3D model: one block per real pipeline step, in the order the backend ran them. A block's colour and
 * height are its stepStatus; a failed step stands out as a red spike with its error in the list below. Nothing is scripted: the
 * scene only changes when the live feed does, and it animates only while a step is running or a block is still moving to its new state.
 * With no WebGL the list below still shows every step.
 */

const COLOR: Record<string, number> = {
  running: 0x22a8c9,
  completed: 0x10b981,
  warning: 0xf59e0b,
  failed: 0xdc2626,
  skipped: 0x94a3b8,
};
const HEIGHT: Record<string, number> = { running: 1, completed: 0.8, warning: 1.1, failed: 2.2, skipped: 0.4 };
const TARGET_COLOR: Record<string, THREE.Color> = Object.fromEntries(Object.entries(COLOR).map(([k, v]) => [k, new THREE.Color(v)]));
const colorGap = (a: THREE.Color, b: THREE.Color) => Math.abs(a.r - b.r) + Math.abs(a.g - b.g) + Math.abs(a.b - b.b);
const SPACING = 1.25;
const EASE = 0.12;

interface Node {
  mesh: THREE.Mesh;
  status: string;
}

export function FormulaEngine3D({ entries, expanded = false }: { entries: RfqSkillHistoryEntry[]; expanded?: boolean }) {
  const [open, setOpen] = useState(false);
  // Escape closes the full-screen view.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const host = useRef<HTMLDivElement>(null);
  const three = useRef<{
    renderer: THREE.WebGLRenderer;
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    group: THREE.Group;
    nodes: Map<string, Node>;
    frame: number;
    start: () => void;
  } | null>(null);
  const [webgl, setWebgl] = useState(true);

  // One renderer for the component's life. It draws only when asked (the loop below stops itself when nothing moves).
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
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    camera.position.set(0, 5.2, 10);
    camera.lookAt(0, 0.6, 0);
    scene.add(new THREE.AmbientLight(0xffffff, 0.75));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(4, 8, 6);
    scene.add(key);
    const group = new THREE.Group();
    scene.add(group);

    const state = { renderer, scene, camera, group, nodes: new Map<string, Node>(), frame: 0, start: () => undefined as void };
    three.current = state;

    const draw = () => {
      renderer.render(scene, camera);
    };
    // Eases every block toward its status; keeps going only while something is still moving or a step is running.
    const tick = (t: number) => {
      let moving = false;
      state.nodes.forEach((node) => {
        const m = node.mesh;
        const targetH = HEIGHT[node.status] ?? HEIGHT.skipped;
        const targetColor = TARGET_COLOR[node.status] ?? TARGET_COLOR.skipped;
        const mat = m.material as THREE.MeshStandardMaterial;
        // Snap once within tolerance: a lerp alone only approaches its target and would keep the loop alive forever.
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
        // The running block breathes with real time, and only while it is running.
        const pulse = node.status === 'running' ? 0.25 + 0.25 * Math.sin(t / 220) : 0;
        mat.emissive.copy(targetColor).multiplyScalar(pulse);
        if (node.status === 'running') moving = true;
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
      state.nodes.forEach((node) => {
        node.mesh.geometry.dispose();
        (node.mesh.material as THREE.Material).dispose();
      });
      renderer.dispose();
      renderer.domElement.remove();
      three.current = null;
    };
  }, []);

  // The scene follows the entries: one block per step, rebuilt only when the step list itself changes.
  useEffect(() => {
    const s = three.current;
    if (!s) return;
    // Pull the camera back so every step fits the frame, whatever the number of steps.
    const halfWidth = (Math.max(entries.length, 1) * SPACING) / 2 + 0.8;
    const distance = halfWidth / (Math.tan(THREE.MathUtils.degToRad(s.camera.fov / 2)) * s.camera.aspect);
    // Height moves with the distance, so the angle at which the row is seen stays the same whatever the step count.
    s.camera.position.set(0, distance * 0.52, distance);
    s.camera.lookAt(0, 0.6, 0);
    const seen = new Set<string>();
    entries.forEach((entry, i) => {
      seen.add(entry.skillCode);
      const x = (i - (entries.length - 1) / 2) * SPACING;
      // A step that ran but flagged something is a warning, the same as the timeline shows it.
      const status = entry.stepStatus === 'completed' && entry.warning ? 'warning' : entry.stepStatus;
      let node = s.nodes.get(entry.skillCode);
      if (!node) {
        const geo = new THREE.BoxGeometry(0.9, 1, 0.9);
        const mat = new THREE.MeshStandardMaterial({ color: COLOR.skipped, roughness: 0.45, metalness: 0.1 });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(x, 0, 0);
        mesh.scale.y = 0.05;
        s.group.add(mesh);
        node = { mesh, status };
        s.nodes.set(entry.skillCode, node);
      }
      node.status = status;
      node.mesh.position.x = x;
    });
    // Steps no longer in the feed are removed, so the model never shows a step that did not run.
    s.nodes.forEach((node, code) => {
      if (seen.has(code)) return;
      s.group.remove(node.mesh);
      node.mesh.geometry.dispose();
      (node.mesh.material as THREE.Material).dispose();
      s.nodes.delete(code);
    });
    s.start();
  }, [entries]);

  const failed = entries.filter((e) => e.stepStatus === 'failed');

  // Inline it is a picture: pointer events pass through, so it never traps the wheel or blocks the page under it.
  // Full screen (expanded, in a portal) is the one place it takes the pointer.
  const surface = (
    <div className={`relative w-full overflow-hidden rounded-xl border border-border bg-card ${expanded ? 'h-full min-h-[60vh]' : 'h-[240px]'}`}>
      <div ref={host} className="absolute inset-0" style={{ pointerEvents: expanded ? 'auto' : 'none' }} role="img" aria-label={`Formula engine: ${entries.length} steps, ${failed.length} failed`} />
      {entries.length === 0 && (
        <p className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">No steps have run yet.</p>
      )}
      {!webgl && (
        <p role="alert" className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">The 3D view needs WebGL. The steps are listed below.</p>
      )}
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
              <p className="text-sm font-semibold text-foreground">Formula engine: each pipeline step as a block</p>
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
