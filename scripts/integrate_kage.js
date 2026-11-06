const fs = require('fs');
const path = require('path');

const targetPath = path.join(__dirname, '..', 'app', 'static', 'index.html');
let html = fs.readFileSync(targetPath, 'utf8');

// 1. Add Kage Landing Page to floating navigation
const kageNavButton = '<a class="nav-bubble-link" href="#section-kage" data-nav><span class="nav-bubble-dot"></span>Kage 3D Temple</a>';
if (!html.includes('Kage 3D Temple')) {
  html = html.replace('<a class="nav-bubble-link" href="#section-evidence" data-nav>', kageNavButton + '\n      <a class="nav-bubble-link" href="#section-evidence" data-nav>');
}

// 2. Add Kage Section with full shader frame
const kageSection = `
      <!-- ============ KAGE THREEUI LANDING PAGE EXPERIENCE ============ -->
      <section class="section" id="section-kage" aria-labelledby="kage-title">
        <div class="section-head">
          <div>
            <div class="section-kicker">ThreeUI 3D World · WebGL</div>
            <h2 id="kage-title">Kage — Mountain Temple Night Walk</h2>
            <p class="section-sub">The complete authored Kage temple experience from ThreeUI. Procedural charred cypress, interactive lantern light, vermilion celestial shaders, and layered Japanese stone garden cutouts.</p>
          </div>
          <div class="btn-row" style="margin:0">
            <a class="btn btn-primary" href="/landing-pages/kage.html" target="_blank" rel="noopener noreferrer">
              Open Fullpage Experience ↗
            </a>
          </div>
        </div>

        <div class="shader-frame" style="position:relative; width:100%; height:750px; border-radius:24px; overflow:hidden; border:1px solid rgba(224, 35, 28, 0.3); box-shadow:0 25px 60px -10px rgba(0,0,0,0.8), 0 0 35px rgba(224,35,28,0.2); background:#05070a;">
          <iframe 
            src="/landing-pages/kage.html" 
            title="Kage — Where stillness reveals the unseen"
            style="width:100%; height:100%; border:none; display:block;"
            sandbox="allow-downloads allow-forms allow-modals allow-popups allow-same-origin allow-scripts"
            loading="eager"
            id="kage-frame"
          ></iframe>
        </div>
      </section>
`;

if (!html.includes('id="section-kage"')) {
  html = html.replace('<!-- ============ FIGURES & TABLES ============ -->', kageSection + '\n\n      <!-- ============ FIGURES & TABLES ============ -->');
}

fs.writeFileSync(targetPath, html, 'utf8');
console.log('Successfully integrated KageLandingPage into app/static/index.html');

