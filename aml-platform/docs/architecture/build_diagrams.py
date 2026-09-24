"""Render three source-grounded architecture diagrams; Python standard library only.

The SVGs embed the attributed icons in icons/. Run this file offline to rebuild.
Evidence baseline: NirmalKumar31/aml-evaluation-harness at 64784288dda38bd104c6cd534d4e80b9ab48c818.
"""
from pathlib import Path
import html
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
INK = '#112B40'
MUTED = '#516779'
BLUE = '#2376A4'
TEAL = '#087F7C'
GOLD = '#946B24'
LINE = '#DCE5EA'


class Diagram:
    def __init__(self, number, title, subtitle, h=1240):
        self.h = h
        self.seq = 0
        self.p = [f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1800" height="{h}" viewBox="0 0 1800 {h}" role="img" aria-labelledby="title desc">
<title id="title">{html.escape(title)}</title><desc id="desc">{html.escape(subtitle)}. Detailed source mapping is provided in README.md.</desc>
<defs>''']
        for key, color in [('flow', BLUE), ('control', TEAL), ('release', GOLD)]:
            self.p.append(f'<marker id="{key}" viewBox="0 0 10 10" markerWidth="9" markerHeight="9" refX="8" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M1 1 L9 5 L1 9" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></marker>')
        self.p.append(f'''</defs><style>
text{{font-family:Arial,Helvetica,sans-serif;fill:{INK}}}
.eyebrow{{font-size:16px;font-weight:700;letter-spacing:2px;fill:{BLUE}}}
.title{{font-size:46px;font-weight:700;letter-spacing:-1px}}
.sub{{font-size:22px;fill:{MUTED}}}
.node{{font-size:24px;font-weight:700}}
.body{{font-size:20px;fill:{MUTED}}}
.small{{font-size:17px;fill:{MUTED}}}
.link{{font-size:17px;fill:{BLUE}}}
.note{{font-size:19px;fill:{MUTED}}}
</style><rect width="1800" height="{h}" fill="#FFF"/>''')
        self.text(70, 55, 'AML EVALUATION HARNESS', 'eyebrow')
        self.text(1730, 55, f'ARCHITECTURE  /  {number:02d}', 'eyebrow', anchor='end')
        self.text(70, 121, title, 'title')
        self.text(70, 162, subtitle, 'sub')
        self.path('M70 190 H1730', LINE, marker=False, width=1)

    def text(self, x, y, s, cls='body', anchor='start', color=None):
        extra = f' style="fill:{color}"' if color else ''
        self.p.append(f'<text x="{x}" y="{y}" class="{cls}" text-anchor="{anchor}"{extra}>{html.escape(str(s))}</text>')

    def lines(self, x, y, lines, cls='body', anchor='middle', step=28):
        for i, s in enumerate(lines):
            self.text(x, y+i*step, s, cls, anchor)

    def path(self, d, color=BLUE, dash=False, marker=True, width=2.1):
        marker_id = 'control' if color == TEAL else ('release' if color == GOLD else 'flow')
        extras = (' stroke-dasharray="5 7"' if dash else '') + (f' marker-end="url(#{marker_id})"' if marker else '')
        self.p.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"{extras}/>')

    def area(self, x, y, w, h, fill='#F5F9FC'):
        # Only broad execution / narrative lanes receive a background.
        self.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="28" fill="{fill}"/>')

    def icon(self, name, cx, cy, size=64):
        self.seq += 1
        root = ET.fromstring((ROOT/'icons'/f'{name}.svg').read_bytes())
        if 'viewBox' not in root.attrib:
            w = re.match(r'[\d.]+', root.get('width', '100')).group()
            h = re.match(r'[\d.]+', root.get('height', '100')).group()
            root.set('viewBox', f'0 0 {w} {h}')
        for k, v in {'x':cx-size/2, 'y':cy-size/2, 'width':size, 'height':size,
                     'preserveAspectRatio':'xMidYMid meet', 'aria-hidden':'true'}.items():
            root.set(k, str(v))
        ids = {e.attrib['id']:f'i{self.seq}_{e.attrib["id"]}' for e in root.iter() if 'id' in e.attrib}
        for e in root.iter():
            for key, value in list(e.attrib.items()):
                if key == 'id':
                    e.set(key, ids[value])
                else:
                    for old, new in ids.items():
                        value = value.replace(f'url(#{old})', f'url(#{new})')
                        if value == '#'+old:
                            value = '#'+new
                    e.set(key, value)
        self.p.append(ET.tostring(root, encoding='unicode'))

    def glyph(self, name, cx, cy, color=BLUE):
        # Neutral semantic symbols, not imitations of vendor logos.
        self.p.append(f'<g transform="translate({cx-32},{cy-32})" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">')
        shapes = {
            'split':'<path d="M9 32 H27 M27 32 C37 32 29 12 43 12 H55 M27 32 C37 32 29 52 43 52 H55 M49 6 L55 12 L49 18 M49 46 L55 52 L49 58"/><circle cx="9" cy="32" r="4" fill="white"/>',
            'chart':'<path d="M8 6 V55 H59 M17 43 H46 M17 30 H56 M17 17 H35"/><circle cx="46" cy="43" r="3" fill="white"/><circle cx="56" cy="30" r="3" fill="white"/><circle cx="35" cy="17" r="3" fill="white"/>',
            'files':'<path d="M18 5 H40 L52 17 V55 H18 Z M40 5 V17 H52 M10 13 V62 H44 M26 28 H43 M26 37 H43 M26 46 H38"/>',
            'web':'<rect x="4" y="8" width="56" height="45" rx="5"/><path d="M4 21 H60 M25 53 V60 M39 53 V60 M19 60 H45"/><circle cx="12" cy="15" r="1"/><circle cx="19" cy="15" r="1"/><path d="M14 41 L24 31 L33 39 L47 27"/>',
            'shield':'<path d="M32 3 L55 12 V30 Q54 48 32 61 Q10 48 9 30 V12 Z M20 31 L29 40 L45 22"/>',
            'tag':'<path d="M8 8 H34 L60 34 L34 60 L8 34 Z"/><circle cx="22" cy="22" r="5"/>',
            'operator':'<circle cx="32" cy="15" r="10"/><path d="M12 59 V44 Q12 30 32 30 Q52 30 52 44 V59 M22 59 V46 M42 59 V46"/>',
            'disk':'<ellipse cx="32" cy="12" rx="24" ry="9"/><path d="M8 12 V49 C8 61 56 61 56 49 V12 M8 30 C8 42 56 42 56 30"/>',
        }
        self.p.append(shapes[name]+'</g>')

    def node(self, x, y, icon, title, body, step=None, size=68):
        if icon.startswith('@'):
            self.glyph(icon[1:], x, y)
        else:
            self.icon(icon, x, y, size)
        if step:
            self.text(x, y-63, step, 'eyebrow', 'middle')
        self.text(x, y+67, title, 'node', 'middle')
        self.lines(x, y+101, body)

    def footer(self, note):
        self.path(f'M70 {self.h-78} H1730', LINE, marker=False, width=1)
        self.text(70, self.h-43, note, 'small')
        self.text(1730, self.h-43, 'SOURCE  6478428  ·  24 SEP 2026', 'small', 'end')

    def save(self, filename):
        raw = '\n'.join(self.p+['</svg>'])+'\n'
        ET.fromstring(raw)
        (ROOT/filename).write_text(raw)


def overview():
    d = Diagram(1, 'From synthetic transactions to published evidence',
                'The complete project flow • Batch evaluation, traceable results, tested software and an interactive website', 1290)
    d.area(45, 224, 1710, 650, '#F7FAFC')
    d.text(80, 250, '01—05  /  PREPARE THE EXPERIMENT', 'eyebrow')
    xs = [190, 545, 900, 1255, 1610]
    d.node(xs[0], 345, 'kaggle', 'IBM AMLworld', ['Synthetic transaction CSV', 'Pattern TXT → ring labels', 'HI: Small · Medium · Large'], '01  INPUT')
    d.node(xs[1], 345, 'python', 'Normalize + parse', ['Typed transactions + IDs', 'Rings and participants', 'Partitioned Parquet'], '02  INGEST')
    d.node(xs[2], 345, 'duckdb', 'Reconcile labels', ['Join patterns to transactions', 'Labeled Parquet + separate', 'ring-membership relations'], '03  JOIN')
    d.node(xs[3], 345, '@split', 'Define temporal split', ['Choose cut; exclude test rings', 'sharing training participants', 'Drop train-ring test tails'], '04  SPLIT')
    d.node(xs[4], 345, 'duckdb', 'Build 32 features', ['Transaction + account history', '1 / 7 / 30-day windows', 'History ends at t − 1 minute'], '05  FEATURES')
    for a,b,label in zip(xs, xs[1:], ['raw files','Parquet','labeled rows','full history']):
        d.path(f'M{a+58} 344 H{b-58}')
        d.text((a+b)/2, 330, label, 'link', 'middle')
    d.path('M1610 520 H1770 V617 Q1770 637 1750 637 H1718')
    d.text(1750, 564, 'fit', 'link', 'end')
    d.text(80, 540, '10—06  /  READ THE RESULTS  ←', 'eyebrow')
    d.node(xs[4], 637, 'sklearn', 'Fit + score per seed', ['Small / Medium: HistGBDT', 'Medium: LogisticRegression', 'Large: LightGBM · seeds 0, 1, 2'], '06  MODELS')
    d.icon('lightgbm', xs[4]+69, 637, 48)
    d.node(xs[3], 637, '@chart', 'Evaluate daily top-k', ['Both endpoints → account-day', 'Daily precision / recall', 'Nulls / ceilings where available'], '07  EVALUATE')
    d.node(xs[2], 637, '@files', 'Preserve the evidence', ['Metrics + stage manifests', 'Code, model and matrix hashes', 'Canonical / supporting registry'], '08  ARCHIVE')
    d.node(xs[1], 637, 'github', 'Verify + publish', ['Public aggregate artifacts', 'Reports + publication checks', 'Protected GitHub repository'], '09  VERIFY')
    d.node(xs[0], 637, '@web', 'Explore the findings', ['GitHub Pages · static site', 'Results + Engineering views', 'Generated, tested, then deployed'], '10  WEBSITE')
    for a,b,label in zip(xs[::-1], xs[-2::-1], ['scores','metrics','gate','site build']):
        d.path(f'M{a-65} 637 H{b+65}')
        d.text((a+b)/2, 621, label, 'link', 'middle')
    d.text(80, 838, 'Features retain past history; split filters select fitting rows. Model families were not measured at every dataset scale.', 'note')
    d.text(70, 925, 'TWO EXECUTION PATHS SUPPORT THIS FLOW', 'eyebrow')
    d.icon('azure-vm', 105, 990, 54)
    d.text(151, 981, 'Recorded HI-Large execution', 'node')
    d.lines(151, 1016, ['One Azure VM → local Docker build → DuckDB + LightGBM', 'ADLS source / JSON transfers; Kaggle inputs direct to VM'], anchor='start')
    d.text(151, 1090, 'Detailed topology → diagram 02', 'small')
    d.path('M880 950 V1110', LINE, marker=False, width=1)
    d.icon('actions', 950, 990, 54)
    d.text(995, 981, 'Current delivery', 'node')
    d.lines(995, 1016, ['GitHub Actions → tested Docker image → GHCR', 'Signed tags promote the same manifest; Pages ships separately'], anchor='start')
    d.text(995, 1090, 'Build, security, release and website paths → diagram 03', 'small')
    d.text(70, 1160, 'Interpretation: synthetic benchmark evidence • Seed, split and leakage diagnostics • Raw data and row-level replay stay private', 'note')
    d.footer('Research evaluation; no live bank deployment or inference service.')
    d.save('01-evaluation-pipeline.svg')


def cloud():
    d = Diagram(2, 'HI-Large: the recorded Azure execution',
                'One VM • Host-side Azure CLI transfers • Docker runs the batch pipeline on mounted local disks', 1370)
    d.area(420, 220, 1335, 866, '#F3F8FC')
    d.icon('azure', 464, 256, 33)
    d.text(493, 262, 'AZURE / EAST US', 'eyebrow')
    d.text(1720, 262, 'HISTORICAL TOPOLOGY', 'eyebrow', 'end', GOLD)

    d.node(185, 354, 'git', 'Application source', ['Source archive uploaded', 'from the repository', 'Azure CLI on the host'])
    d.node(665, 354, 'azure-storage', 'ADLS Gen2', ['src/ → application source', 'runs/ ← JSON outputs', 'Hierarchical namespace on'])
    d.node(1155, 354, 'docker', 'Build on the VM', ['Source unpacked on host', 'docker build → aml:<git-sha>', 'Image was not pulled from GHCR'])
    d.node(1585, 354, 'azure-vm', 'Azure VM', ['Standard_E4ds_v7', '4 vCPU · ≈31 GB available', 'Single-node batch execution'])
    d.path('M244 353 H607'); d.text(314, 331, 'source archive', 'link', 'middle')
    d.path('M723 353 H1097'); d.text(910, 331, 'download on host', 'link', 'middle')
    d.path('M1220 353 H1525'); d.text(1373, 331, 'local image', 'link', 'middle')

    d.text(457, 565, 'BATCH DATA PATH  /  ON THE VM, IN DOCKER', 'eyebrow')
    d.node(185, 653, 'kaggle', 'HI-Large input', ['179.7M transactions', 'CSV + pattern file', 'Direct HTTPS download'])
    d.node(665, 653, 'duckdb', 'DuckDB + Parquet', ['Normalize → labels → split', '32 history / transaction features', 'Local scratch + managed spill'])
    d.node(1155, 653, 'lightgbm', 'LightGBM', ['124,992,128 × 32 matrix', 'Full training split · seeds 0, 1, 2', 'Saved scores → budget evaluation'])
    d.node(1585, 653, '@files', 'JSON results', ['Metrics + run manifests', 'Uploaded by host Azure CLI', 'No automatic Parquet upload'])
    d.path('M244 653 H607'); d.text(314, 631, 'to local scratch', 'link', 'middle')
    d.path('M723 653 H1097'); d.text(910, 631, 'features + split', 'link', 'middle')
    d.path('M1220 653 H1525'); d.text(1373, 631, 'evaluate', 'link', 'middle')
    d.path('M1636 610 V554 Q1636 538 1620 538 H681 Q665 538 665 526')
    d.text(1125, 531, 'JSON only → runs/ in ADLS', 'link', 'middle')

    d.path('M460 851 H1717', LINE, marker=False, width=1)
    d.glyph('disk', 512, 925)
    d.text(560, 909, 'Local NVMe', 'node')
    d.lines(560, 941, ['/mnt/scratch · ≈216 GB', 'Raw files + intermediates', 'Ephemeral on deallocation'], anchor='start', cls='small', step=25)
    d.icon('azure-disk', 930, 925, 57)
    d.text(978, 909, 'Managed SSD', 'node')
    d.lines(978, 941, ['/mnt/spill · 1 TB', 'DuckDB temporary spill', 'Separate from local scratch'], anchor='start', cls='small', step=25)
    d.icon('azure-identity', 1337, 925, 57)
    d.text(1385, 909, 'Managed identity', 'node')
    d.lines(1385, 941, ['az login --identity on host', 'Blob RBAC', 'Shared-key access disabled'], anchor='start', cls='small', step=25)
    d.icon('azure-network', 435, 1050, 27)
    d.text(457, 1056, 'Recorded network: VNet + NSG + attached public IP; no NAT gateway. SSH rule was later changed to Deny.', 'small')
    d.glyph('operator', 185, 951, TEAL)
    d.text(185, 1006, 'Operator · Azure CLI', 'node', 'middle')
    d.text(185, 1035, 'az vm run-command', 'small', 'middle')
    d.path('M222 925 H399 V288 H1585 V310', TEAL, dash=True)
    d.text(1000, 283, 'Azure control plane', 'small', 'middle', TEAL)

    d.text(70, 1140, 'HISTORICAL EVIDENCE ≠ TODAY’S REPRODUCTION SCRIPT', 'eyebrow')
    d.lines(70, 1175, [
        'Archived fits preserve source and matrix provenance, but no registry image digest. Bit-for-bit container rebuild is not established.',
        'Current scripts add git archive + SHA-256 verification, dataset-pin checks and image-identity recording.',
        'The current Bicep template differs from this recorded topology; the Medium runner stages raw inputs through blob storage.'
    ], anchor='start', cls='note', step=29)
    d.footer('Solid blue: source / data movement · Dashed teal: control · ACR was not on the processing path.')
    d.save('02-azure-execution.svg')


def delivery():
    d = Diagram(3, 'From a source change to software and a website',
                'GitHub Actions validates three independent paths • Release promotion reuses the tested image manifest', 1490)
    d.icon('github', 104, 261, 61)
    d.text(150, 250, 'GitHub repository', 'node')
    d.text(150, 282, 'Pull request → protected main', 'body')
    d.path('M485 259 H574')
    d.icon('actions', 622, 261, 60)
    d.text(670, 250, 'GitHub Actions', 'node')
    d.text(670, 282, 'Separate workflows; required checks gate merge', 'body')
    d.text(1708, 250, 'CURRENT IMPLEMENTATION', 'eyebrow', 'end')
    d.text(1708, 282, 'No production model-serving endpoint', 'small', 'end')

    d.area(45, 331, 1710, 215, '#F6F9FB')
    d.text(80, 365, '01  /  SOURCE & EVIDENCE CHECKS', 'eyebrow')
    d.icon('python', 116, 431, 58)
    d.text(164, 418, 'Tests + reproducibility', 'node')
    d.lines(164, 449, ['pytest · synthetic demo · package smoke', 'Provenance, replay and figure checks'], cls='small', anchor='start', step=27)
    d.glyph('shield', 680, 431)
    d.text(728, 418, 'Security + static checks', 'node')
    d.lines(728, 449, ['CodeQL · Bandit · Gitleaks · pip-audit', 'Ruff · ShellCheck · actionlint · Bicep'], cls='small', anchor='start', step=27)
    d.glyph('files', 1248, 431)
    d.text(1296, 418, 'Publication checks', 'node')
    d.lines(1296, 449, ['Artifact-backed values + release facts', 'Public surface · Markdown · links'], cls='small', anchor='start', step=27)
    d.text(80, 519, 'PRs validate candidates; each workflow runs its own checks. Raw data and private replay bundles are excluded from publication.', 'small')

    d.text(70, 595, '02  /  CONTAINER DISTRIBUTION', 'eyebrow')
    xs=[190,655,1120,1585]
    d.node(xs[0], 674, 'docker', 'Build once', ['Docker Buildx · linux/amd64', 'Load candidate into runner'])
    d.node(xs[1], 674, 'trivy', 'Test + scan', ['Suite inside the image', 'Trivy: fixable HIGH / CRITICAL'])
    d.node(xs[2], 674, 'github', 'Publish to GHCR', ['Push the tested image', 'Commit-SHA tag + latest'])
    d.node(xs[3], 674, 'docker', 'Pull by digest', ['Pull back; verify image identity', 'Consumers use @sha256:…'])
    for a,b,label in zip(xs,xs[1:],['candidate','main push','immutable reference']):
        d.path(f'M{a+64} 674 H{b-64}')
        d.text((a+b)/2, 654, label, 'link', 'middle')
    d.text(70, 838, 'PR image builds stop after testing and scanning. The release path requires the commit image to exist before the tag is pushed.', 'note')

    d.area(45, 876, 1710, 237, '#FBF8F1')
    d.text(80, 914, 'SIGNED TAG → RELEASE', 'eyebrow', color=GOLD)
    d.icon('git', 117, 974, 51)
    d.text(158, 965, 'Signed vX.Y.Z', 'node')
    d.text(158, 996, 'Targets the built commit', 'small')
    d.path('M419 973 H485', GOLD)
    d.glyph('shield', 529, 974, GOLD)
    d.text(576, 955, 'Verify before promotion', 'node')
    d.lines(576, 986, ['Signature + tag object checked', 'GET → PUT identical manifest bytes'], cls='small', anchor='start', step=25)
    d.path('M948 973 H1017', GOLD)
    d.glyph('tag', 1061, 974, GOLD)
    d.text(1107, 955, 'Release image', 'node')
    d.lines(1107, 986, ['Same digest + media type', 'Recheck both registry references'], cls='small', anchor='start', step=25)
    d.path('M1444 973 H1516', GOLD)
    d.glyph('operator', 1560, 974, GOLD)
    d.text(1638, 957, 'Owner', 'node', 'middle')
    d.lines(1638, 988, ['publishes', 'Release notes'], cls='small', step=25)
    d.text(80, 1074, 'In parallel: release.yml verifies the tag, version, citation and publication facts. The owner checks both workflow outcomes.', 'note')

    d.text(70, 1161, '03  /  WEBSITE DELIVERY', 'eyebrow')
    d.icon('python', 111, 1230, 55)
    d.text(156, 1217, 'Generate + assemble', 'node')
    d.lines(156, 1248, ['Archive JSON → site data → HTML', 'Static assets + existing diagrams'], cls='small', anchor='start', step=26)
    d.path('M497 1230 H583')
    d.glyph('shield', 626, 1230)
    d.text(674, 1217, 'site-build', 'node')
    d.lines(674, 1248, ['Determinism + site unit contracts', 'Playwright in Chrome + surface scan'], cls='small', anchor='start', step=26)
    d.path('M1028 1230 H1105')
    d.glyph('files', 1148, 1230)
    d.text(1194, 1217, 'Tested artifact', 'node')
    d.lines(1194, 1248, ['Upload once', 'Deploy that artifact on main'], cls='small', anchor='start', step=26)
    d.path('M1470 1230 H1520')
    d.glyph('web', 1580, 1230)
    d.text(1580, 1320, 'GitHub Pages', 'node', 'middle')
    d.text(1580, 1350, 'Home · Explorer · Engineering', 'small', 'middle')
    d.text(70, 1380, 'The Pages workflow builds from repository assets. It does not deploy the GHCR container, and it never deploys from a pull request.', 'note')
    d.footer('Separate image, release-verification and website jobs; arrows show artifact flow, not a single workflow dependency chain.')
    d.save('03-ci-release.svg')


if __name__ == '__main__':
    overview()
    cloud()
    delivery()
    print('Built three self-contained SVGs.')
