const fs = require('fs');

const html = fs.readFileSync('public/landing-pages/kage.html', 'utf8');
const lines = html.split('\n');
console.log('Total lines:', lines.length);

lines.forEach((line, index) => {
  if (line.includes('<body') || line.includes('</style>') || line.includes('id="gl"') || line.includes('<nav')) {
    console.log(index + ': ' + line.trim().slice(0, 100));
  }
});

