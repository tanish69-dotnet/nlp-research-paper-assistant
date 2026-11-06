const fs = require('fs');
const path = require('path');

const target = path.join(__dirname, 'app', 'static', 'index.html');
const backup = path.join(__dirname, 'app', 'static', 'index.backup.html');

let html = fs.readFileSync(backup, 'utf8');

// Modern Google Fonts
const headInject = `
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;1,400&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
`;
html = html.replace('</head>', headInject + '\n</head>');

// Ambient background and floating interactive elements
const ambientHtml = `
<div class="ambient-canvas-wrapper" aria-hidden="true">
  <div class="ambient-orb orb-1"></div>
  <div class="ambient-orb orb-2"></div>
  <div class="ambient-orb orb-3"></div>
  <div class="ambient-orb orb-4"></div>
  <div class="ambient-grid-overlay"></div>
</div>
`;
html = html.replace('<body>', '<body>\n' + ambientHtml);

// Save updated html
fs.writeFileSync(target, html, 'utf8');
console.log('Fonts & Ambient HTML injected');

