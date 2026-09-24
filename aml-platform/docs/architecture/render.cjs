/* SVG is the editable master. PNGs are 3600 px wide presentation exports.
 * Dependency: @resvg/resvg-js 2.6.2; no browser or remote assets required.
 * Run: node render.cjs
 */
const fs = require('node:fs');
const path = require('node:path');
const { Resvg } = require('@resvg/resvg-js');
const stems = ['01-evaluation-pipeline', '02-azure-execution', '03-ci-release'];
for (const stem of stems) {
  const source = fs.readFileSync(path.join(__dirname, `${stem}.svg`));
  const png = new Resvg(source, {
    fitTo: { mode: 'width', value: 3600 },
    font: { loadSystemFonts: true, defaultFontFamily: 'Arial' },
  }).render().asPng();
  fs.writeFileSync(path.join(__dirname, `${stem}.png`), png);
  console.log(`${stem}.png`);
}
