const fs = require('fs');

// Read the canonical kage.html template
let kage = fs.readFileSync('public/landing-pages/kage.html', 'utf8');

// Read original ResearchLens script logic
const researchLensLogic = fs.readFileSync('scripts/researchlens_logic.js', 'utf8');

// 1. Update Title and Metadata
kage = kage.replace(
  '<title>Kage — Where stillness reveals the unseen</title>',
  '<title>ResearchLens — Multimodal Evidence Intelligence</title>'
);

// 2. Update Preloader
kage = kage.replace('影の道', 'RESEARCHLENS');
kage = kage.replace('Raising the mountain temple', 'Initialising Multimodal Evidence Engine');

// 3. Update Brand in Nav
kage = kage.replace(
  '<span class="brand-tx"><b>KAGE</b><i>HIDDEN REALMS OF KYOTO</i></span>',
  '<span class="brand-tx"><b>RESEARCHLENS</b><i>MULTIMODAL EVIDENCE AGENTS</i></span>'
);

// Update Nav Links to follow natural workflow: Papers -> Ask -> Evidence -> History
const newNavLinks = `
  <nav class="nav-links" id="navlinks">
    <a class="nav-link" href="#papers-lens" data-cursor><span>01 Add Papers</span><span class="alt">書庫</span></a>
    <a class="nav-link" href="#ask-lens" data-cursor><span>02 Ask Agent</span><span class="alt">推論</span></a>
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

// Update Hero Chips to reflect the correct step-by-step workflow
kage = kage.replace(
  `<div class="chip" data-chip="0" data-rv="up" data-cursor><span class="num">01</span>
        <span class="tx"><b>Thresholds</b><p>Discover the hidden gates that open on to deeper paths.</p></span></div>
      <div class="chip" data-chip="1" data-rv="up" data-cursor><span class="num">02</span>
        <span class="tx"><b>Still Gardens</b><p>Witness the courts where silence gently unfolds.</p></span></div>
      <div class="chip" data-chip="2" data-rv="up" data-cursor><span class="num">03</span>
        <span class="tx"><b>Sacred Craft</b><p>Embrace the hands and heritage that shape devotion.</p></span></div>
      <div class="chip" data-chip="3" data-rv="up" data-cursor><span class="num">04</span>
        <span class="tx"><b>Night Rituals</b><p>Explore the rites that awaken when the day is done.</p></span></div>`,
  `<div class="chip" data-chip="0" data-rv="up" data-cursor onclick="document.getElementById('papers-lens').scrollIntoView({behavior:'smooth'})"><span class="num">01</span>
        <span class="tx"><b>Add Papers</b><p>Upload demo PDF or discover research papers on arXiv.</p></span></div>
      <div class="chip" data-chip="1" data-rv="up" data-cursor onclick="document.getElementById('ask-lens').scrollIntoView({behavior:'smooth'})"><span class="num">02</span>
        <span class="tx"><b>Ask Questions</b><p>Query over figures, equations, diagrams, and tables.</p></span></div>
      <div class="chip" data-chip="2" data-rv="up" data-cursor onclick="document.getElementById('evidence-lens').scrollIntoView({behavior:'smooth'})"><span class="num">03</span>
        <span class="tx"><b>Visual Evidence</b><p>Inspect extracted charts, figures, and data models.</p></span></div>
      <div class="chip" data-chip="3" data-rv="up" data-cursor onclick="document.getElementById('history-lens').scrollIntoView({behavior:'smooth'})"><span class="num">04</span>
        <span class="tx"><b>Answer Audit</b><p>Review verified claims, citations, and model reasoning.</p></span></div>`
);

// 5. FIRST SECTION (Chapter 01, data-cam="1"): STEP 1 — ADD & INDEX PAPERS
const step1PapersSection = `
<section class="sec" id="papers-lens" data-cam="1" style="min-height:auto; padding-top: clamp(60px, 8vh, 120px);">
  <div class="sec-head" data-rv="fade">
    <span class="k"><b>Step 01</b> — Paper Corpus</span><span class="rule"></span><span class="k jp">書庫</span>
  </div>
  
  <div class="custom-step-grid">
    <div class="step-text-col">
      <h2 class="display h-sec" data-rv="up" style="max-width:none; font-size:clamp(2rem, 3.2vw, 3.2rem); line-height:1.15; margin:0 0 1rem;">
        First, add your research paper.
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
kage = kage.replace(/<section class="sec" id="gate" data-cam="1">[\s\S]*?<\/section>/, step1PapersSection);

// 6. SECOND SECTION (Chapter 02, data-cam="2"): STEP 2 — ASK RESEARCHLENS AGENTS
const step2AskSection = `
<section class="sec" id="ask-lens" data-cam="2" style="min-height:auto; padding-top: clamp(60px, 8vh, 120px);">
  <div class="sec-head" data-rv="fade">
    <span class="k"><b>Step 02</b> — Reasoning Interface</span><span class="rule"></span><span class="k jp">推論</span>
  </div>

  <div class="custom-step-grid">
    <div class="step-text-col">
      <h2 class="display h-sec" data-rv="up" style="max-width:none; font-size:clamp(2rem, 3.2vw, 3.2rem); line-height:1.15; margin:0 0 1rem;">
        Ask about your research papers.
      </h2>
      <p class="body-lg" data-rv="up" style="color:#aab4ad; line-height:1.6; margin-bottom:1.5rem;">
        Once your paper is indexed, query across any domain. Specialized agents analyze queries, inspect charts & visual figures using Qwen2.5-VL, verify tabular data, and judge each claim before returning an answer.
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
kage = kage.replace(/<section class="sec" id="pathways" data-cam="2">[\s\S]*?<\/section>/, step2AskSection);

// 7. THIRD SECTION (Chapter 03, data-cam="3"): STEP 3 — VISUAL EVIDENCE
const step3EvidenceSection = `
<section class="sec" id="evidence-lens" data-cam="3" style="padding-top: clamp(60px, 8vh, 120px);">
  <div class="sec-head" data-rv="fade">
    <span class="k"><b>Step 03</b> — Multimodal Evidence</span><span class="rule"></span><span class="k jp">証拠</span>
  </div>
  <div class="cur-head">
    <h2 class="display h-sec" data-rv="up" style="max-width:none;">Extracted Figures & Structured Tables</h2>
    <p class="body-lg" data-rv="up" style="color:#aab4ad;">Explore real visual assets extracted from your indexed research papers.</p>
  </div>

  <div class="rl-glass-card" style="background: rgba(10, 14, 18, 0.78); border: 1px solid rgba(223, 231, 224, 0.16); border-radius: 20px; padding: 2rem; backdrop-filter: blur(24px); margin-top:2rem;">
    <div style="display:flex; gap:12px; flex-wrap:wrap;">
      <input id="evidence-query" type="search" placeholder="Find figures or tables about... (e.g. architecture diagram, benchmark accuracy)" style="flex:1 1 300px; background:rgba(5,7,10,0.6); border:1px solid rgba(223,231,224,0.18); border-radius:8px; color:#dfe7e0; padding:10px 14px; font-family:inherit; outline:none;">
      <button id="evidence-btn" type="button" style="background:#e0231c; color:#fff; border:none; padding:10px 24px; border-radius:999px; font-weight:600; font-size:13px; cursor:pointer;">Search Evidence</button>
      <button id="evidence-session-btn" type="button" style="background:rgba(223,231,224,0.08); color:#dfe7e0; border:1px solid rgba(223,231,224,0.18); padding:10px 20px; border-radius:999px; font-size:13px; cursor:pointer;">Show Answer Evidence</button>
    </div>
    <div style="display:flex; align-items:center; gap:12px; margin-top:14px;">
      <input id="evidence-scope" type="text" placeholder="Scope to Paper ID (optional)" style="max-width:280px; background:rgba(5,7,10,0.6); border:1px solid rgba(223,231,224,0.18); border-radius:8px; color:#dfe7e0; padding:8px 12px; font-size:13px; outline:none;">
      <span id="evidence-loader" class="loader-dots hidden"><i></i><i></i><i></i></span>
      <div id="evidence-status" style="font-size:13px; color:#aab4ad;"></div>
    </div>
  </div>

  <p id="evidence-empty" style="margin-top:2rem; font-size:14px; color:#78837c;">Search the evidence corpus above or ask a question to automatically surface cited tables and figures.</p>
  <div id="evidence-grid" class="masonry hidden" style="margin-top:1.5rem;"></div>
</section>
`;
kage = kage.replace(/<section class="sec" id="lessons" data-cam="3">[\s\S]*?<\/section>/, step3EvidenceSection);

// 8. FOURTH SECTION (Chapter 04, data-cam="4"): STEP 4 — QUESTION HISTORY & AUDIT
const step4HistorySection = `
<section class="sec fin" id="history-lens" data-cam="4" style="padding-top: clamp(60px, 8vh, 120px);">
  <div class="sec-head" data-rv="fade">
    <span class="k"><b>Step 04</b> — Audit & Provenance</span><span class="rule"></span><span class="k jp">履歴</span>
  </div>
  <div style="display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap; gap:1rem;">
    <div>
      <h2 class="display" data-rv="up" style="max-width:none;">Question History & Audit Trail</h2>
      <p class="body-lg" data-rv="up" style="color:#aab4ad;">Every response retains its agent traces, verification status, and claim-level citations.</p>
    </div>
    <div style="display:flex; gap:10px;">
      <a id="latest-answer" class="hidden" href="#answer-result" style="background:rgba(223,231,224,0.1); color:#dfe7e0; border:1px solid rgba(223,231,224,0.2); padding:6px 14px; border-radius:999px; font-size:13px;">Jump to latest</a>
      <button id="clear-history-btn" type="button" style="background:none; border:1px solid rgba(223,231,224,0.2); color:#aab4ad; padding:6px 14px; border-radius:999px; font-size:13px; cursor:pointer;">Clear history</button>
    </div>
  </div>

  <div id="answer-result" style="margin-top:2rem; display:flex; flex-direction:column; gap:20px;">
    <p id="history-empty" style="font-size:14px; color:#78837c;">No questions evaluated yet. Run a query in Step 02 above.</p>
  </div>
</section>
`;
kage = kage.replace(/<section class="sec fin" id="eternity" data-cam="4">[\s\S]*?<\/section>/, step4HistorySection);

// 9. Update Footer
const footerContent = `
  <div class="foot-grid">
    <div class="foot-brand">
      <svg viewBox="0 0 44 44" fill="none" width="34" height="34" aria-hidden="true">
        <circle cx="22" cy="25" r="8.6" fill="#e0231c" fill-opacity=".9"/>
        <path d="M5 13h34M9 18.4h26M22 8.5v27" stroke="#dfe7e0" stroke-width="1.5"/>
      </svg>
      <p>ResearchLens Multimodal Reasoning Engine. Real-time document evidence extraction, VLM visual reasoning, and verifiable citations.</p>
    </div>
    <div><h4>Endpoints</h4><ul>
      <li><a href="http://127.0.0.1:8001/api/v1/health" target="_blank">Reasoning :8001</a></li>
      <li><a href="http://127.0.0.1:8000/health" target="_blank">Retrieval :8000</a></li>
      <li><a href="http://127.0.0.1:11434" target="_blank">Ollama :11434</a></li>
    </ul></div>
    <div><h4>Workflow</h4><ul>
      <li><a href="#papers-lens">01 Add Papers</a></li>
      <li><a href="#ask-lens">02 Ask Agent</a></li>
      <li><a href="#evidence-lens">03 Evidence</a></li>
      <li><a href="#history-lens">04 History</a></li>
    </ul></div>
    <div><h4>Diagnostics</h4>
      <input id="p2base" type="hidden" value="http://127.0.0.1:8000">
      <input id="nlpbase" type="hidden" value="http://127.0.0.1:8001">
      <button id="check-btn" type="button" style="background:rgba(223,231,224,0.08); border:1px solid rgba(223,231,224,0.2); color:#dfe7e0; padding:6px 12px; border-radius:999px; font-size:12px; cursor:pointer; margin-top:8px;">Check Services</button>
      <div id="status-line" style="font-size:12px; color:#78837c; margin-top:6px;"></div>
    </div>
  </div>
  <div class="foot-base">
    <span>© 2026 ResearchLens — Powered by ThreeUI Kage WebGL World</span>
    <span class="jp">真実と証拠の調和</span>
    <span>Local Qwen2.5-VL & Ollama</span>
  </div>
`;
kage = kage.replace(/<div class="foot-grid">[\s\S]*?<div class="foot-base">[\s\S]*?<\/div>/, footerContent);

// 10. Robust CSS fixes for layout, typography, wrapping, and badges
const extraStyles = `
<style>
  /* Fix two-column split layout for the steps */
  .custom-step-grid {
    display: grid !important;
    grid-template-columns: minmax(320px, 1fr) minmax(340px, 1.25fr) !important;
    gap: clamp(24px, 4vw, 64px) !important;
    align-items: start !important;
    width: 100% !important;
  }
  .step-text-col {
    min-width: 0 !important;
  }
  .step-card-col {
    min-width: 0 !important;
  }
  @media (max-width: 900px) {
    .custom-step-grid {
      grid-template-columns: 1fr !important;
      gap: 24px !important;
    }
  }

  /* Override harsh clipping on display headers */
  .display {
    max-width: none !important;
    word-break: normal !important;
  }

  .badge { display:inline-block; padding:3px 10px; border-radius:999px; font-size:11px; font-weight:700; margin:0 4px 4px 0; }
  .badge.ok { background:rgba(16,185,129,0.18); color:#34d399; border:1px solid rgba(16,185,129,0.3); }
  .badge.warn { background:rgba(245,158,11,0.18); color:#fbbf24; border:1px solid rgba(245,158,11,0.3); }
  .badge.err { background:rgba(239,68,68,0.18); color:#f87171; border:1px solid rgba(239,68,68,0.3); }
  .badge.neutral { background:rgba(223,231,224,0.08); color:#dfe7e0; border:1px solid rgba(223,231,224,0.15); }
  .pill { display:inline-block; padding:3px 8px; border-radius:999px; font-size:11px; margin:0 4px 4px 0; background:rgba(223,231,224,0.08); color:#aab4ad; border:1px solid rgba(223,231,224,0.12); }
  .pill.sage { background:rgba(16,185,129,0.15); color:#6ee7b7; border-color:rgba(16,185,129,0.25); }
  .pill.peach { background:rgba(224,35,28,0.15); color:#ff8a7a; border-color:rgba(224,35,28,0.25); }
  
  .history-entry { background:rgba(10,14,18,0.85); border:1px solid rgba(223,231,224,0.16); border-radius:18px; padding:1.5rem; backdrop-filter:blur(20px); }
  .history-entry.latest { border-color:rgba(224,35,28,0.4); box-shadow:0 0 30px rgba(224,35,28,0.2); }
  .card-error { border-left:4px solid #e0231c; }
  .error-detail { white-space:pre-wrap; color:#ff8a7a; font-family:monospace; font-size:13px; background:rgba(224,35,28,0.1); padding:10px; border-radius:8px; }
  
  .masonry { column-count:3; column-gap:1.2rem; }
  .masonry > * { break-inside:avoid; display:block; margin-bottom:1.2rem; }
  @media(max-width:1100px){ .masonry { column-count:2; } }
  @media(max-width:700px){ .masonry { column-count:1; } }

  .paper-card, .media-card { background:rgba(10,14,18,0.8); border:1px solid rgba(223,231,224,0.14); border-radius:16px; padding:1.2rem; backdrop-filter:blur(16px); transition:transform 0.2s, border-color 0.2s; }
  .paper-card:hover, .media-card:hover { transform:translateY(-3px); border-color:rgba(224,35,28,0.4); }
  .paper-title { font-size:1.05rem; font-weight:600; color:#dfe7e0; margin:0 0 6px; }
  .paper-meta { font-size:12px; color:#78837c; margin-bottom:6px; }
  .paper-abstract { font-size:13px; color:#aab4ad; line-height:1.5; }
  .media-figure { width:100%; border-radius:10px; border:1px solid rgba(223,231,224,0.1); background:#05070a; }
  .media-caption { font-size:13px; color:#aab4ad; margin-top:8px; }
  .media-caption-clamp { display:-webkit-box; -webkit-line-clamp:4; -webkit-box-orient:vertical; overflow:hidden; }
  .caption-toggle { font-size:11px; color:#e0231c; background:none; border:1px solid rgba(223,231,224,0.15); border-radius:999px; padding:2px 8px; cursor:pointer; }

  table { width:100%; border-collapse:collapse; font-size:13px; margin-top:6px; }
  th, td { border-bottom:1px solid rgba(223,231,224,0.1); padding:6px 8px; text-align:left; }
  th { color:#78837c; font-weight:600; text-transform:uppercase; font-size:11px; }
  .table-scroll { overflow-x:auto; border:1px solid rgba(223,231,224,0.12); border-radius:8px; }

  .hidden { display:none !important; }
  .btn-small { padding:4px 10px; font-size:12px; border-radius:999px; }
  .btn-ghost { background:rgba(223,231,224,0.08); border:1px solid rgba(223,231,224,0.16); color:#dfe7e0; cursor:pointer; }
  .btn-primary { background:#e0231c; color:#fff; border:none; cursor:pointer; }
  .btn-quiet { background:none; border:none; color:#78837c; cursor:pointer; }
  .btn-row { display:flex; gap:8px; align-items:center; margin-top:8px; }

  .service-pill.is-ok .dot { background:#10b981 !important; box-shadow:0 0 8px #10b981; }
  .service-pill.is-bad .dot { background:#ef4444 !important; box-shadow:0 0 8px #ef4444; }
  .service-pill.is-checking .dot { background:#c9a24a !important; animation:pulse 1s infinite alternate; }
  @keyframes pulse { from { opacity:0.4; } to { opacity:1; } }
  @keyframes spin { to { transform:rotate(360deg); } }

  .loader-dots { display:inline-flex; align-items:center; gap:4px; }
  .loader-dots i { width:5px; height:5px; border-radius:50%; background:#e0231c; opacity:0.3; animation:dotsBounce 0.9s infinite alternate; }
  .loader-dots i:nth-child(2) { animation-delay:0.2s; }
  .loader-dots i:nth-child(3) { animation-delay:0.4s; }
  @keyframes dotsBounce { to { opacity:1; transform:scale(1.3); } }
</style>
`;
kage = kage.replace('</head>', extraStyles + '\n</head>');

// 11. Append ResearchLens Interactive Logic to scripts
kage = kage.replace('</body>', `<script>\n${researchLensLogic}\n</script>\n</body>`);

// Fix asset paths
kage = kage.replace(/secret-pathways-assets\/fonts\.css/g, '/landing-pages/secret-pathways-assets/fonts.css');
kage = kage.replace(/secret-pathways-assets\/three\.min\.js/g, '/landing-pages/secret-pathways-assets/three.min.js');

// Save files
fs.writeFileSync('app/static/index.html', kage, 'utf8');
fs.writeFileSync('app/static/landing-pages/kage.html', kage, 'utf8');
fs.writeFileSync('public/landing-pages/kage.html', kage, 'utf8');

console.log('Successfully re-ordered workflow and fixed layout!');
