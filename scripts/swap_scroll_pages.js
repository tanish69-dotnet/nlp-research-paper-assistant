const fs = require('fs');

// Read the canonical kage.html template from backup or original
let kage = fs.readFileSync('public/landing-pages/kage.html', 'utf8');

// If public/landing-pages/kage.html was already edited, let's reset to pure template if needed
// or read index.backup.html
const researchLensLogic = fs.readFileSync('scripts/researchlens_logic.js', 'utf8');

// 1. Update Title and Metadata
kage = kage.replace(
  /<title>.*?<\/title>/,
  '<title>ResearchLens — Multimodal Evidence Intelligence</title>'
);

// 2. Update Preloader
kage = kage.replace('影の道', 'RESEARCHLENS');
kage = kage.replace('Raising the mountain temple', 'Initialising Multimodal Evidence Engine');

// 3. Update Brand in Nav
kage = kage.replace(
  /<span class="brand-tx">[\s\S]*?<\/span>/,
  '<span class="brand-tx"><b>RESEARCHLENS</b><i>MULTIMODAL EVIDENCE AGENTS</i></span>'
);

// Update Nav Links to follow: 01 Add Paper -> 02 Ask Question -> 03 Evidence -> 04 History
const newNavLinks = `
  <nav class="nav-links" id="navlinks">
    <a class="nav-link" href="#papers-lens" data-cursor><span>01 Upload Paper</span><span class="alt">書庫</span></a>
    <a class="nav-link" href="#ask-lens" data-cursor><span>02 Ask Question</span><span class="alt">推論</span></a>
    <a class="nav-link" href="#evidence-lens" data-cursor><span>03 Evidence</span><span class="alt">証拠</span></a>
    <a class="nav-link" href="#history-lens" data-cursor><span>04 History</span><span class="alt">履歴</span></a>
  </nav>
  <span class="service-pill" id="service-pill" role="status" aria-live="polite" style="margin-left:1rem; padding:6px 14px; border-radius:999px; background:rgba(223,231,224,0.06); border:1px solid rgba(223,231,224,0.15); font-size:12px; display:inline-flex; align-items:center; gap:6px;">
    <span class="dot" style="width:7px; height:7px; border-radius:50%; background:#c9a24a;"></span>Checking services…
  </span>
`;
kage = kage.replace(/<nav class="nav-links" id="navlinks">[\s\S]*?<\/nav>/, newNavLinks);

// 4. Update Hero Titles and Copy
kage = kage.replace('Chapter 00 — The Hidden Gate', 'System 01 — Multimodal Neural Reasoning');
kage = kage.replace(
  `<h1 class="display h-hero">
      <span class="mask-line"><span>Where stillness</span></span>
      <span class="mask-line"><span>reveals the</span></span>
      <span class="mask-line"><span>unseen.</span></span>
    </h1>`,
  `<h1 class="display h-hero">
      <span class="mask-line"><span>Your research,</span></span>
      <span class="mask-line"><span>deeply</span></span>
      <span class="mask-line"><span>understood.</span></span>
    </h1>`
);

kage = kage.replace(
  'Enter Kyoto through its quiet thresholds, where ritual,\n      craft, and memory shape the path.',
  'Scientific papers analyzed as real evidence: figures, tables, and dense text verified claim by claim with honest citations.'
);

kage = kage.replace('<div class="word-fb" aria-hidden="true">KAGE</div>', '<div class="word-fb" aria-hidden="true">RESEARCHLENS</div>');
kage = kage.replace('<span class="v jp">影の道</span>', '<span class="v jp">真実の探求</span>');

// Update Hero Chips
kage = kage.replace(
  /<div class="chapters" id="chips">[\s\S]*?<\/div>\s*<\/div>/,
  `<div class="chapters" id="chips">
      <div class="chip" data-chip="0" data-rv="up" data-cursor onclick="document.getElementById('papers-lens').scrollIntoView({behavior:'smooth'})"><span class="num">01</span>
        <span class="tx"><b>Upload Paper</b><p>Drop demo PDF or import research from arXiv.</p></span></div>
      <div class="chip" data-chip="1" data-rv="up" data-cursor onclick="document.getElementById('ask-lens').scrollIntoView({behavior:'smooth'})"><span class="num">02</span>
        <span class="tx"><b>Ask Questions</b><p>Query over figures, equations, diagrams, and tables.</p></span></div>
      <div class="chip" data-chip="2" data-rv="up" data-cursor onclick="document.getElementById('evidence-lens').scrollIntoView({behavior:'smooth'})"><span class="num">03</span>
        <span class="tx"><b>Visual Evidence</b><p>Inspect extracted charts, figures, and data models.</p></span></div>
      <div class="chip" data-chip="3" data-rv="up" data-cursor onclick="document.getElementById('history-lens').scrollIntoView({behavior:'smooth'})"><span class="num">04</span>
        <span class="tx"><b>Audit History</b><p>Review verified claims, citations, and model reasoning.</p></span></div>
    </div>
  </div>`
);

// =========================================================================
// 2ND PAGE (Chapter 1, data-cam="1"): UPLOAD & ADD RESEARCH PAPER
// =========================================================================
const page2UploadPaper = `
<!-- ============================================================ 2ND PAGE: UPLOAD PAPER -->
<section class="sec" id="papers-lens" data-cam="1" style="min-height:auto; padding-top: clamp(60px, 8vh, 120px);">
  <div class="sec-head" data-rv="fade">
    <span class="k"><b>01</b> — Ingest & Indexing</span><span class="rule"></span><span class="k jp">書庫</span>
  </div>

  <div class="custom-step-grid">
    <div class="step-text-col">
      <h2 class="display h-sec" data-rv="up" style="max-width:none; font-size:clamp(2rem, 3.2vw, 3.2rem); line-height:1.15; margin:0 0 1rem;">
        Add your research paper.
      </h2>
      <p class="body-lg" data-rv="up" style="color:#aab4ad; line-height:1.6; margin-bottom:1.5rem;">
        Upload your PDF research paper or import directly from arXiv. The multimodal ingestion engine parses text passages, isolates structured Markdown tables, and extracts figure images into Chroma vector storage.
      </p>

      <div class="gate-stats" data-rv="up">
        <div><b>PDF</b><span>Multimodal</span></div>
        <div><b>Tables</b><span>Markdown</span></div>
        <div><b>Figures</b><span>Extracted</span></div>
        <div><b>Dense</b><span>BM25 + Dense</span></div>
      </div>
    </div>

    <div class="step-card-col">
      <!-- Upload Card -->
      <div class="rl-glass-card" style="background: rgba(10, 14, 18, 0.78); border: 1px solid rgba(223, 231, 224, 0.16); border-radius: 20px; padding: 1.8rem; backdrop-filter: blur(24px); box-shadow: 0 30px 60px rgba(0,0,0,0.6);">
        <h3 style="font-size:1.15rem; font-weight:600; margin:0 0 0.8rem; color:#dfe7e0;">Upload PDF Paper</h3>
        <div class="drop-zone" id="drop-zone" style="border: 1.5px dashed rgba(223, 231, 224, 0.25); border-radius: 14px; padding: 1.6rem; text-align: center; background: rgba(5,7,10,0.5); cursor: pointer; transition: border-color 0.2s;">
          <input id="pdf" type="file" accept="application/pdf,.pdf" style="width:100%; margin-bottom:8px; font-size:13px; color:#aab4ad;">
          <p style="margin:0 0 4px; font-size:15px; font-weight:600; color:#dfe7e0;">Drag & drop your demo paper here</p>
          <p style="margin:0; font-size:12px; color:#78837c;">Max 32 MiB · Automatic table & figure extraction</p>
          <p id="file-name" style="margin-top:10px; font-size:13px; color:#c9a24a; font-weight:600;">No file selected</p>
        </div>

        <details style="margin-top:14px; border-top:1px dashed rgba(223,231,224,0.12); padding-top:10px;">
          <summary style="cursor:pointer; font-size:13px; color:#e0231c;">Optional Metadata</summary>
          <input id="paper-id" type="text" placeholder="Custom Paper ID (e.g. demo_paper_01)" style="width:100%; background:rgba(5,7,10,0.6); border:1px solid rgba(223,231,224,0.18); border-radius:8px; color:#dfe7e0; padding:8px 10px; font-family:inherit; margin-top:8px; outline:none;">
          <input id="paper-title" type="text" placeholder="Paper Title" style="width:100%; background:rgba(5,7,10,0.6); border:1px solid rgba(223,231,224,0.18); border-radius:8px; color:#dfe7e0; padding:8px 10px; font-family:inherit; margin-top:8px; outline:none;">
        </details>

        <div style="display:flex; align-items:center; gap:12px; margin-top:1.4rem;">
          <button id="upload-btn" type="button" style="background:#e0231c; color:#fff; border:none; padding:10px 24px; border-radius:999px; font-weight:600; font-size:13px; cursor:pointer; box-shadow:0 0 20px rgba(224,35,28,0.4);">Upload & Index Paper</button>
          <span id="upload-spinner" class="spinner hidden" style="width:16px; height:16px; border:2px solid rgba(224,35,28,0.3); border-top-color:#e0231c; border-radius:50%; animation:spin 0.7s linear infinite;"></span>
        </div>
        <progress id="upload-progress" class="hidden" max="100" value="0" style="width:100%; height:6px; margin-top:12px; border-radius:999px;"></progress>
        <div id="upload-result" style="margin-top:12px; font-size:13px;"></div>
      </div>

      <!-- arXiv Discovery Card -->
      <div class="rl-glass-card" style="background: rgba(10, 14, 18, 0.78); border: 1px solid rgba(223, 231, 224, 0.16); border-radius: 20px; padding: 1.8rem; backdrop-filter: blur(24px); margin-top:1.4rem; box-shadow: 0 30px 60px rgba(0,0,0,0.6);">
        <h3 style="font-size:1.15rem; font-weight:600; margin:0 0 0.4rem; color:#dfe7e0;">Or Import from arXiv</h3>
        <p style="font-size:13px; color:#aab4ad; margin-bottom:12px;">Search open scientific literature and ingest with a single click.</p>
        <div style="display:flex; gap:10px;">
          <input id="arxiv-query" type="search" placeholder="e.g. multimodal retrieval with figures" style="flex:1; background:rgba(5,7,10,0.6); border:1px solid rgba(223,231,224,0.18); border-radius:8px; color:#dfe7e0; padding:10px 12px; font-family:inherit; outline:none;">
          <button id="arxiv-btn" type="button" style="background:rgba(223,231,224,0.1); color:#dfe7e0; border:1px solid rgba(223,231,224,0.2); padding:10px 18px; border-radius:999px; font-weight:600; font-size:13px; cursor:pointer;">Search</button>
        </div>
        <span id="arxiv-spinner" class="spinner hidden" style="width:15px; height:15px; border:2px solid rgba(224,35,28,0.3); border-top-color:#e0231c; border-radius:50%; animation:spin 0.7s linear infinite; margin-top:8px;"></span>
        <div id="arxiv-status" style="margin-top:10px; font-size:13px; color:#aab4ad;"></div>
        <div id="arxiv-results" style="margin-top:1rem;"></div>
      </div>
    </div>
  </div>

  <div style="margin-top:3rem;">
    <h3 style="font-size:1.15rem; font-weight:600; margin:0 0 0.8rem; color:#dfe7e0;">Papers Ingested In This Session</h3>
    <p id="paper-grid-empty" style="font-size:14px; color:#78837c;">No papers indexed yet in this browser session. Upload a PDF or search arXiv above.</p>
    <div id="paper-grid" class="masonry hidden" style="margin-top:1.2rem;"></div>
  </div>
</section>
`;

// =========================================================================
// 3RD PAGE (Chapter 2, data-cam="2"): ASK QUESTIONS ABOUT PAPER
// =========================================================================
const page3AskQuestion = `
<!-- ============================================================ 3RD PAGE: ASK ABOUT PAPER -->
<section class="sec" id="ask-lens" data-cam="2" style="min-height:auto; padding-top: clamp(60px, 8vh, 120px);">
  <div class="sec-head" data-rv="fade">
    <span class="k"><b>02</b> — Reasoning Interface</span><span class="rule"></span><span class="k jp">推論</span>
  </div>

  <div class="custom-step-grid">
    <div class="step-text-col">
      <h2 class="display h-sec" data-rv="up" style="max-width:none; font-size:clamp(2rem, 3.2vw, 3.2rem); line-height:1.15; margin:0 0 1rem;">
        Ask about your research papers.
      </h2>
      <p class="body-lg" data-rv="up" style="color:#aab4ad; line-height:1.6; margin-bottom:1.5rem;">
        Questions are evaluated exclusively from retrieved multimodal evidence. Specialized agents analyze queries, inspect charts & visual figures using Qwen2.5-VL, verify tabular data, and judge each claim before returning an answer.
      </p>

      <div class="gate-stats" data-rv="up">
        <div><b>VLM</b><span>Qwen2.5-VL</span></div>
        <div><b>100%</b><span>Verified</span></div>
        <div><b>Zero</b><span>Hallucination</span></div>
        <div><b>∞</b><span>Clarity</span></div>
      </div>
    </div>

    <div class="step-card-col">
      <div class="rl-glass-card" style="background: rgba(10, 14, 18, 0.78); border: 1px solid rgba(223, 231, 224, 0.16); border-radius: 20px; padding: 2rem; backdrop-filter: blur(24px); box-shadow: 0 30px 60px rgba(0,0,0,0.6);">
        <label for="query" style="display:block; font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:0.1em; color:#dfe7e0; margin-bottom:8px;">Research Query</label>
        <textarea id="query" placeholder="Ask about a methodology, figure, experimental finding, or table..." style="width:100%; min-height:130px; background:rgba(5,7,10,0.6); border:1px solid rgba(223,231,224,0.18); border-radius:12px; color:#dfe7e0; padding:12px 14px; font-family:inherit; font-size:15px; resize:vertical; outline:none; transition:border-color 0.2s;" onfocus="this.style.borderColor='#e0231c'" onblur="this.style.borderColor='rgba(223,231,224,0.18)'"></textarea>

        <div style="display:grid; grid-template-columns: 120px 1fr; gap:12px; margin-top:14px;">
          <div>
            <label for="topk" style="display:block; font-size:11px; text-transform:uppercase; color:#78837c; margin-bottom:4px;">Top K</label>
            <input id="topk" type="number" value="8" min="1" max="50" style="width:100%; background:rgba(5,7,10,0.6); border:1px solid rgba(223,231,224,0.18); border-radius:8px; color:#dfe7e0; padding:8px 10px; font-family:inherit; outline:none;">
          </div>
          <div>
            <label for="scope" style="display:block; font-size:11px; text-transform:uppercase; color:#78837c; margin-bottom:4px;">Scope Paper ID <span style="color:#78837c;">(Optional)</span></label>
            <input id="scope" type="text" placeholder="e.g. 1611.04684v1" style="width:100%; background:rgba(5,7,10,0.6); border:1px solid rgba(223,231,224,0.18); border-radius:8px; color:#dfe7e0; padding:8px 10px; font-family:inherit; outline:none;">
          </div>
        </div>

        <div style="display:flex; align-items:center; gap:12px; margin-top:1.6rem; flex-wrap:wrap;">
          <button id="ask-btn" type="button" style="background:#e0231c; color:#fff; border:none; padding:11px 26px; border-radius:999px; font-weight:600; font-size:14px; cursor:pointer; box-shadow:0 0 20px rgba(224,35,28,0.4); transition:transform 0.15s, background 0.15s;" onmouseover="this.style.background='#ff5a3c'" onmouseout="this.style.background='#e0231c'">Ask ResearchLens</button>
          <button id="ask-fill-btn" type="button" style="background:rgba(223,231,224,0.08); color:#dfe7e0; border:1px solid rgba(223,231,224,0.16); padding:9px 18px; border-radius:999px; font-size:13px; cursor:pointer;">Use Figure 1 Example</button>
          <span id="ask-spinner" class="spinner hidden" style="width:16px; height:16px; border:2px solid rgba(224,35,28,0.3); border-top-color:#e0231c; border-radius:50%; animation:spin 0.7s linear infinite;" aria-hidden="true"></span>
        </div>
        <div id="ask-status" style="margin-top:14px; font-size:13px; color:#aab4ad; min-height:1.2rem;"></div>
      </div>
    </div>
  </div>
</section>
`;

// Replace Chapter 1 and Chapter 2 sections in exact order
// In original kage.html, the first sec is id="gate", second is id="pathways"
// In current index.html, we replace the first two sections after hero
const sec1Regex = /<section class="sec" id="(?:gate|ask-lens|papers-lens)" data-cam="1"[\s\S]*?<\/section>/;
const sec2Regex = /<section class="sec" id="(?:pathways|papers-lens|ask-lens)" data-cam="2"[\s\S]*?<\/section>/;

if (sec1Regex.test(kage)) {
  kage = kage.replace(sec1Regex, page2UploadPaper);
}
if (sec2Regex.test(kage)) {
  kage = kage.replace(sec2Regex, page3AskQuestion);
}

// Ensure asset URLs are absolute
kage = kage.replace(/secret-pathways-assets\/fonts\.css/g, '/landing-pages/secret-pathways-assets/fonts.css');
kage = kage.replace(/secret-pathways-assets\/three\.min\.js/g, '/landing-pages/secret-pathways-assets/three.min.js');

// Write out to index.html and public/landing-pages/kage.html
fs.writeFileSync('app/static/index.html', kage, 'utf8');
fs.writeFileSync('app/static/landing-pages/kage.html', kage, 'utf8');
fs.writeFileSync('public/landing-pages/kage.html', kage, 'utf8');

console.log('Successfully re-ordered: 2nd page = Add Paper, 3rd page = Ask About Paper!');

