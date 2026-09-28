import * as THREE from './vendor/three.module.js';
import { OrbitControls } from './vendor/OrbitControls.js';

const $ = (id) => document.getElementById(id);
const LAYER_LABEL = { white: '白', L1: 'L1', L2: 'L2', L3: 'L3', L4: 'L4' };
const EXPLODE_GAP = 8; // 分解表示での層の間隔 mm

const state = {
  api: null,
  fields: [],
  params: {},
  defaultColors: {},
  githubColors: [],
  layerNames: [],
  loaded: false,
  plates: null,
  plateIdx: 0,
  view: 'assembled',
  layerIdx: 0,
  genSeq: 0,
  genTimer: null,
  needFit: true,
  lastExport: null,
};

// ---------------------------------------------------------------- 3D 表示

const canvas = $('canvas');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 5000);
camera.up.set(0, 0, 1);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;

scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f99, 1.4));
const key = new THREE.DirectionalLight(0xffffff, 1.6);
key.position.set(-60, -90, 160);
scene.add(key);
const fill = new THREE.DirectionalLight(0xffffff, 0.5);
fill.position.set(90, 70, -40);
scene.add(fill);

const plateGroup = new THREE.Group();
scene.add(plateGroup);

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
function applyTheme() {
  scene.background = new THREE.Color(cssVar('--view-bg'));
}
applyTheme();
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);

new ResizeObserver(() => {
  const { clientWidth: w, clientHeight: h } = $('viewport');
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(h, 1);
  camera.updateProjectionMatrix();
}).observe($('viewport'));

(function loop() {
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(loop);
})();

function b64ToBuffer(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

function clearPlate() {
  for (const g of [...plateGroup.children]) {
    g.traverse((o) => {
      o.geometry?.dispose();
      o.material?.dispose();
    });
    plateGroup.remove(g);
  }
}

function showPlate() {
  clearPlate();
  const plate = state.plates?.[state.plateIdx];
  if (!plate) return;
  for (const layer of plate.layers) {
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(new Float32Array(b64ToBuffer(layer.positions)), 3));
    geom.setIndex(new THREE.BufferAttribute(new Uint32Array(b64ToBuffer(layer.indices)), 1));
    const mat = new THREE.MeshStandardMaterial({
      color: state.params.colors[layer.name], flatShading: true, roughness: 0.8, metalness: 0,
    });
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geom, 25),
      new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.22 }),
    );
    const g = new THREE.Group();
    g.add(new THREE.Mesh(geom, mat), edges);
    g.userData = { name: layer.name, z0: layer.z0, mat };
    plateGroup.add(g);
  }
  state.layerIdx = Math.min(state.layerIdx, plate.layers.length - 1);
  renderLayerButtons();
  applyView();
  renderDims();
}

function applyView() {
  const n = plateGroup.children.length;
  plateGroup.children.forEach((g, i) => {
    g.visible = state.view !== 'single' || i === state.layerIdx;
    // i = 0 が一番上（白）。分解表示では下の層ほど低い位置
    g.position.z = state.view === 'exploded' ? (n - 1 - i) * EXPLODE_GAP
      : state.view === 'single' ? -g.userData.z0 : 0;
  });
  $('seg-layer').hidden = state.view !== 'single';
  if (state.needFit) {
    fitCamera('iso');
    state.needFit = false;
  }
}

function visibleBox() {
  const box = new THREE.Box3();
  plateGroup.updateMatrixWorld(true);
  for (const g of plateGroup.children) if (g.visible) box.expandByObject(g);
  return box;
}

function fitCamera(dir) {
  const box = visibleBox();
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const radius = box.getSize(new THREE.Vector3()).length() / 2;
  const dist = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.05;
  const v = { top: [0, -0.02, 1], iso: [0.3, -1, 0.85], bottom: [0, -0.02, -1] }[dir];
  const d = new THREE.Vector3(...v).normalize().multiplyScalar(dist);
  camera.position.copy(center).add(d);
  controls.target.copy(center);
  camera.near = dist / 100;
  camera.far = dist * 10;
  camera.updateProjectionMatrix();
}

function updateColors() {
  for (const g of plateGroup.children) g.userData.mat.color.set(state.params.colors[g.userData.name]);
}

// ---------------------------------------------------------------- 画面の組み立て

function renderFields() {
  const root = $('fields');
  root.innerHTML = '';
  let group = null;
  for (const f of state.fields) {
    if (f.group !== group) {
      group = f.group;
      const h = document.createElement('h3');
      h.textContent = group;
      root.append(h);
    }
    const row = document.createElement('div');
    row.className = 'field' + (f.kind === 'bool' ? ' check' : '');
    const id = `f-${f.name}`;
    const input = document.createElement('input');
    input.id = id;
    input.dataset.name = f.name;
    const label = document.createElement('label');
    label.htmlFor = id;
    label.textContent = f.label;
    if (f.kind === 'bool') {
      input.type = 'checkbox';
      input.addEventListener('change', () => { state.params[f.name] = input.checked; scheduleGenerate(0); });
      row.append(input, label);
    } else {
      if (f.kind === 'float') {
        Object.assign(input, { type: 'number', min: f.min, max: f.max, step: f.step });
      } else {
        input.type = 'text';
        input.spellcheck = false;
      }
      input.addEventListener('input', () => {
        if (f.kind === 'float') {
          const v = parseFloat(input.value);
          if (Number.isNaN(v)) return;
          state.params[f.name] = v;
        } else {
          state.params[f.name] = input.value;
        }
        scheduleGenerate();
      });
      const unit = document.createElement('span');
      unit.className = 'unit';
      unit.textContent = f.unit;
      row.append(label, input, unit);
    }
    root.append(row);
  }
  syncFieldInputs();
}

function syncFieldInputs() {
  for (const f of state.fields) {
    const input = $(`f-${f.name}`);
    if (f.kind === 'bool') input.checked = !!state.params[f.name];
    else input.value = state.params[f.name];
  }
  for (const name of state.layerNames) $(`c-${name}`).value = state.params.colors[name].toLowerCase();
}

function renderColors() {
  const root = $('colors');
  root.innerHTML = '';
  state.layerNames.forEach((name) => {
    const row = document.createElement('div');
    row.className = 'field';
    const label = document.createElement('label');
    label.htmlFor = `c-${name}`;
    label.textContent = name === 'white' ? '白（天板・L0）' : name;
    const input = document.createElement('input');
    input.type = 'color';
    input.id = `c-${name}`;
    input.addEventListener('input', () => {
      state.params.colors[name] = input.value.toUpperCase();
      updateColors();
    });
    row.append(label, input);
    root.append(row);
  });
}

function setColors(colors) {
  state.params.colors = { ...colors };
  syncFieldInputs();
  updateColors();
}

function renderPlateButtons() {
  const seg = $('seg-plate');
  seg.innerHTML = '';
  (state.plates || []).forEach((p, i) => {
    const b = document.createElement('button');
    b.textContent = `${p.name}（${p.period[0].slice(2, 7).replace('-', '/')}〜${p.period[1].slice(2, 7).replace('-', '/')}）`;
    b.classList.toggle('on', i === state.plateIdx);
    b.addEventListener('click', () => {
      state.plateIdx = i;
      state.needFit = true;
      renderPlateButtons();
      showPlate();
    });
    seg.append(b);
  });
}

function renderLayerButtons() {
  const seg = $('seg-layer');
  seg.innerHTML = '';
  const plate = state.plates?.[state.plateIdx];
  (plate?.layers || []).forEach((l, i) => {
    const b = document.createElement('button');
    b.textContent = `${i + 1}. ${LAYER_LABEL[l.name]}`;
    b.classList.toggle('on', i === state.layerIdx);
    b.addEventListener('click', () => {
      state.layerIdx = i;
      state.needFit = true;
      renderLayerButtons();
      applyView();
    });
    seg.append(b);
  });
}

function renderDims() {
  const plate = state.plates?.[state.plateIdx];
  if (!plate) { $('dims').textContent = ''; return; }
  const i = plate.info;
  const counts = Object.entries(i.counts).map(([k, v]) => `${k} ${v}`).join(' / ');
  $('dims').textContent =
    `${plate.name}：${plate.period[0]} 〜 ${plate.period[1]}　外形 ${i.plate_w.toFixed(1)} × ${i.plate_h.toFixed(1)} mm　` +
    `厚さ ${i.thickness.toFixed(1)} mm（突起込み ${i.total.toFixed(1)} mm）　` +
    `層 ${plate.layers.map((l) => LAYER_LABEL[l.name]).join(' → ')}　マス数 ${counts}`;
}

function renderGrids(data) {
  $('data-summary').hidden = false;
  $('data-total').textContent = `${data.user}：直近 1 年で ${data.total.toLocaleString()} コントリビューション`;
  const root = $('grids');
  root.innerHTML = '';
  data.halves.forEach((h, i) => {
    const wrap = document.createElement('div');
    wrap.className = 'grid-wrap';
    const period = document.createElement('div');
    period.className = 'period';
    period.textContent = `plate${i + 1}：${h.period[0]} 〜 ${h.period[1]}`;
    const grass = document.createElement('div');
    grass.className = 'grass';
    grass.style.gridTemplateColumns = `repeat(${h.grid[0].length}, 1fr)`;
    for (const row of h.grid) {
      for (const lv of row) {
        const s = document.createElement('span');
        s.style.background = lv === null ? 'transparent' : state.githubColors[lv];
        grass.append(s);
      }
    }
    wrap.append(period, grass);
    root.append(wrap);
  });
}

function renderWarnings(list) {
  const ul = $('warnings');
  ul.innerHTML = '';
  for (const w of list || []) {
    const li = document.createElement('li');
    li.textContent = w;
    ul.append(li);
  }
}

function showError(msg) {
  $('error').hidden = !msg;
  $('error').textContent = msg || '';
}

function setTokenStatus(source) {
  $('token-status').textContent = source
    ? `トークン：${source} を使います`
    : 'トークンが見つかりません。データの取得には GitHub のトークンが必要です';
}

// ---------------------------------------------------------------- Python 呼び出し

async function call(name, ...args) {
  try {
    return await state.api[name](...args);
  } catch (e) {
    return { ok: false, error: String(e?.message || e) };
  }
}

function scheduleGenerate(delay = 500) {
  if (!state.loaded) return;
  clearTimeout(state.genTimer);
  state.genTimer = setTimeout(generate, delay);
}

async function generate() {
  const seq = ++state.genSeq;
  $('busy').hidden = false;
  const res = await call('generate', state.params);
  if (seq !== state.genSeq) return; // 新しい生成が始まっていれば古い結果は捨てる
  $('busy').hidden = true;
  if (!res.ok) { showError(res.error); return; }
  showError('');
  const first = !state.plates;
  state.plates = res.plates;
  state.plateIdx = Math.min(state.plateIdx, res.plates.length - 1);
  if (first) state.needFit = true;
  $('empty').hidden = true;
  $('btn-export').disabled = false;
  renderPlateButtons();
  showPlate();
  renderWarnings(res.warnings);
}

async function loadData(promise) {
  $('busy').hidden = false;
  showError('');
  const res = await promise;
  $('busy').hidden = true;
  if (res.cancelled) return;
  if (!res.ok) { showError(res.error); return; }
  state.loaded = true;
  state.plates = null;
  state.plateIdx = 0;
  $('user').value = res.user;
  renderGrids(res);
  generate();
}

async function init() {
  state.api = window.pywebview.api;
  const res = await call('init');
  state.fields = res.fields;
  state.defaultColors = res.colors;
  state.githubColors = res.github_colors;
  state.layerNames = res.layer_names;
  state.params = Object.fromEntries(res.fields.map((f) => [f.name, f.default]));
  state.params.colors = { ...res.colors };
  setTokenStatus(res.token_source);
  renderColors();
  renderFields();

  $('btn-fetch').addEventListener('click', () => loadData(call('fetch', $('user').value, $('start-date').value)));
  $('user').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('btn-fetch').click(); });
  $('btn-demo').addEventListener('click', () => loadData(call('demo', $('user').value, $('start-date').value)));
  $('btn-start-date-reset').addEventListener('click', () => { $('start-date').value = ''; });
  $('btn-json').addEventListener('click', () => loadData(call('load_json', $('user').value)));

  $('btn-token-save').addEventListener('click', async () => {
    const r = await call('save_token', $('token').value);
    if (!r.ok) { showError(r.error); return; }
    $('token').value = '';
    $('token-box').open = false;
    setTokenStatus(r.token_source);
  });
  $('btn-token-delete').addEventListener('click', async () => setTokenStatus((await call('delete_token')).token_source));

  $('btn-colors-filament').addEventListener('click', () => setColors(state.defaultColors));
  $('btn-colors-github').addEventListener('click', () => {
    const g = state.githubColors;
    setColors({ white: g[0], L1: g[1], L2: g[2], L3: g[3], L4: g[4] });
  });

  $('seg-view').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    state.view = b.dataset.view;
    state.needFit = true;
    for (const x of $('seg-view').children) x.classList.toggle('on', x === b);
    applyView();
  });
  $('btn-cam-top').addEventListener('click', () => fitCamera('top'));
  $('btn-cam-iso').addEventListener('click', () => fitCamera('iso'));
  $('btn-cam-bottom').addEventListener('click', () => fitCamera('bottom'));

  $('btn-export').addEventListener('click', async () => {
    $('busy').hidden = false;
    const r = await call('export', state.params);
    $('busy').hidden = true;
    if (r.cancelled) return;
    if (!r.ok) { showError(r.error); return; }
    state.lastExport = r;
    $('export-result').hidden = false;
    $('export-dir').textContent = `${r.files.length} 個のファイルを書き出しました：${r.dir}`;
  });
  $('btn-open-folder').addEventListener('click', () => state.lastExport && call('open_folder', state.lastExport.dir));
  $('btn-open-slicer').addEventListener('click', () => state.lastExport && call('open_in_slicer', state.lastExport.threemf));
  $('btn-coupons').addEventListener('click', async () => {
    const r = await call('export_test_coupons', state.params);
    if (r.cancelled) return;
    if (!r.ok) { showError(r.error); return; }
    state.lastExport = { ...(state.lastExport || {}), dir: r.dir };
    $('export-result').hidden = false;
    $('export-dir').textContent = `テスト片 ${r.files.length} 個を書き出しました：${r.dir}`;
  });
  $('btn-preset-save').addEventListener('click', async () => {
    const r = await call('save_preset', state.params);
    if (!r.ok) showError(r.error);
  });
  $('btn-preset-load').addEventListener('click', async () => {
    const r = await call('load_preset');
    if (r.cancelled) return;
    if (!r.ok) { showError(r.error); return; }
    state.params = r.params;
    syncFieldInputs();
    updateColors();
    scheduleGenerate(0);
  });
}

if (window.pywebview?.api) init();
else window.addEventListener('pywebviewready', init, { once: true });
