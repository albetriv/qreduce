/** Exercise favorites against the real configurator DOM and scripts. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const root = path.join(__dirname, "..", "uix");
const family = process.argv[2];
const key = "qreduce.uix.favorites.v1." + family;
const common = fs.readFileSync(path.join(root, "assets", "common.js"), "utf8");
const html = fs.readFileSync(path.join(root, "experiment_" + family + ".html"), "utf8");

function launch(store = new Map(), mode = "normal") {
  const dom = new JSDOM(html, { url: "file:///qreduce/uix/experiment_" + family + ".html", runScripts: "outside-only" });
  const w = dom.window;
  const errors = [];
  w.addEventListener("error", event => errors.push(event.error));
  let failWrites = mode === "readOnly";
  const storage = {
    getItem: key => store.has(key) ? store.get(key) : null,
    setItem: (key, value) => { if (failWrites) throw new Error("Quota exceeded"); store.set(key, value); },
    removeItem: key => store.delete(key),
  };
  Object.defineProperty(w, "localStorage", { get() {
    if (mode === "unavailable") throw new Error("SecurityError");
    return storage;
  } });
  w.confirm = () => true;
  w.eval(common);
  if (family === "portfolio_sr") {
    w.document.querySelectorAll("script:not([src])").forEach(script => {
      if (script.textContent.includes("DOMContentLoaded")) w.eval(script.textContent);
    });
  } else {
    w.eval(fs.readFileSync(path.join(root, "assets", family === "portfolio_mv" ? "portfolio_mv.js" : "facility_location.js"), "utf8"));
  }
  w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  const $ = id => w.document.getElementById(id);
  function set(id, value) {
    const field = $(id);
    if (field.type === "checkbox") field.checked = value;
    else field.value = value;
    field.dispatchEvent(new w.Event("input", { bubbles: true }));
    field.dispatchEvent(new w.Event("change", { bubbles: true }));
  }
  function save(name) { set("favoriteName", name); $("saveFavorite").click(); }
  function select(name) { set("favoritesList", name); }
  async function importData(data) {
    const file = new w.File([typeof data === "string" ? data : JSON.stringify(data)], "favorites.json", { type: "application/json" });
    Object.defineProperty($("favoritesFile"), "files", { configurable: true, value: [file] });
    $("favoritesFile").dispatchEvent(new w.Event("change"));
    await new Promise(resolve => w.setTimeout(resolve, 25));
  }
  return { dom, w, $, set, save, select, importData, errors, store,
    failWrites: () => { failWrites = true; } };
}

async function main() {
  const app = launch();
  const { $, w, set, save, select } = app;
  assert.ok($("favoritesPanel").closest("aside.summary"));
  assert.equal($("loadFavorite").disabled, true);
  assert.equal($("exportFavorites").disabled, true);
  set("runId", "favorite_run");
  if (family === "facility_location") set("instancePath", "data/example instance.txt");
  assert.equal($("copyCommand").disabled, false);
  w.document.querySelector('[data-format="multiline"]').click();
  const expected = $("cliPreview").textContent;
  const fieldValues = {};
  w.document.querySelectorAll("#configForm input[id], #configForm select[id], #configForm textarea[id]").forEach(field => {
    fieldValues[field.id] = field.type === "checkbox" ? field.checked : field.value;
  });
  save("Zeta"); save("Alfa");
  assert.deepEqual(Array.from($("favoritesList").options, option => option.value), ["Alfa", "Zeta"]);
  assert.equal(app.store.size, 1, "probe must be removed");
  const archive = JSON.parse(app.store.get(key));
  const readable = launch(new Map(app.store), "readOnly");
  assert.equal(readable.$("favoritesList").options.length, 2);
  assert.equal(readable.$("exportFavorites").disabled, false);
  assert.match(readable.$("favoritesStorage").textContent, /solo in memoria/);
  readable.dom.window.close();
  assert.equal(Array.from(app.store.keys())[0], key, "only this configurator's key is written");
  assert.equal(archive.entries.length, 2);
  assert.equal(archive.entries[0].format, "multiline");
  set("runId", "changed");
  w.document.querySelector('[data-format="inline"]').click();
  select("Alfa"); $("loadFavorite").click();
  assert.equal($("cliPreview").textContent, expected);
  Object.entries(fieldValues).forEach(([id, value]) => {
    assert.equal($(id).type === "checkbox" ? $(id).checked : $(id).value, value, id);
  });
  w.confirm = () => false;
  set("runId", "not_saved"); save("Alfa");
  assert.equal(JSON.parse(app.store.get(key)).entries[0].fields.runId, "favorite_run");
  select("Alfa"); $("deleteFavorite").click();
  assert.equal(JSON.parse(app.store.get(key)).entries.length, 2);
  w.confirm = () => true;
  save("Alfa");
  assert.equal(JSON.parse(app.store.get(key)).entries[0].fields.runId, "not_saved");
  select("Zeta"); $("deleteFavorite").click();
  assert.equal(JSON.parse(app.store.get(key)).entries.length, 1);
  $("resetDefaults").click();
  assert.equal(JSON.parse(app.store.get(key)).entries.length, 1);
  set("runId", "");
  save("Invalid");
  assert.equal(JSON.parse(app.store.get(key)).entries.length, 1);

  const reopened = launch(app.store);
  assert.equal(reopened.$("favoritesList").options[0].value, "Alfa");
  assert.notEqual(reopened.$("runId").value, "not_saved", "no automatic loading");
  await reopened.importData(archive);
  assert.deepEqual(Array.from(reopened.$("favoritesList").options, option => option.value), ["Alfa", "Alfa (2)", "Zeta"]);
  const before = app.store.get(key);
  for (const invalid of ["{", { ...archive, family: "other" }, { ...archive, version: 99 },
    { ...archive, entries: [{ ...archive.entries[0], name: "x".repeat(161) }] },
    { ...archive, entries: [archive.entries[0], archive.entries[0]] },
    { ...archive, entries: [{ ...archive.entries[0], fields: {} }] },
    { ...archive, entries: [{ ...archive.entries[0], fields: { ...archive.entries[0].fields, runId: false } }] }]) {
    await reopened.importData(invalid);
    assert.equal(app.store.get(key), before);
    assert.match(reopened.$("favoritesMessage").textContent, /rifiutata/);
  }
  const oversized = new reopened.w.File(["x".repeat(5 * 1024 * 1024 + 1)], "large.json");
  Object.defineProperty(reopened.$("favoritesFile"), "files", { configurable: true, value: [oversized] });
  reopened.$("favoritesFile").dispatchEvent(new reopened.w.Event("change"));
  assert.match(reopened.$("favoritesMessage").textContent, /5 MiB/);
  assert.equal(app.store.get(key), before);
  let exported;
  reopened.w.URL.createObjectURL = blob => { exported = blob; return "blob:test"; };
  reopened.w.URL.revokeObjectURL = () => {};
  reopened.w.HTMLAnchorElement.prototype.click = function () {
    assert.equal(this.download, "qreduce-favorites-" + family + ".json");
  };
  reopened.$("exportFavorites").click();
  const content = await new Promise(resolve => {
    const reader = new reopened.w.FileReader();
    reader.onload = () => resolve(JSON.parse(reader.result));
    reader.readAsText(exported);
  });
  assert.equal(content.entries.length, 3);
  const otherBrowser = launch();
  await otherBrowser.importData(content);
  assert.equal(JSON.parse(otherBrowser.store.get(key)).entries.length, 3);

  const memory = launch(new Map(), "unavailable");
  memory.set("runId", "memory");
  if (family === "facility_location") memory.set("instancePath", "instance.txt");
  memory.save("Memory");
  assert.match(memory.$("favoritesStorage").textContent, /solo in memoria/);
  assert.equal(memory.$("exportFavorites").disabled, false);
  const corruptedStore = new Map([[key, "broken"]]);
  const corrupted = launch(corruptedStore);
  assert.equal(corrupted.$("saveFavorite").disabled, true);
  assert.equal(corrupted.$("importFavorites").disabled, true);
  assert.equal(corruptedStore.get(key), "broken");
  otherBrowser.failWrites();
  otherBrowser.save("Quota");
  assert.match(otherBrowser.$("favoritesStorage").textContent, /Scrittura non riuscita/);
  assert.equal(otherBrowser.$("favoritesList").options.length, 4);

  // A second window must not silently overwrite changes made after it opened.
  app.set("runId", "valid_again");
  app.save("Stale");
  assert.match(app.$("favoritesMessage").textContent, /altra finestra/);
  assert.equal(app.store.get(key), before);
  const tooLarge = launch();
  tooLarge.set("runId", "large");
  if (family === "facility_location") tooLarge.set("instancePath", "instance.txt");
  tooLarge.set("outputRoot", "x".repeat(3 * 1024 * 1024));
  tooLarge.save("Too large");
  assert.match(tooLarge.$("favoritesMessage").textContent, /oltre 5 MiB/);
  assert.equal(tooLarge.store.has(key), false);
  tooLarge.dom.window.close();
  for (const instance of [app, reopened, otherBrowser, memory, corrupted]) {
    assert.deepEqual(instance.errors, []);
    instance.dom.window.close();
  }
  console.log(JSON.stringify({ family, success: true }));
}
main().catch(error => { console.error(error); process.exit(1); });