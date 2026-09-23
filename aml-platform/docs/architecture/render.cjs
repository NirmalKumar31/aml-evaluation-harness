// Render offline after installing @resvg/resvg-js outside the project.
// NODE_PATH=/path/to/node_modules node render.cjs
const fs = require('node:fs');
const path = require('node:path');
const { Resvg } = require('@resvg/resvg-js');
for (const name of ['01-evaluation-pipeline', '02-azure-execution', '03-ci-release']) {
  const input = fs.readFileSync(path.join(__dirname, `${name}.svg`));
  const renderer = new Resvg(input, {
    fitTo: { mode: 'width', value: 3600 },
    font: { loadSystemFonts: true, defaultFontFamily: 'Arial' },
  });
  fs.writeFileSync(path.join(__dirname, `${name}.png`), renderer.render().asPng());
  console.log(`${name}.png`);
}
