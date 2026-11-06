const fs = require('fs');

const html = fs.readFileSync('app/static/index.html', 'utf8');
const lines = html.split('\n');

lines.forEach((line, index) => {
  if (line.includes('<section') || line.includes('data-cam')) {
    console.log(index + ': ' + line.trim().slice(0, 100));
  }
});

