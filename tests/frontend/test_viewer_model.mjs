import assert from "node:assert/strict";
import test from "node:test";
import {ViewerModel, inputText, PAGE_SIZE} from "../../custom_components/casambi_bt/frontend/viewer-model.js";
import {translations, stringsForLanguage} from "../../custom_components/casambi_bt/frontend/translations.js";

const row = sequence => ({id:`store:${sequence}`,sequence,type:"input",name:"Switch",unit:30,button:1,button_index:1,input_action:"press"});
const page = (phase,events,cursor) => ({phase,events,store_id:"store",scanned_to_sequence:cursor,upper_sequence:cursor,has_more:false});

test("live input keeps the inspected observation and paused reading window", () => {
  const model=new ViewerModel();
  model.applyPage(page("snapshot",[row(1)],1));
  model.selected=model.rows[0];
  model.follow=false;
  const selected=model.selected, rows=model.rows;
  assert.equal(model.applyPage(page("live",[row(2)],2)),false);
  assert.equal(model.rows,rows);
  assert.equal(model.selected,selected);
  assert.equal(model.unread,1);
  assert.equal(model.cursor,2);
});

test("replayed IDs do not duplicate rows while distinct received copies remain", () => {
  const model=new ViewerModel();
  model.applyPage(page("snapshot",[row(1)],1));
  model.applyPage(page("live",[row(1),row(2),row(3)],3));
  assert.deepEqual(model.rows.map(item=>item.sequence),[3,2,1]);
});

test("the resident page is bounded without losing the durable replay cursor", () => {
  const model=new ViewerModel();
  model.applyPage(page("snapshot",[],0));
  for(let start=1;start<=10_000;start+=250) model.applyPage(page("catch_up",Array.from({length:250},(_,index)=>row(start+index)),start+249));
  assert.equal(model.rows.length,PAGE_SIZE);
  assert.equal(model.rows[0].sequence,10_000);
  assert.equal(model.cursor,10_000);
  assert.equal(model.hasMore,true);
});

test("a filtered snapshot preserves selected details and null input values", () => {
  const model=new ViewerModel();
  model.selected={...row(1),input_value16:null};
  const selected=model.selected;
  model.resetQuery();
  model.applyPage(page("snapshot",[],500));
  assert.equal(model.selected,selected);
  assert.equal(model.selected.input_value16,null);
});

test("primary input labels contain button and action while unknown indices stay explicit", () => {
  assert.equal(inputText(row(1),translations.zh),"第 1 键 · 按下");
  assert.equal(inputText({...row(1),button:null,button_index:7,input_action:null},translations.en),"Input index 7 · Input report");
  assert.equal(inputText({...row(1),type:"lux",value:"500 lux"},translations.en),"500 lux");
});

test("HA German language variants select German while other locales keep their language policy", () => {
  for (const locale of ["de", "de-DE", "de-AT", "de-CH"]) {
    const strings = stringsForLanguage(locale);
    assert.equal(strings.title, "Netzwerkereignisse");
    assert.equal(inputText(row(1), strings), "Taste 1 · Gedrückt");
    assert.equal(inputText({...row(1), input_action:"release"}, strings), "Taste 1 · Losgelassen");
    assert.equal(inputText({...row(1), button:null, button_index:7, input_action:null}, strings), "Eingangsindex 7 · Eingangsmeldung");
  }
  assert.equal(stringsForLanguage("zh-Hans"), translations.zh);
  assert.equal(stringsForLanguage("en-GB"), translations.en);
  assert.equal(stringsForLanguage("nl"), translations.en);
  assert.equal(stringsForLanguage(undefined), translations.en);
});

test("German covers every viewer label including status, capture failures and export", () => {
  assert.deepEqual(Object.keys(translations.de).sort(), Object.keys(translations.en).sort());
  for (const [key, value] of Object.entries(translations.de)) {
    assert.equal(typeof value, "string", key);
    if (key !== "buttonEnd") assert.notEqual(value.trim(), "", key);
  }
  assert.match(translations.de.paused, /Erfassung und Speicherung laufen weiter/);
  assert.match(translations.de.gap, /möglicherweise unvollständig/);
  assert.match(translations.de.exportFailed, /keine vollständige Archivdatei/);
});
