// Panel (index.html içindeki JavaScript) ile Python hesabının aynı sonucu verdiğini denetler.
// index.html'in betiği sahte bir sayfa ortamında çalıştırılır; kayıtlı Open-Meteo yanıtı (fixtures/open_meteo.json)
// ve sabit bir "şimdi" (fixtures/expected.json) kullanılır. Beklenen değerler Python (telegram_report.py) hesabından gelir.
// Çalıştırma:  node tests/parity.mjs
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (p) => fs.readFileSync(path.join(here, p), "utf8");
const html = fs.readFileSync(process.env.INDEX_HTML || path.join(here, "..", "index.html"), "utf8"); // INDEX_HTML: başka bir kopyayı denemek için
const fixture = JSON.parse(read("fixtures/open_meteo.json"));
const expected = JSON.parse(read("fixtures/expected.json"));

// index.html'deki en büyük <script> bloğu paneldir
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const code = scripts.sort((a, b) => b.length - a.length)[0];

// sabit "şimdi": Moldova saatiyle expected.fixed_now (kış saati, UTC+2)
const [d, t] = expected.fixed_now.split("T");
const [Y, M, D] = d.split("-").map(Number);
const [H, Mi] = t.split(":").map(Number);
const FIXED = Date.UTC(Y, M - 1, D, H - 2, Mi);

const cache = {};
const makeEl = (id) => ({
  id, className: "", innerHTML: "", textContent: "", hidden: false, style: {}, dataset: {}, value: "", disabled: false,
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  addEventListener() {}, removeEventListener() {}, setAttribute() {}, getAttribute() { return null; }, appendChild() {},
  focus() {}, click() {}, scrollIntoView() {}, closest() { return null; },
  querySelector() { return makeEl("q"); }, querySelectorAll() { return []; },
  getBoundingClientRect() { return { left: 0, top: 0, width: 600, height: 300 }; }, offsetWidth: 600, clientWidth: 600,
});
const getEl = (id) => cache[id] || (cache[id] = makeEl(id));
const document = {
  getElementById: getEl, querySelector: (s) => getEl(s), querySelectorAll: () => [], addEventListener() {},
  createElement: () => makeEl("x"), documentElement: { lang: "" }, title: "", hidden: false, body: makeEl("body"),
};
const sandbox = {
  document, localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  navigator: { language: "tr-TR", languages: ["tr-TR"] },
  location: { hash: "", pathname: "/", search: "", href: "http://test/" }, history: { replaceState() {} },
  setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {}, console,
  AbortController, Intl, Math, JSON, Array, Object, Number, String, parseFloat, parseInt, isFinite, Promise,
  fetch: (u) => /api\.open-meteo\.com\/v1\/forecast/.test(String(u))
    ? Promise.resolve({ ok: true, json: () => Promise.resolve(JSON.parse(JSON.stringify(fixture))) })
    : Promise.reject(new Error("test: ağ yok")),
};
sandbox.window = sandbox;
sandbox.matchMedia = () => ({ matches: false });
sandbox.addEventListener = () => {};
sandbox.requestAnimationFrame = () => 0;
vm.createContext(sandbox);
vm.runInContext(`
  const RealDate = Date;
  globalThis.Date = class extends RealDate {
    constructor(...a) { if (a.length) super(...a); else super(${FIXED}); }
    static now() { return ${FIXED}; }
  };`, sandbox);
vm.runInContext(code, sandbox);
for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r)); // fetch ve render tamamlansın

const tiles = cache["tiles"]?.innerHTML || "";
const text = (s) => s.replace(/<br>/g, " | ").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
const tileList = tiles.split('<div class="tile">').slice(1).map(text);
let failed = 0;
const check = (name, got, want, tol = 0.051) => {
  const ok = Math.abs(got - want) <= tol;
  if (!ok) failed++;
  console.log(`${ok ? "TAMAM" : "HATA "} ${name}: panel=${got}  python=${want.toFixed(2)}`);
};
const num = (s) => Number(s.replace(",", "."));

if (tileList.length < 2) {
  console.log("HATA  üretim kartı bulunamadı (panel çalışmadı?)");
  console.log(tiles.slice(0, 300));
  process.exit(1);
}
const prod = tileList[1]; // "24 saat üretim 14,9 MWh modeller 14,9–24,3 MWh | saha belirsizliği dahil: 11,7–19,7 MWh"
console.log("kart:", prod);
const big = prod.match(/üretim\s+([\d.,]+)\s*MWh/);
const models = prod.match(/modeller\s+([\d.,]+)–([\d.,]+)/);
const site = prod.match(/dahil:\s+([\d.,]+)–([\d.,]+)/);
if (!big || !models || !site) { console.log("HATA  kart metni beklenen biçimde değil"); process.exit(1); }
const m = Object.values(expected.models);
check("24 saat üretim (ECMWF) MWh", num(big[1]), expected.models.e);
check("modeller en düşük MWh", num(models[1]), Math.min(...m));
check("modeller en yüksek MWh", num(models[2]), Math.max(...m));
check("saha katsayısı ×1,05 MWh", num(site[1]), expected.site_lo);
check("saha katsayısı ×1,25 MWh", num(site[2]), expected.site_hi);
if (failed) { console.log(`\n${failed} denetim başarısız: panel ile Python hesabı ayrışmış.`); process.exit(1); }
console.log("\nTüm denetimler geçti: panel ve Python aynı sonucu veriyor.");
