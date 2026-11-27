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
  w.eval(fs.readFileSync(path.join(root, "assets", "solver_info.js"), "utf8"));
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
    await new Promise(resolve => w.setTimeout(resolve, 100));
  }
  return { dom, w, $, set, save, select, importData, errors, store,
    failWrites: () => { failWrites = true; } };
}

async function main() {
  if (family === "portfolio_mv") {
    const preset = launch();
    for (const name of ["portfolio_500_classic", "portfolio_500_dwave"]) {
      const archive = JSON.parse(fs.readFileSync(path.join(root, "favorites", name + ".json"), "utf8"));
      await preset.importData(archive);
      assert.match(preset.$("favoritesMessage").textContent, /Importati 1 preferiti/);
      preset.select(name);
      preset.$("loadFavorite").click();
      for (const [id, value] of Object.entries(archive.entries[0].fields)) {
        const field = preset.$(id);
        assert.equal(field.type === "checkbox" ? field.checked : field.value, value, id);
      }
      assert.equal(preset.$("cliPreview").textContent, archive.entries[0].command);
      assert.equal(preset.$("copyCommand").disabled, false);
    }
    preset.dom.window.close();
  }
  // Name proposals must behave identically in all three configurators.
  const names = launch();
  const initialRunId = names.$("runId").value;
  assert.equal(names.$("favoriteName").value, initialRunId);
  names.set("runId", "auto_one");
  assert.equal(names.$("favoriteName").value, "auto_one");
  names.set("runId", "auto_two");
  assert.equal(names.$("favoriteName").value, "auto_two");
  names.set("favoriteName", "Personalizzato");
  names.set("runId", "auto_three");
  assert.equal(names.$("favoriteName").value, "Personalizzato");
  names.set("favoriteName", "");
  assert.equal(names.$("favoriteName").value, "");
  names.set("runId", "auto_four");
  assert.equal(names.$("favoriteName").value, "auto_four");
  if (family === "facility_location") names.set("instancePath", "instance.txt");
  names.save("Nome salvato");
  names.select("Nome salvato");
  names.set("favoriteName", "Modificato dopo selezione");
  names.$("loadFavorite").click();
  assert.equal(names.$("favoriteName").value, "Nome salvato");
  names.set("runId", "after_load");
  assert.equal(names.$("favoriteName").value, "Nome salvato");
  names.$("resetDefaults").click();
  assert.equal(names.$("favoriteName").value, names.$("runId").value);
  names.set("runId", "after_reset");
  assert.equal(names.$("favoriteName").value, "after_reset");
  names.set("favoriteName", "Altro nome");
  names.$("resetDefaults").click();
  assert.equal(names.$("favoriteName").value, initialRunId);
  assert.deepEqual(names.errors, []);
  names.dom.window.close();

  const app = launch();
  const { $, w, set, save, select } = app;
  assert.ok($("favoritesPanel").closest("aside.summary"));
  assert.equal($("loadFavorite").disabled, true);
  assert.equal($("exportFavorites").disabled, true);
  set("runId", "favorite_run");
  if (family === "portfolio_sr") {
    set("lowerBound", "0.05");
    set("minSelectedAssets", "2");
    set("maxPositions", "5");
  }
  if (family === "portfolio_mv") set("numSourceMisCandidates", "5");
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
  if (family === "portfolio_sr") {
    set("lowerBound", "0");
    set("minSelectedAssets", "");
    set("maxPositions", "");
  }
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
  if (family === "portfolio_sr") {
    const compatible = JSON.parse(JSON.stringify(archive));
    const entry = compatible.entries[0];
    compatible.entries = [entry];
    delete entry.fields.minSelectedAssets;
    delete entry.fields.lowerBound;
    entry.command = entry.command.replace("--max-selected-assets", "--max-positions");
    for (const imported of [false, true]) {
      const legacy = launch(imported ? new Map() : new Map([[key, JSON.stringify(compatible)]]));
      if (imported) await legacy.importData(compatible);
      const storedBeforeLoad = legacy.store.get(key);
      legacy.set("minSelectedAssets", "3");
      legacy.set("lowerBound", "0.1");
      legacy.select(entry.name);
      assert.equal(legacy.$("loadFavorite").disabled, false);
      legacy.$("loadFavorite").click();
      assert.equal(legacy.$("minSelectedAssets").value, "");
      assert.equal(Number(legacy.$("lowerBound").value), 0);
      assert.equal(legacy.$("maxPositions").value, "5");
      assert.match(legacy.$("cliPreview").textContent, /--max-selected-assets\s+5/);
      assert.doesNotMatch(legacy.$("cliPreview").textContent, /--max-positions|--min-selected-assets|--lower-bound/);
      assert.equal(legacy.store.get(key), storedBeforeLoad);
      assert.deepEqual(legacy.errors, []);
      legacy.dom.window.close();
    }
  }
  if (family === "portfolio_mv") {
    otherBrowser.set("numSourceMisCandidates", "7");
    otherBrowser.select("Zeta");
    otherBrowser.$("loadFavorite").click();
    assert.equal(otherBrowser.$("numSourceMisCandidates").value, "5");
    assert.match(otherBrowser.$("cliPreview").textContent, /--num-source-mis-candidates\s+5/);

    for (const savedValue of [undefined, "", "3"]) {
      const compatible = JSON.parse(JSON.stringify(archive));
      compatible.entries = [compatible.entries[0]];
      delete compatible.entries[0].fields.pasqalQpuDevice;
      delete compatible.entries[0].fields.pasqalQpuShots;
      if (savedValue === undefined) delete compatible.entries[0].fields.numSourceMisCandidates;
      else compatible.entries[0].fields.numSourceMisCandidates = savedValue;
      // Verify both existing local archives and imported JSON.
      for (const imported of [false, true]) {
        const legacy = launch(imported ? new Map() : new Map([[key, JSON.stringify(compatible)]]));
        if (imported) await legacy.importData(compatible);
        const storedBeforeLoad = legacy.store.get(key);
        legacy.set("numSourceMisCandidates", "7");
        legacy.set("pasqalQpuDevice", "FRESNEL_CAN1");
        legacy.set("pasqalQpuShots", "100");
        legacy.select(compatible.entries[0].name);
        assert.equal(legacy.$("loadFavorite").disabled, false);
        legacy.$("loadFavorite").click();
        assert.equal(legacy.$("numSourceMisCandidates").value, savedValue || "");
        assert.equal(legacy.$("pasqalQpuDevice").value, "");
        assert.equal(legacy.$("pasqalQpuShots").value, "");
        if (savedValue) assert.match(legacy.$("cliPreview").textContent, /--num-source-mis-candidates\s+3/);
        else assert.doesNotMatch(legacy.$("cliPreview").textContent, /--num-source-mis-candidates/);
        assert.deepEqual(legacy.errors, []);
        assert.equal(legacy.store.get(key), storedBeforeLoad, "loading must not migrate the archive");
        legacy.dom.window.close();
      }
    }
    const qpu = launch();
    qpu.set("misSolver", "pasqal_qpu");
    qpu.set("pasqalQpuDevice", "FRESNEL_CAN1");
    qpu.set("pasqalQpuShots", "100");
    qpu.set("pasqalQpuConsent", true);
    qpu.save("QPU");
    const saved = JSON.parse(qpu.store.get(key)).entries[0];
    assert.equal(saved.fields.pasqalQpuDevice, "FRESNEL_CAN1");
    assert.equal(saved.fields.pasqalQpuConsent, undefined);
    assert.equal(saved.command, "");
    qpu.select("QPU");
    qpu.$("loadFavorite").click();
    assert.equal(qpu.$("pasqalQpuConsent").checked, false);
    assert.equal(qpu.$("copyCommand").disabled, true);
    qpu.dom.window.close();

    // Compatibility must not allow arbitrary missing or unknown fields.
    for (const invalidFields of [
      { ...archive.entries[0].fields, unexpected: "value" },
      Object.fromEntries(Object.entries(archive.entries[0].fields).filter(([id]) =>
        id !== "numSourceMisCandidates" && id !== "runId")),
      { ...archive.entries[0].fields, numSourceMisCandidates: false },
    ]) {
      const invalid = { ...archive, entries: [{ ...archive.entries[0], fields: invalidFields }] };
      const rejected = launch();
      await rejected.importData(invalid);
      assert.match(rejected.$("favoritesMessage").textContent, /rifiutata/);
      assert.equal(rejected.store.has(key), false);
      rejected.dom.window.close();
    }
  }

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