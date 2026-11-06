const fs = require('fs');
const path = require('path');

const rootDir = path.resolve(__dirname, '..');
const target = path.join(rootDir, 'app', 'static', 'index.html');
const backup = path.join(rootDir, 'app', 'static', 'index.backup.html');

let html = fs.readFileSync(backup, 'utf8');

// Replace CSS and modernize design
const modernCss = `
  /* ------------------------------------------------------------------ *
   * ResearchLens — Next-Gen Spatial Aesthetic (Glass, Depth, Motion)
   * ------------------------------------------------------------------ */
  :root {
    color-scheme: light;
    --bg-base: #0B0F17;
    --bg-surface: rgba(18, 24, 38, 0.75);
    --bg-surface-elevated: rgba(28, 36, 56, 0.65);
    --bg-surface-hover: rgba(38, 48, 74, 0.85);
    --border-subtle: rgba(255, 255, 255, 0.08);
    --border-focus: rgba(99, 102, 241, 0.5);
    --border-highlight: rgba(255, 255, 255, 0.15);

    --primary: #6366F1;
    --primary-glow: rgba(99, 102, 241, 0.35);
    --primary-hover: #4F46E5;
    --accent: #06B6D4;
    --accent-glow: rgba(6, 182, 212, 0.35);
    --accent-violet: #8B5CF6;

    --ink-primary: #F8FAFC;
    --ink-secondary: #94A3B8;
    --ink-muted: #64748B;

    --ok: #10B981;
    --ok-bg: rgba(16, 185, 129, 0.12);
    --ok-border: rgba(16, 185, 129, 0.3);
    --warn: #F59E0B;
    --warn-bg: rgba(245, 158, 11, 0.12);
    --warn-border: rgba(245, 158, 11, 0.3);
    --err: #EF4444;
    --err-bg: rgba(239, 68, 68, 0.12);
    --err-border: rgba(239, 68, 68, 0.3);
    --neutral-bg: rgba(148, 163, 184, 0.1);
    --neutral: #CBD5E1;

    --radius-xl: 28px;
    --radius-lg: 20px;
    --radius-md: 14px;
    --radius-sm: 10px;
    --radius-xs: 6px;

    --font-heading: 'Outfit', -apple-system, sans-serif;
    --font-body: 'Plus Jakarta Sans', -apple-system, sans-serif;
    --font-mono: 'JetBrains Mono', monospace;

    --shadow-soft: 0 10px 30px -5px rgba(0, 0, 0, 0.4), 0 0 1px 1px rgba(255, 255, 255, 0.05);
    --shadow-glass: 0 20px 50px -10px rgba(0, 0, 0, 0.6), inset 0 1px 1px rgba(255, 255, 255, 0.15);
    --shadow-glow: 0 0 25px -3px var(--primary-glow);
  }

  * , *::before, *::after { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body {
    margin: 0;
    background: var(--bg-base);
    color: var(--ink-primary);
    font-family: var(--font-body);
    font-size: 15px;
    line-height: 1.6;
    overflow-x: hidden;
    -webkit-font-smoothing: antialiased;
    position: relative;
    min-height: 100vh;
  }

  /* ---------- Ambient 3D Mesh & Floating Floating Elements ---------- */
  .ambient-canvas-wrapper {
    position: fixed;
    top: 0; left: 0; width: 100vw; height: 100vh;
    overflow: hidden;
    z-index: 0;
    pointer-events: none;
  }
  .ambient-orb {
    position: absolute;
    border-radius: 50%;
    filter: blur(80px);
    opacity: 0.45;
    animation: floatOrb 22s ease-in-out infinite alternate;
  }
  .orb-1 {
    width: 500px; height: 500px;
    top: -120px; left: -100px;
    background: radial-gradient(circle, #4338CA 0%, rgba(99, 102, 241, 0.2) 70%, transparent 100%);
    animation-duration: 25s;
  }
  .orb-2 {
    width: 600px; height: 600px;
    top: 25%; right: -150px;
    background: radial-gradient(circle, #0891B2 0%, rgba(6, 182, 212, 0.25) 60%, transparent 100%);
    animation-duration: 30s;
    animation-delay: -5s;
  }
  .orb-3 {
    width: 550px; height: 550px;
    bottom: -150px; left: 20%;
    background: radial-gradient(circle, #7C3AED 0%, rgba(139, 92, 246, 0.2) 65%, transparent 100%);
    animation-duration: 28s;
    animation-delay: -10s;
  }
  .orb-4 {
    width: 350px; height: 350px;
    top: 60%; left: -80px;
    background: radial-gradient(circle, #0284C7 0%, rgba(56, 189, 248, 0.2) 65%, transparent 100%);
    animation-duration: 20s;
    animation-delay: -7s;
  }
  .ambient-grid-overlay {
    position: absolute;
    inset: 0;
    background-image: radial-gradient(rgba(255, 255, 255, 0.07) 1px, transparent 1px);
    background-size: 32px 32px;
    mask-image: radial-gradient(ellipse at center, rgba(0,0,0,1) 40%, rgba(0,0,0,0) 80%);
    opacity: 0.65;
  }
  @keyframes floatOrb {
    0% { transform: translate(0, 0) scale(1) rotate(0deg); }
    50% { transform: translate(60px, 40px) scale(1.1) rotate(180deg); }
    100% { transform: translate(-40px, 70px) scale(0.95) rotate(360deg); }
  }

  /* 3D floating visual decoration in background */
  .spatial-mesh-card {
    position: absolute;
    width: 140px;
    height: 140px;
    border-radius: 24px;
    background: linear-gradient(135deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.01));
    backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.12);
    box-shadow: 0 15px 35px rgba(0,0,0,0.4), inset 0 1px 1px rgba(255,255,255,0.2);
    pointer-events: none;
    z-index: 1;
    transform: perspective(800px) rotateX(15deg) rotateY(-20deg) rotateZ(5deg);
    animation: floatingMesh 10s ease-in-out infinite alternate;
  }
  @keyframes floatingMesh {
    0% { transform: perspective(800px) rotateX(15deg) rotateY(-20deg) translateY(0px); }
    100% { transform: perspective(800px) rotateX(22deg) rotateY(-12deg) translateY(-25px); }
  }

  /* ---------- Typography & Global ---------- */
  h1, h2, h3, .serif {
    font-family: var(--font-heading);
    font-weight: 700;
    letter-spacing: -0.025em;
    color: #FFFFFF;
  }
  h1 {
    font-size: clamp(2.3rem, 1.8rem + 2.8vw, 3.8rem);
    line-height: 1.08;
    margin: 0 0 1rem;
    background: linear-gradient(135deg, #FFFFFF 20%, #CBD5E1 60%, #94A3B8 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  h2 {
    font-size: clamp(1.4rem, 1.15rem + 1vw, 2rem);
    margin: 0;
    background: linear-gradient(135deg, #FFFFFF 40%, #94A3B8 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  h3 { font-size: 1.25rem; margin: 0 0 .5rem; font-weight: 600; color: #F1F5F9; }
  h4 {
    font-size: .8rem;
    margin: 1.1rem 0 .4rem;
    letter-spacing: .12em;
    text-transform: uppercase;
    color: var(--accent);
    font-family: var(--font-body);
    font-weight: 700;
  }
  p { margin: 0 0 .8rem; color: var(--ink-secondary); }
  a { color: var(--accent); text-decoration: none; transition: color .2s ease; }
  a:hover { color: #38BDF8; text-decoration: underline; }
  :focus-visible { outline: 2px solid var(--primary); outline-offset: 3px; border-radius: 12px; }

  /* ---------- Floating Bubble Pill Nav Bar ---------- */
  .app {
    position: relative;
    z-index: 10;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  .floating-nav-bar {
    position: fixed;
    top: 20px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 100;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.45rem 0.65rem;
    background: rgba(15, 23, 42, 0.75);
    backdrop-filter: blur(24px) saturate(180%);
    -webkit-backdrop-filter: blur(24px) saturate(180%);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 9999px;
    box-shadow: 0 20px 40px -10px rgba(0, 0, 0, 0.5), inset 0 1px 1px rgba(255, 255, 255, 0.15);
    transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  }
  .floating-nav-bar:hover {
    border-color: rgba(255, 255, 255, 0.22);
    box-shadow: 0 25px 50px -10px rgba(0, 0, 0, 0.7), inset 0 1px 1px rgba(255, 255, 255, 0.25);
  }

  .floating-brand {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.3rem 0.75rem 0.3rem 0.4rem;
    border-radius: 9999px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.06);
  }
  .floating-brand-mark {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: linear-gradient(135deg, #6366F1, #06B6D4);
    display: grid;
    place-items: center;
    box-shadow: 0 0 12px var(--primary-glow);
  }
  .floating-brand-text {
    font-family: var(--font-heading);
    font-weight: 700;
    font-size: 0.95rem;
    letter-spacing: -0.01em;
    background: linear-gradient(135deg, #FFFFFF, #E2E8F0);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }

  .nav-bubble-group {
    display: flex;
    align-items: center;
    gap: 0.25rem;
  }
  .nav-bubble-link {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.42rem 0.95rem;
    border-radius: 9999px;
    color: var(--ink-secondary);
    font-size: 0.85rem;
    font-weight: 600;
    text-decoration: none;
    transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    position: relative;
    border: 1px solid transparent;
  }
  .nav-bubble-link:hover {
    color: #FFFFFF;
    background: rgba(255, 255, 255, 0.08);
    transform: translateY(-1px);
    text-decoration: none;
  }
  .nav-bubble-link.is-active {
    color: #FFFFFF;
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.25), rgba(6, 182, 212, 0.25));
    border-color: rgba(99, 102, 241, 0.4);
    box-shadow: 0 0 15px rgba(99, 102, 241, 0.25);
  }
  .nav-bubble-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--ink-muted);
    transition: all 0.2s ease;
  }
  .nav-bubble-link.is-active .nav-bubble-dot {
    background: var(--accent);
    box-shadow: 0 0 8px var(--accent);
  }

  /* Top Right Status Badge on Floating Bar */
  .service-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.35rem 0.85rem;
    border-radius: 9999px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid var(--border-subtle);
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--ink-secondary);
    white-space: nowrap;
    transition: all 0.3s ease;
  }
  .service-pill .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--ink-muted);
  }
  .service-pill.is-ok {
    background: var(--ok-bg);
    border-color: var(--ok-border);
    color: #34D399;
  }
  .service-pill.is-ok .dot {
    background: #10B981;
    box-shadow: 0 0 8px #10B981;
  }
  .service-pill.is-bad {
    background: var(--err-bg);
    border-color: var(--err-border);
    color: #F87171;
  }
  .service-pill.is-bad .dot {
    background: #EF4444;
    box-shadow: 0 0 8px #EF4444;
  }
  .service-pill.is-checking .dot {
    background: #F59E0B;
    box-shadow: 0 0 8px #F59E0B;
    animation: pulse 1.1s ease-in-out infinite;
  }

  /* Legacy sidebar hidden as we modernise to top floating bubble navbar */
  .sidebar { display: none !important; }

  /* ---------- Content & Layout ---------- */
  .main {
    flex: 1;
    width: 100%;
    max-width: 1320px;
    margin: 0 auto;
    padding: 95px 1.5rem 5rem;
  }
  .topbar { display: none !important; }
  .content { padding: 0; width: 100%; }

  /* ---------- Cards & Glassmorphic Surfaces ---------- */
  .section {
    margin-bottom: 3.5rem;
    scroll-margin-top: 110px;
    animation: fadeInSection 0.6s ease-out both;
  }
  @keyframes fadeInSection {
    from { opacity: 0; transform: translateY(18px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .section-head {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1.2rem;
    margin-bottom: 1.4rem;
    flex-wrap: wrap;
  }
  .section-kicker {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.74rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 0.4rem;
  }
  .section-sub {
    color: var(--ink-secondary);
    font-size: 0.98rem;
    max-width: 72ch;
    margin-top: 0.35rem;
  }

  .card {
    background: var(--bg-surface);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    padding: 1.6rem 1.8rem;
    box-shadow: var(--shadow-soft);
    position: relative;
    overflow: hidden;
    transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), border-color 0.3s ease, box-shadow 0.3s ease;
  }
  .card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.15), transparent);
  }
  .card:hover {
    border-color: rgba(255, 255, 255, 0.15);
    box-shadow: var(--shadow-glass);
  }
  .card + .card { margin-top: 1.2rem; }
  .card-flat {
    background: rgba(18, 24, 38, 0.45);
    box-shadow: none;
  }
  .grid-2 {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    gap: 1.4rem;
    align-items: stretch;
  }

  /* ---------- 3D Hero Showcase Section ---------- */
  .hero {
    position: relative;
    overflow: hidden;
    border-radius: var(--radius-xl);
    background: linear-gradient(135deg, rgba(28, 36, 56, 0.8) 0%, rgba(15, 23, 42, 0.95) 100%);
    backdrop-filter: blur(30px);
    -webkit-backdrop-filter: blur(30px);
    border: 1px solid rgba(255, 255, 255, 0.12);
    padding: clamp(2rem, 4vw, 3.5rem);
    box-shadow: var(--shadow-glass);
  }
  .hero::before {
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(circle at 85% 20%, rgba(99, 102, 241, 0.25), transparent 45%),
                radial-gradient(circle at 15% 90%, rgba(6, 182, 212, 0.2), transparent 45%);
    pointer-events: none;
  }
  .hero-inner {
    position: relative;
    z-index: 2;
    max-width: 68ch;
  }
  .eyebrow {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.74rem;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #A5B4FC;
    background: rgba(99, 102, 241, 0.15);
    border: 1px solid rgba(99, 102, 241, 0.3);
    border-radius: 9999px;
    padding: 0.35rem 0.95rem;
    margin-bottom: 1.2rem;
    box-shadow: 0 0 15px rgba(99, 102, 241, 0.2);
  }
  .hero-actions {
    display: flex;
    gap: 0.9rem;
    flex-wrap: wrap;
    margin-top: 1.8rem;
  }

  .steps {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
    gap: 1rem;
    margin-top: 2rem;
  }
  .step {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: var(--radius-md);
    padding: 1.1rem 1.2rem;
    backdrop-filter: blur(10px);
    transition: transform 0.25s ease, background 0.25s ease, border-color 0.25s ease;
  }
  .step:hover {
    transform: translateY(-3px);
    background: rgba(255, 255, 255, 0.07);
    border-color: rgba(99, 102, 241, 0.3);
  }
  .step b {
    display: flex;
    align-items: center;
    font-family: var(--font-heading);
    font-size: 1.05rem;
    color: #F8FAFC;
    margin-bottom: 0.4rem;
  }
  .step span {
    color: var(--ink-secondary);
    font-size: 0.88rem;
    line-height: 1.45;
  }
  .step-n {
    display: inline-grid;
    place-items: center;
    width: 26px;
    height: 26px;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--primary), var(--accent));
    color: #fff;
    font-size: 0.76rem;
    font-weight: 800;
    margin-right: 0.6rem;
    box-shadow: 0 0 10px var(--primary-glow);
    flex-shrink: 0;
  }

  /* ---------- Forms & Inputs ---------- */
  label {
    display: block;
    margin: 0.9rem 0 0.35rem;
    font-weight: 600;
    font-size: 0.86rem;
    color: #E2E8F0;
  }
  .field-hint {
    font-weight: 400;
    color: var(--ink-muted);
  }
  input[type=text], input[type=number], input[type=search], textarea {
    width: 100%;
    padding: 0.75rem 1rem;
    font: inherit;
    font-family: var(--font-body);
    color: #F8FAFC;
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: var(--radius-sm);
    transition: all 0.25s ease;
    backdrop-filter: blur(8px);
  }
  input[type=text]:focus, input[type=number]:focus, input[type=search]:focus, textarea:focus {
    border-color: var(--primary);
    box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.25), 0 0 15px rgba(99, 102, 241, 0.2);
    outline: none;
    background: rgba(15, 23, 42, 0.85);
  }
  textarea {
    min-height: 110px;
    resize: vertical;
    line-height: 1.6;
    font-size: 0.96rem;
  }
  .row { display: flex; gap: 1.1rem; flex-wrap: wrap; }
  .row > * { flex: 1 1 240px; min-width: 0; }
  .options-row {
    display: grid;
    grid-template-columns: 140px minmax(0, 1fr);
    gap: 1.1rem;
    align-items: end;
  }

  /* ---------- Interactive Buttons ---------- */
  button {
    font: inherit;
    cursor: pointer;
    border-radius: 9999px;
    font-family: var(--font-body);
    font-weight: 600;
    transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  }
  button:disabled {
    cursor: not-allowed;
    opacity: 0.45;
    transform: none !important;
  }
  .btn {
    padding: 0.65rem 1.4rem;
    border: 1px solid transparent;
    font-size: 0.92rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
  }
  .btn-primary {
    background: linear-gradient(135deg, #6366F1 0%, #4F46E5 100%);
    color: #FFFFFF;
    border-color: rgba(255, 255, 255, 0.15);
    box-shadow: 0 4px 18px var(--primary-glow);
  }
  .btn-primary:hover:not(:disabled) {
    background: linear-gradient(135deg, #4F46E5 0%, #4338CA 100%);
    transform: translateY(-2px);
    box-shadow: 0 6px 24px rgba(99, 102, 241, 0.5);
  }
  .btn-primary:active:not(:disabled) {
    transform: translateY(0);
  }
  .btn-ghost {
    background: rgba(255, 255, 255, 0.05);
    border-color: rgba(255, 255, 255, 0.12);
    color: #F8FAFC;
    backdrop-filter: blur(8px);
  }
  .btn-ghost:hover:not(:disabled) {
    border-color: rgba(255, 255, 255, 0.25);
    background: rgba(255, 255, 255, 0.1);
    transform: translateY(-2px);
  }
  .btn-quiet {
    background: transparent;
    border-color: transparent;
    color: var(--ink-secondary);
    padding: 0.4rem 0.8rem;
    font-size: 0.84rem;
  }
  .btn-quiet:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.1);
    color: #F8FAFC;
  }
  .btn-small {
    padding: 0.42rem 0.95rem;
    font-size: 0.84rem;
  }
  .btn-row {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    flex-wrap: wrap;
    margin-top: 1.1rem;
  }

  /* ---------- Drop Zone (Interactive 3D Glass) ---------- */
  .drop-zone {
    border: 2px dashed rgba(99, 102, 241, 0.35);
    border-radius: var(--radius-md);
    background: rgba(15, 23, 42, 0.45);
    padding: 1.6rem 1.2rem;
    text-align: center;
    transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    position: relative;
    cursor: pointer;
  }
  .drop-zone:hover {
    border-color: var(--accent);
    background: rgba(6, 182, 212, 0.06);
    transform: translateY(-2px);
  }
  .drop-zone.dragging {
    border-color: var(--primary);
    background: rgba(99, 102, 241, 0.12);
    transform: scale(1.02);
    box-shadow: 0 0 25px var(--primary-glow);
  }
  .drop-zone input[type=file] {
    width: 100%;
    margin-bottom: 0.6rem;
    font-size: 0.86rem;
    color: var(--ink-secondary);
  }
  .drop-title {
    font-family: var(--font-heading);
    font-size: 1.15rem;
    font-weight: 600;
    color: #F8FAFC;
    margin: 0 0 0.3rem;
  }
  .file-name { font-size: 0.86rem; }
  .file-name.has-file {
    color: #38BDF8;
    font-weight: 600;
    background: rgba(56, 189, 248, 0.1);
    padding: 0.25rem 0.75rem;
    border-radius: 9999px;
    display: inline-block;
  }

  progress {
    width: 100%;
    height: 8px;
    margin-top: 0.9rem;
    border: none;
    border-radius: 9999px;
    overflow: hidden;
    background: rgba(255, 255, 255, 0.08);
  }
  progress::-webkit-progress-bar { background: rgba(255, 255, 255, 0.08); border-radius: 9999px; }
  progress::-webkit-progress-value {
    background: linear-gradient(90deg, var(--primary), var(--accent));
    border-radius: 9999px;
    box-shadow: 0 0 10px var(--accent-glow);
  }
  progress::-moz-progress-bar {
    background: linear-gradient(90deg, var(--primary), var(--accent));
    border-radius: 9999px;
  }

  /* ---------- Badges & Tags ---------- */
  .badge {
    display: inline-block;
    padding: 0.26rem 0.75rem;
    border-radius: 9999px;
    font-size: 0.76rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    background: var(--neutral-bg);
    color: var(--neutral);
    border: 1px solid var(--border-subtle);
    margin: 0 0.4rem 0.4rem 0;
  }
  .badge.ok {
    background: var(--ok-bg);
    color: #34D399;
    border-color: var(--ok-border);
  }
  .badge.warn {
    background: var(--warn-bg);
    color: #FBBF24;
    border-color: var(--warn-border);
  }
  .badge.err {
    background: var(--err-bg);
    color: #F87171;
    border-color: var(--err-border);
  }
  .badge.neutral {
    background: rgba(255, 255, 255, 0.06);
    color: #CBD5E1;
  }
  .pill {
    display: inline-block;
    padding: 0.22rem 0.7rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
    background: rgba(139, 92, 246, 0.15);
    color: #C4B5FD;
    border: 1px solid rgba(139, 92, 246, 0.25);
    margin: 0 0.35rem 0.35rem 0;
  }
  .pill.peach {
    background: rgba(249, 115, 22, 0.12);
    color: #FDBA74;
    border-color: rgba(249, 115, 22, 0.25);
  }
  .pill.sage {
    background: rgba(16, 185, 129, 0.12);
    color: #6EE7B7;
    border-color: rgba(16, 185, 129, 0.25);
  }

  /* ---------- History & Answer Cards ---------- */
  .history-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1.2rem;
    margin: 2rem 0 0.9rem;
    flex-wrap: wrap;
  }
  .history-entry {
    scroll-margin-top: 120px;
    animation: slideInUp 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
  }
  @keyframes slideInUp {
    from { opacity: 0; transform: translateY(16px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .history-entry.latest {
    border-color: rgba(99, 102, 241, 0.4);
    box-shadow: 0 15px 40px -10px rgba(99, 102, 241, 0.3), inset 0 1px 1px rgba(255, 255, 255, 0.15);
  }
  .question-heading { margin: 0.1rem 0 0.35rem; }
  .question {
    white-space: pre-wrap;
    font-weight: 700;
    font-size: 1.12rem;
    color: #F8FAFC;
    margin: 0 0 0.5rem;
    font-family: var(--font-heading);
  }
  .answer {
    white-space: pre-wrap;
    margin: 0.3rem 0 0.6rem;
    color: #E2E8F0;
    font-size: 0.98rem;
    line-height: 1.65;
  }
  .error-detail {
    white-space: pre-wrap;
    color: #FCA5A5;
    background: rgba(239, 68, 68, 0.08);
    padding: 0.8rem;
    border-radius: var(--radius-sm);
    font-family: var(--font-mono);
    font-size: 0.85rem;
  }
  .muted { color: var(--ink-secondary); font-size: 0.88rem; }
  .card-error { border-left: 4px solid #EF4444; }

  /* Tables */
  table {
    border-collapse: collapse;
    width: 100%;
    font-size: 0.86rem;
    margin-top: 0.5rem;
  }
  th, td {
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    padding: 0.5rem 0.75rem;
    text-align: left;
    vertical-align: top;
  }
  th {
    font-weight: 700;
    color: #94A3B8;
    font-size: 0.75rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    background: rgba(255, 255, 255, 0.02);
  }
  .table-scroll {
    overflow-x: auto;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: var(--radius-sm);
    background: rgba(15, 23, 42, 0.4);
  }
  .table-scroll table { margin: 0; }
  .table-scroll th, .table-scroll td { white-space: nowrap; }

  details {
    margin-top: 0.7rem;
    border-top: 1px dashed rgba(255, 255, 255, 0.1);
    padding-top: 0.6rem;
  }
  details > summary {
    cursor: pointer;
    font-weight: 600;
    font-size: 0.88rem;
    color: var(--accent);
    transition: color 0.2s ease;
  }
  details > summary:hover { color: #38BDF8; }
  details[open] > summary { margin-bottom: 0.5rem; }

  /* ---------- Masonry Cards ---------- */
  .masonry {
    column-count: 3;
    column-gap: 1.2rem;
  }
  .masonry > * {
    break-inside: avoid;
    display: block;
    margin-bottom: 1.2rem;
  }
  @media (max-width: 1200px) { .masonry { column-count: 2; } }
  @media (max-width: 768px) { .masonry { column-count: 1; } }

  .paper-card, .media-card {
    background: var(--bg-surface);
    backdrop-filter: blur(16px);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 1.2rem 1.3rem;
    box-shadow: var(--shadow-soft);
    transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  }
  .paper-card:hover, .media-card:hover {
    box-shadow: var(--shadow-glass);
    border-color: rgba(99, 102, 241, 0.35);
    transform: translateY(-3px) scale(1.01);
  }
  .paper-title {
    font-family: var(--font-heading);
    font-size: 1.1rem;
    font-weight: 600;
    color: #F8FAFC;
    margin: 0 0 0.35rem;
  }
  .paper-meta {
    color: var(--ink-secondary);
    font-size: 0.82rem;
    margin-bottom: 0.45rem;
  }
  .paper-abstract {
    font-size: 0.88rem;
    color: #CBD5E1;
    line-height: 1.5;
  }
  .media-figure {
    display: block;
    width: 100%;
    height: auto;
    border-radius: var(--radius-sm);
    border: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(15, 23, 42, 0.6);
  }
  .media-caption {
    font-size: 0.88rem;
    margin-top: 0.6rem;
    color: #CBD5E1;
  }
  .media-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    margin-top: 0.6rem;
  }

  .empty-state {
    border: 1.5px dashed rgba(255, 255, 255, 0.12);
    border-radius: var(--radius-lg);
    padding: 2.2rem 1.5rem;
    text-align: center;
    color: var(--ink-secondary);
    background: rgba(15, 23, 42, 0.35);
  }
  .empty-state b {
    display: block;
    font-family: var(--font-heading);
    color: #F8FAFC;
    font-size: 1.15rem;
    margin-bottom: 0.3rem;
  }

  .hidden { display: none !important; }
  .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }

  .spinner {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    border: 2px solid rgba(99, 102, 241, 0.25);
    border-top-color: var(--accent);
    animation: spin 0.7s linear infinite;
    display: inline-block;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .loader-dots {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    height: 16px;
    flex: 0 0 auto;
    align-self: center;
  }
  .loader-dots i {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--accent);
    opacity: 0.3;
    animation: dotsBounce 0.95s ease-in-out infinite both;
  }
  .loader-dots i:nth-child(1) { animation-delay: 0s; }
  .loader-dots i:nth-child(2) { animation-delay: 0.16s; }
  .loader-dots i:nth-child(3) { animation-delay: 0.32s; }
  @keyframes dotsBounce {
    0%, 80%, 100% { opacity: 0.3; transform: scale(0.7); }
    40% { opacity: 1; transform: scale(1.2); }
  }

  #evidence-loader { width: 32px; }
  .media-caption-clamp {
    display: -webkit-box;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .caption-toggle {
    font-size: 0.8rem;
    color: var(--accent);
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 9999px;
    padding: 0.2rem 0.65rem;
  }
  #ask-status {
    min-height: 1.5rem;
    margin-top: 0.8rem;
    display: flex;
    align-items: center;
    gap: 0.6rem;
    font-weight: 500;
  }
  #status-line { margin-top: 0.8rem; font-size: 0.86rem; color: var(--ink-secondary); }
  #evidence-status, #arxiv-status { min-height: 1.3rem; margin-top: 0.65rem; }

  footer {
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    padding: 1.8rem 0;
    margin-top: 4rem;
    color: var(--ink-muted);
    font-size: 0.86rem;
    text-align: center;
  }

  /* Responsive Adjustments */
  @media (max-width: 900px) {
    .floating-nav-bar {
      width: calc(100% - 24px);
      justify-content: space-between;
      top: 10px;
      padding: 0.4rem 0.6rem;
    }
    .floating-brand-text { display: none; }
    .nav-bubble-link { padding: 0.4rem 0.65rem; font-size: 0.8rem; }
    .main { padding: 80px 1rem 3rem; }
    .options-row { grid-template-columns: 1fr; }
    .grid-2 { grid-template-columns: 1fr; }
  }
`;

// Extract everything inside <style> and replace with modernCss
const styleRegex = /<style>[\s\S]*?<\/style>/i;
html = html.replace(styleRegex, '<style>' + modernCss + '</style>');

// Inject Google fonts into head
const fontImports = `
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
`;
html = html.replace('</head>', fontImports + '\n</head>');

// Replace header/nav with floating bubble bar and ambient 3D visuals
const floatingNavBarHtml = `
  <!-- Ambient 3D Mesh and Moving Light Orbs -->
  <div class="ambient-canvas-wrapper" aria-hidden="true">
    <div class="ambient-orb orb-1"></div>
    <div class="ambient-orb orb-2"></div>
    <div class="ambient-orb orb-3"></div>
    <div class="ambient-orb orb-4"></div>
    <div class="ambient-grid-overlay"></div>
  </div>

  <!-- Floating Nav Bar Bubble -->
  <header class="floating-nav-bar" role="banner">
    <div class="floating-brand">
      <div class="floating-brand-mark" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2.2" stroke-linecap="round">
          <circle cx="10.5" cy="10.5" r="6.5"></circle>
          <path d="M15.4 15.4 21 21"></path>
          <path d="M7.6 8.4h5.8M7.6 11.2h3.6"></path>
        </svg>
      </div>
      <span class="floating-brand-text">ResearchLens</span>
    </div>

    <nav class="nav-bubble-group" aria-label="Workspace sections">
      <a class="nav-bubble-link is-active" href="#section-home" data-nav><span class="nav-bubble-dot"></span>Workspace</a>
      <a class="nav-bubble-link" href="#section-ask" data-nav><span class="nav-bubble-dot"></span>Ask Question</a>
      <a class="nav-bubble-link" href="#section-papers" data-nav><span class="nav-bubble-dot"></span>My Papers</a>
      <a class="nav-bubble-link" href="#section-evidence" data-nav><span class="nav-bubble-dot"></span>Figures &amp; Tables</a>
      <a class="nav-bubble-link" href="#history-header" data-nav><span class="nav-bubble-dot"></span>History</a>
    </nav>

    <div class="service-pill" id="service-pill" role="status" aria-live="polite">
      <span class="dot"></span>Checking services…
    </div>
  </header>
`;

html = html.replace('<body>', '<body>\n' + floatingNavBarHtml);

// Add 3D card decor to hero
const heroCardDecor = `
            <div class="spatial-mesh-card" style="top: 20px; right: 30px;" aria-hidden="true"></div>
`;
html = html.replace('<div class="hero">', '<div class="hero">' + heroCardDecor);

fs.writeFileSync(target, html, 'utf8');
console.log('Successfully upgraded index.html with aesthetic 3D design and floating navbar');

