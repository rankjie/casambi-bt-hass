// View state stays independent of HA property updates and transport reconnects.
export const PAGE_SIZE = 250;

export class ViewerModel {
  constructor() {
    this.entryId = "";
    this.storeId = null;
    this.cursor = null;
    this.rows = [];
    this.selected = null;
    this.follow = true;
    this.paused = false;
    this.unread = 0;
    this.hasMore = false;
    this.upper = 0;
    this.filters = {};
    this.generation = 0;
  }

  resetQuery() {
    this.cursor = null;
    this.follow = true;
    this.unread = 0;
    this.hasMore = false;
  }

  applyPage(page) {
    const previous = this.cursor;
    this.cursor = page.scanned_to_sequence;
    this.storeId = page.store_id;
    if (page.phase === "snapshot") {
      this.rows = [...page.events].sort((a, b) => b.sequence - a.sequence);
      this.hasMore = page.has_more;
      this.upper = page.upper_sequence;
      return true;
    }
    const fresh = page.events.filter(row => previous == null || row.sequence > previous);
    if (!this.follow || this.paused) {
      this.unread += fresh.length;
      return false;
    }
    const merged = new Map([...this.rows, ...fresh].map(row => [row.id, row]));
    const rows = [...merged.values()].sort((a, b) => b.sequence - a.sequence);
    this.hasMore ||= rows.length > PAGE_SIZE;
    this.rows = rows.slice(0, PAGE_SIZE);
    this.upper = page.upper_sequence;
    return fresh.length > 0;
  }
}

export function inputText(event, strings) {
  if (event.type !== "input") return event.value;
  const index = event.button_index ?? event.button_event_index ?? event.input_index;
  const button = event.button == null ? `${strings.inputIndex} ${index ?? "—"}` : `${strings.button} ${event.button}${strings.buttonEnd || ""}`;
  return `${button} · ${strings[event.input_action] || strings.inputNotice}`;
}
