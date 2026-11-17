import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { ArrowUpRight } from '@phosphor-icons/react';

/**
 * The hero action of a finished run: a small solid block, drawn in 3D, that turns while the pointer is on it and rests
 * otherwise. Pressing it opens the Output page. Without WebGL the same button is drawn as plain text.
 */
export function OutputButton({ onOpen, disabled = false }: { onOpen: () => void; disabled?: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState(false);
  const [webgl, setWebgl] = useState(true);
  const spin = useRef({ on: false, angle: 0 });
  const wakeRef = useRef<(() => void) | null>(null);

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
    renderer.setSize(44, 44);
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
    camera.position.set(2.2, 1.8, 4.2);
    camera.lookAt(0, 0, 0);
    scene.add(new THREE.AmbientLight(0xffffff, 0.8));
    const key = new THREE.DirectionalLight(0xffffff, 1.2);
    key.position.set(3, 5, 4);
    scene.add(key);

    // A solid block with bevelled edges: the report, as an object.
    const block = new THREE.Mesh(
      new THREE.BoxGeometry(1.5, 1.5, 1.5),
      new THREE.MeshStandardMaterial({ color: 0x22a8c9, roughness: 0.35, metalness: 0.15 }),
    );
    scene.add(block);

    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (spin.current.on) spin.current.angle += dt * 1.6;
      block.rotation.y = spin.current.angle;
      block.rotation.x = spin.current.on ? Math.sin(spin.current.angle * 0.5) * 0.25 : 0;
      renderer.render(scene, camera);
      // The loop runs only while the block turns; at rest it draws once and stops.
      frame = spin.current.on ? requestAnimationFrame(tick) : 0;
    };
    renderer.render(scene, camera);
    const wake = () => {
      if (!frame) {
        last = performance.now();
        frame = requestAnimationFrame(tick);
      }
    };
    wakeRef.current = wake;
    return () => {
      cancelAnimationFrame(frame);
      wakeRef.current = null;
      block.geometry.dispose();
      (block.material as THREE.Material).dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  useEffect(() => {
    spin.current.on = hover && !disabled;
    wakeRef.current?.();
  }, [hover, disabled]);

  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={disabled}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={() => setHover(true)}
      onBlur={() => setHover(false)}
      className="group inline-flex w-full items-center gap-3 rounded-xl border border-brand/40 bg-card px-4 py-3 text-left transition hover:border-brand focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:opacity-50"
      data-testid="output-button"
    >
      <span ref={host} className="flex h-11 w-11 shrink-0 items-center justify-center" aria-hidden>
        {!webgl && <span className="h-7 w-7 rounded-md bg-brand" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold text-foreground">Output</span>
        <span className="block text-xs text-muted-foreground">Reports, charts, the Superset view, review and downloads</span>
      </span>
      <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground transition group-hover:text-foreground" aria-hidden />
    </button>
  );
}
