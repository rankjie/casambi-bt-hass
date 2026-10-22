import { inputText } from "./viewer-model.js";

export class EventList {
  constructor(container, {onSelect, onUnit, onRead, formatTime, strings}) {
    Object.assign(this, {container, onSelect, onUnit, onRead, formatTime, strings});
    this.rows = [];
    this.nodes = new Map();
    this.content = document.createElement("div");
    this.content.className = "list-content";
    this.content.setAttribute("role", "rowgroup");
    container.append(this.content);
    this._scroll = () => { if (container.scrollTop > 1) onRead(); this.schedule(); };
    container.addEventListener("scroll", this._scroll, {passive:true});
    this._resize = new ResizeObserver(() => this.schedule());
    this._resize.observe(container);
    this._click = event => {
      const row = event.target.closest("[data-event-id]");
      if (row) {
        const item=this.rows.find(item=>item.id===row.dataset.eventId);
        if (event.target.closest("[data-unit-link]")) onUnit(item);
        else onSelect(item);
      }
    };
    this._key = event => {
      if (event.key === "Enter" || event.key === " ") {
        if (event.target.closest("button,a")) return;
        event.preventDefault(); this._click(event);
      }
    };
    this._focus = () => onRead();
    container.addEventListener("click", this._click);
    container.addEventListener("keydown", this._key);
    container.addEventListener("focusin", this._focus);
  }

  setRows(rows, selectedId) {
    this.rows = rows;
    this.selectedId = selectedId;
    this.container.setAttribute("aria-rowcount", String(rows.length));
    this.render();
  }

  schedule() {
    if (this._frame) return;
    this._frame = requestAnimationFrame(() => { this._frame = null; this.render(); });
  }

  render() {
    const narrow = this.container.clientWidth < 650;
    const height = narrow ? 72 : 56;
    const start = Math.max(0, Math.floor(this.container.scrollTop / height) - 5);
    const end = Math.min(this.rows.length, start + Math.ceil(this.container.clientHeight / height) + 12);
    const visible = new Set();
    let next = this.content.firstElementChild;
    this.content.style.height = `${this.rows.length * height}px`;
    for (let index = start; index < end; index++) {
      const item = this.rows[index];
      visible.add(item.id);
      let node = this.nodes.get(item.id);
      if (!node) {
        node = this.makeRow(item);
        this.nodes.set(item.id, node);
      }
      if (node === next) next = next.nextElementSibling;
      else this.content.insertBefore(node, next);
      node.style.height = `${height}px`;
      node.style.transform = `translateY(${index * height}px)`;
      node.classList.toggle("compact", narrow);
      node.setAttribute("aria-selected", String(item.id === this.selectedId));
      node.setAttribute("aria-rowindex", String(index + 1));
    }
    for (const [id, node] of this.nodes) {
      if (!visible.has(id)) { node.remove(); this.nodes.delete(id); }
    }
  }

  makeRow(event) {
    const node = document.createElement("div");
    node.className = "event-row";
    node.dataset.eventId = event.id;
    node.setAttribute("role", "row");
    node.tabIndex = 0;
    const cell = (className, value, secondary) => {
      const element = document.createElement("div");
      element.className = className;
      element.setAttribute("role", "cell");
      const primary = document.createElement("span"); primary.textContent = value;
      element.append(primary);
      if (secondary) { const small = document.createElement("small"); small.textContent = secondary; element.append(small); }
      node.append(element);
      return element;
    };
    cell("event-time", this.formatTime(event.time));
    const device=cell("event-device", event.name);
    if (event.unit!=null) {
      const secondary=document.createElement("small"),button=document.createElement("button");
      button.type="button";
      button.className="unit-link";
      button.dataset.unitLink="";
      button.textContent=`Unit #${event.unit}`;
      button.setAttribute("aria-label",`${this.strings.haDevice}: Unit #${event.unit}`);
      secondary.append(button); device.append(secondary);
    }
    cell("event-type", this.strings[event.type] || event.type);
    cell("event-value", inputText(event, this.strings));
    const source = event.source_stream === "button_event" ? "ButtonEvent" : event.source_stream === "notify_input" ? "NotifyInput" : event.source === "unit_state" ? this.strings.stateSource : "Type 7";
    cell("event-source", source);
    return node;
  }

  dispose() {
    this._resize.disconnect();
    if (this._frame) cancelAnimationFrame(this._frame);
    this.container.removeEventListener("scroll", this._scroll);
    this.container.removeEventListener("click", this._click);
    this.container.removeEventListener("keydown", this._key);
    this.container.removeEventListener("focusin", this._focus);
  }
}
