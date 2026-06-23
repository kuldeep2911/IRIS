// Avatar.tsx — optional 3D "TalkingHead"-style avatar in a Three.js canvas.
//
// This is the IRIS face: idle breathing + blink when quiet, mouth animation
// driven by TTS audio amplitude (visemes/lip-sync) while speaking, and visual
// states (idle / thinking / speaking / success / concern). It is toggleable in
// Settings (off => voice-only).
//
// The full met4citizen **TalkingHead** library (Ready Player Me GLB + viseme
// morph targets) plugs in where marked below; this self-contained head keeps the
// dashboard building without external avatar assets.
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { useStore, type AvatarState } from "../store";

const STATE_COLORS: Record<AvatarState, number> = {
  idle: 0x2563eb, // accent blue
  thinking: 0x06b6d4, // cyan
  speaking: 0x22d3ee,
  success: 0x10b981,
  concern: 0xf59e0b,
};

export default function Avatar({ audioEl }: { audioEl?: HTMLAudioElement | null }) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const avatarState = useStore((s) => s.avatarState);
  const stateRef = useRef<AvatarState>(avatarState);
  stateRef.current = avatarState;

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const width = mount.clientWidth || 280;
    const height = mount.clientHeight || 280;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    camera.position.z = 4;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(2, 3, 4);
    scene.add(key);

    // --- head + eyes + mouth (TalkingHead morph targets plug in here) ---
    const head = new THREE.Mesh(
      new THREE.SphereGeometry(1, 48, 48),
      new THREE.MeshStandardMaterial({ color: STATE_COLORS.idle, roughness: 0.35, metalness: 0.4 }),
    );
    scene.add(head);

    const eyeGeo = new THREE.SphereGeometry(0.12, 16, 16);
    const eyeMat = new THREE.MeshStandardMaterial({ color: 0x0a0a0f });
    const leftEye = new THREE.Mesh(eyeGeo, eyeMat);
    const rightEye = new THREE.Mesh(eyeGeo, eyeMat);
    leftEye.position.set(-0.35, 0.2, 0.92);
    rightEye.position.set(0.35, 0.2, 0.92);
    scene.add(leftEye, rightEye);

    const mouth = new THREE.Mesh(
      new THREE.BoxGeometry(0.5, 0.06, 0.05),
      new THREE.MeshStandardMaterial({ color: 0x0a0a0f }),
    );
    mouth.position.set(0, -0.35, 0.92);
    scene.add(mouth);

    // Audio amplitude analyser for lip-sync (visemes) when speaking.
    let analyser: AnalyserType | null = null;
    if (audioEl) analyser = makeAnalyser(audioEl);

    let raf = 0;
    let blink = 0;
    const clock = new THREE.Clock();
    const mat = head.material as THREE.MeshStandardMaterial;

    const animate = () => {
      const t = clock.getElapsedTime();
      const st = stateRef.current;
      mat.color.lerp(new THREE.Color(STATE_COLORS[st]), 0.06);

      // idle breathing
      const breathe = 1 + Math.sin(t * 1.6) * 0.012;
      head.scale.setScalar(breathe);
      head.rotation.y = Math.sin(t * 0.5) * 0.12;

      // periodic blink
      blink += 0.02;
      const open = Math.abs(Math.sin(blink)) > 0.06 ? 1 : 0.1;
      leftEye.scale.y = open;
      rightEye.scale.y = open;

      // mouth: amplitude-driven when speaking, gentle idle otherwise
      const amp = st === "speaking" ? analyser?.level() ?? 0.5 : 0.04;
      mouth.scale.y = 1 + amp * 6;

      renderer.render(scene, camera);
      raf = requestAnimationFrame(animate);
    };
    animate();

    const onResize = () => {
      const w = mount.clientWidth || width;
      const h = mount.clientHeight || height;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      renderer.dispose();
      if (mount.contains(renderer.domElement)) mount.removeChild(renderer.domElement);
    };
  }, [audioEl]);

  return <div ref={mountRef} className="w-full h-full min-h-[240px]" aria-label="IRIS avatar" />;
}

// --- tiny WebAudio amplitude analyser for lip-sync ---
interface AnalyserType {
  level: () => number;
}

function makeAnalyser(audioEl: HTMLAudioElement): AnalyserType | null {
  try {
    const Ctx = window.AudioContext || (window as any).webkitAudioContext;
    const ctx = new Ctx();
    const src = ctx.createMediaElementSource(audioEl);
    const node = ctx.createAnalyser();
    node.fftSize = 256;
    src.connect(node);
    node.connect(ctx.destination);
    const buf = new Uint8Array(node.frequencyBinCount);
    return {
      level: () => {
        node.getByteFrequencyData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) sum += buf[i];
        return sum / buf.length / 255;
      },
    };
  } catch {
    return null;
  }
}
