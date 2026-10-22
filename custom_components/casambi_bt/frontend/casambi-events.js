import { EventList } from "./event-list.js";
import { ViewerModel, inputText } from "./viewer-model.js";
import { stringsForLanguage } from "./translations.js";

const CSS = `
:host{display:block;height:100dvh;color:var(--primary-text-color);background:var(--primary-background-color);font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif);container-type:inline-size}
*{box-sizing:border-box}button,input,select{font:inherit;color:inherit;background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:8px;padding:9px 12px;min-height:40px}button{cursor:pointer}button:hover{background:var(--secondary-background-color)}button:disabled{opacity:.45;cursor:default}:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}[hidden]{display:none!important}
.shell{height:100%;display:flex;flex-direction:column;padding:16px 24px;gap:12px}header,.actions,.counts,.pager{display:flex;align-items:center;gap:10px}header{flex-wrap:wrap}h1{font-size:22px;font-weight:500;margin:0 12px 0 0}.actions{margin-left:auto}#network{max-width:260px}.menu{border:0;background:none;font-size:22px;padding:4px 10px}#status{font-size:13px;color:var(--secondary-text-color);line-height:1.7}#error,#gap{padding:10px 12px;border-left:3px solid var(--error-color);font-size:13px;background:var(--card-background-color)}#error button{margin-left:12px}.filters{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.filters input[type=search]{flex:1;min-width:180px}.filters select{max-width:180px}.range{display:none;gap:8px;flex-wrap:wrap}.filters-open .range{display:flex}.range label{font-size:12px;color:var(--secondary-text-color);display:flex;gap:7px;align-items:center}.range input{font-size:12px;min-height:34px;padding:5px}.counts{font-size:13px;color:var(--secondary-text-color);flex-wrap:wrap}.counts strong{font-weight:500;color:var(--primary-text-color);font-variant-numeric:tabular-nums}.counts #latest{margin-left:auto;color:var(--primary-color)}#notice{color:var(--primary-color);font-size:13px}.workspace{display:grid;grid-template-columns:minmax(0,1fr) 360px;flex:1;min-height:0;background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:10px;overflow:hidden}.table-pane{display:flex;flex-direction:column;min-height:0;min-width:0}.table-header,.event-row{display:grid;grid-template-columns:112px minmax(120px,1fr) 90px minmax(140px,1.3fr) 105px;gap:10px;align-items:center;padding:0 14px}.table-header{height:40px;flex-shrink:0;font-size:12px;color:var(--secondary-text-color);border-bottom:1px solid var(--divider-color)}#list{overflow:auto;flex:1;min-height:150px;position:relative;overflow-anchor:none}.list-content{position:relative}.event-row{position:absolute;top:0;left:0;right:0;width:100%;border-bottom:1px solid var(--divider-color);cursor:pointer;font-size:13px;contain:layout paint}.event-row:hover,.event-row[aria-selected=true]{background:var(--secondary-background-color)}.event-row[aria-selected=true]{box-shadow:inset 3px 0 var(--primary-color)}.event-row>div{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.event-row small{display:block;color:var(--secondary-text-color);font-size:11px;margin-top:3px}.event-time{font-size:12px;font-variant-numeric:tabular-nums}.event-source,.event-type{color:var(--secondary-text-color);font-size:12px}.event-value{font-variant-numeric:tabular-nums}#empty{padding:40px 20px;text-align:center;color:var(--secondary-text-color);font-size:14px}.pager{padding:8px 12px;border-top:1px solid var(--divider-color);justify-content:flex-end}.pager button{min-height:32px;padding:5px 12px}aside{border-left:1px solid var(--divider-color);overflow:auto;padding:16px;min-width:0}aside h2{font-size:16px;margin:0 0 8px;font-weight:500}#detail-placeholder{font-size:14px;color:var(--secondary-text-color)}#detail-description{font-size:14px;line-height:1.7;margin:0 0 12px}#detail-back{margin-bottom:12px}dl{display:grid;grid-template-columns:minmax(100px,auto) minmax(0,1fr);gap:8px 12px;font-size:12px}dt{color:var(--secondary-text-color)}dd{margin:0;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}pre{font:12px/1.5 ui-monospace,SFMono-Regular,monospace;white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer;font-size:13px}details{font-size:12px;color:var(--secondary-text-color)}#label-basis{font-size:12px;line-height:1.6;color:var(--secondary-text-color)}#receive-values{display:flex;gap:6px 22px;flex-wrap:wrap;padding-top:7px}#receive-values span{white-space:nowrap}#diagnostics{flex-shrink:0}#copy{margin-top:12px;font-size:12px}
.event-row.compact{grid-template-columns:minmax(0,1fr) auto;grid-template-rows:1fr 1fr;gap:2px 8px;padding:10px 12px}.compact .event-device{grid-column:1;grid-row:1}.compact .event-time{grid-column:2;grid-row:1;align-self:start}.compact .event-value{grid-column:1;grid-row:2}.compact .event-source{grid-column:2;grid-row:2}.compact .event-type{display:none}.compact small{display:inline;margin-left:6px}.table-pane.narrow .table-header{display:none}
.unit-link{border:0!important;background:none!important;color:var(--primary-color);text-decoration:underline;padding:0;min-height:24px;font:inherit;line-height:1.4}.ha-links{margin:0 0 16px;font-size:12px;overflow-wrap:anywhere}.ha-links a{color:var(--primary-color)}.ha-links p{color:var(--secondary-text-color);line-height:1.6}.entity-link{display:block;width:100%;text-align:left;margin-top:7px;font-size:12px}.entity-link small{display:block;color:var(--secondary-text-color);margin-top:3px;overflow-wrap:anywhere}
@container(max-width:1100px){.workspace{grid-template-columns:minmax(0,1fr)}aside{display:none}.shell.inspected .table-pane{display:none}.shell.inspected aside{display:block;border-left:0}#detail-back{display:inline-block}.table-header{display:none}}
@container(min-width:1101px){#detail-back{display:none}}
@container(max-width:650px){.shell{padding:10px;gap:9px}h1{font-size:20px}.actions{margin-left:0}.range{width:100%}.range label{flex:1;min-width:0}.range input{width:100%;min-width:0}.filters select{max-width:45%;flex:1}.filters input[type=search]{width:auto;min-width:0;flex:1;flex-basis:auto}.filters select,.filters #reset{display:none}.filters-open .filters select,.filters-open .filters #reset{display:block}#network{max-width:calc(100% - 70px)}.actions button{min-height:34px;padding:5px 10px;font-size:12px}.counts{gap:7px;font-size:12px}.workspace{min-height:180px}#status{font-size:12px}#diagnostics{font-size:12px}}
`;

class CasambiEventsPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:"open"});
    this.model = new ViewerModel();
    this._status = null;
    this._pages = [];
    this._networkEpoch = 0;
    this._boundReady = () => this._loadNetworks();
    this._boundLost = () => this._renderStatus();
    this._visibility = () => { if (!document.hidden && this._errorCode === "ack_timeout") this._subscribe(); };
  }

  set hass(value) {
    const previous = this._hass;
    this._hass = value;
    this.s = stringsForLanguage(value.language);
    if (!this.isConnected) return;
    this._mount();
    if (this._connection !== value.connection) {
      this._detachConnection();
      this._connection = value.connection;
      this._connection.addEventListener("ready", this._boundReady);
      this._connection.addEventListener("disconnected", this._boundLost);
      if (value.connected) this._loadNetworks();
    } else if (!previous?.connected && value.connected) {
      this._loadNetworks();
    }
    this._renderStatus();
  }

  set panel(value) { this._panel = value; }
  set narrow(value) { this._narrow = value; }
  set route(value) { this._route = value; }

  connectedCallback() {
    document.addEventListener("visibilitychange", this._visibility);
    if (this._hass) { const hass = this._hass; this._hass = null; this.hass = hass; }
  }

  disconnectedCallback() {
    document.removeEventListener("visibilitychange", this._visibility);
    clearTimeout(this._searchTimer);
    this.model.generation++;
    this._stopStream();
    this._detachConnection();
    this._list?.dispose();
    this._list?.content.remove();
    this._list = null;
  }

  _detachConnection() {
    this._connection?.removeEventListener("ready", this._boundReady);
    this._connection?.removeEventListener("disconnected", this._boundLost);
    this._connection = null;
  }

  $(id) { return this.shadowRoot.getElementById(id); }

  _mount() {
    if (!this.$("shell")) {
      this.shadowRoot.innerHTML = `<style>${CSS}</style><main class="shell" id="shell">
        <header><button class="menu" id="menu" aria-label="${this.s.menu}">☰</button><h1>${this.s.title}</h1><select id="network" aria-label="${this.s.network}"></select><div class="actions"><button id="pause">${this.s.pause}</button><button id="export">${this.s.export}</button></div></header>
        <div id="status" role="status"></div><div id="error" role="alert" hidden><span id="error-text"></span><button id="retry">${this.s.retry}</button></div><div id="gap" hidden>${this.s.gap}</div>
        <div class="filters"><input id="search" type="search" placeholder="${this.s.search}" aria-label="${this.s.search}"><button id="filter-toggle" aria-expanded="false">${this.s.filters}</button><select id="device" aria-label="${this.s.device}"></select><select id="type" aria-label="${this.s.type}"></select><select id="source" aria-label="${this.s.source}"><option value="">${this.s.source}</option><option value="unit_state">${this.s.stateSource}</option><option value="button_event">ButtonEvent</option><option value="notify_input">NotifyInput</option><option value="invocation">${this.s.protocolSource}</option></select><button id="reset">${this.s.reset}</button></div>
        <div class="range"><label>${this.s.from}<input id="from" type="datetime-local"></label><label>${this.s.to}<input id="to" type="datetime-local"></label><span id="timezone"></span></div>
        <div class="counts"><span>${this.s.saved} <strong id="saved">—</strong></span><span>· ${this.s.loaded} <strong id="loaded">0</strong></span><button id="latest" hidden></button><button id="from-now">${this.s.fromNow}</button></div><div id="notice" role="status" aria-live="polite"></div>
        <div class="workspace"><section class="table-pane"><div class="table-header" role="row"><span>${this.s.time}</span><span>${this.s.deviceHeading}</span><span>${this.s.event}</span><span>${this.s.value}</span><span>${this.s.sourceHeading}</span></div><div id="list" role="table" aria-label="${this.s.title}"></div><div id="empty" hidden></div><div class="pager"><button id="newer">${this.s.newer}</button><button id="older">${this.s.earlier}</button></div></section><aside aria-label="${this.s.details}"><p id="detail-placeholder">${this.s.selectEvent}</p><div id="detail" hidden><button id="detail-back">${this.s.back}</button><h2 id="detail-title"></h2><p id="detail-description"></p><section id="ha-links" class="ha-links" aria-label="Home Assistant" hidden></section><dl id="detail-fields"></dl><p id="label-basis" hidden></p><details id="detail-json"><summary>${this.s.json}</summary><pre id="json"></pre></details><button id="copy">${this.s.copy}</button></div></aside></div>
        <details id="diagnostics"><summary>${this.s.diagnostics}</summary><div id="receive-values"></div></details></main>`;
      this.$("menu").onclick = () => this.dispatchEvent(new CustomEvent("hass-toggle-menu", {bubbles:true, composed:true}));
      this.$("network").onchange = () => this._selectNetwork(this.$("network").value);
      this.$("filter-toggle").onclick = () => { const opened=this.$("shell").classList.toggle("filters-open"); this.$("filter-toggle").setAttribute("aria-expanded",String(opened)); };
      this.$("search").oninput = () => { clearTimeout(this._searchTimer); this._searchTimer = setTimeout(() => this._filter(), 200); };
      for (const id of ["device", "type", "source", "from", "to"]) this.$(id).onchange = () => this._filter();
      this.$("reset").onclick = () => { for (const id of ["search","device","type","source","from","to"]) this.$(id).value=""; this._filter(); };
      this.$("pause").onclick = () => { this.model.paused = !this.model.paused; this._subscribe(); this._renderCounts(); };
      this.$("latest").onclick = () => this._latest();
      this.$("from-now").onclick = () => this._fromNow();
      this.$("older").onclick = () => this._history(true);
      this.$("newer").onclick = () => this._history(false);
      this.$("retry").onclick = () => {
        if (this._errorCode === "store_reset" || this._errorCode === "invalid_cursor") { this.model.storeId=this._currentStoreId; this.model.resetQuery(); }
        this._subscribe();
      };
      this.$("detail-back").onclick = () => this._closeDetails();
      this.$("copy").onclick = async () => {
        try { await navigator.clipboard.writeText(JSON.stringify(this.model.selected,null,2)); this.$("copy").textContent=this.s.copied; }
        catch { this._showError("clipboard_failed"); }
      };
      this.$("export").onclick = () => this._export();
      this.$("shell").addEventListener("keydown", event => {
        if (event.key === "Escape") this._closeDetails();
        if (event.key === "/" && !["INPUT","SELECT","TEXTAREA"].includes(event.target.tagName)) { event.preventDefault(); this.$("search").focus(); }
      });
      this.$("timezone").textContent=Intl.DateTimeFormat().resolvedOptions().timeZone;
      this._setOptions("device", this.s.device, []);
      this._setOptions("type", this.s.type, []);
    }
    if (!this._list) this._list = new EventList(this.$("list"), {
      strings:this.s, formatTime:time => this._formatTime(time),
      onSelect:event => this._inspect(event),
      onUnit:event => this._inspect(event,true),
      onRead:() => { this.model.follow=false; this._renderCounts(); }
    });
  }

  _formatTime(time) {
    const timeZone = this._hass.locale?.time_zone === "local" ? undefined : this._hass.config?.time_zone;
    return new Intl.DateTimeFormat(this._hass.language, {hour:"2-digit", minute:"2-digit", second:"2-digit", fractionalSecondDigits:3, timeZone}).format(time);
  }

  async _loadNetworks() {
    if (!this.isConnected || !this._hass?.connected) return;
    const epoch=++this._networkEpoch;
    try {
      const result=await this._hass.callWS({type:"casambi_bt/events/networks"});
      if (epoch !== this._networkEpoch || !this.isConnected) return;
      this._currentStoreId=result.store_id;
      this._networks=result.networks;
      const selected=this.model.entryId;
      this.$("network").replaceChildren();
      for (const network of result.networks) this.$("network").add(new Option(network.name,network.entry_id));
      if (!result.networks.length) { this.$("empty").hidden=false; this.$("empty").textContent=this.s.noNetwork; return; }
      const routeParts=(this._route?.path || "").split("/").filter(Boolean).map(decodeURIComponent);
      const entryId=result.networks.some(network=>network.entry_id===selected) ? selected : result.networks.some(network=>network.entry_id===routeParts[0]) ? routeParts[0] : result.networks[0].entry_id;
      if (this.model.storeId && this.model.storeId!==result.store_id) { this._showError("store_reset"); return; }
      this.model.storeId=result.store_id;
      this.model.entryId=entryId;
      this.$("network").value=entryId;
      this._status=result.networks.find(network=>network.entry_id===entryId);
      await this._subscribe();
      if (routeParts[1]===result.store_id && routeParts[2] && !this.model.selected) {
        const event=await this._hass.callWS({type:"casambi_bt/events/get",entry_id:entryId,store_id:result.store_id,sequence:Number(routeParts[2])});
        if (this.model.entryId===entryId) this._inspect(event);
      }
    } catch { if (epoch===this._networkEpoch) this._showError("archive_read_failed"); }
  }

  async _selectNetwork(entryId) {
    this.model.entryId=entryId;
    this.model.selected=null;
    this.model.paused=false;
    this._closeDetails();
    this.model.resetQuery();
    this._pages=[];
    this._historyBefore=null;
    this._status=this._networks.find(network=>network.entry_id===entryId);
    this.$("device").value="";
    delete this.model.filters.unit;
    this._routeTo();
    await this._subscribe();
  }

  async _stopStream() {
    const unsubscribe=this._unsubscribe;
    this._unsubscribe=null;
    if (unsubscribe) {
      try { await unsubscribe(); }
      catch (error) { if (this._hass?.connected && error?.code!=="not_found") this._showError("streamError"); }
    }
  }

  async _subscribe() {
    if (!this._hass?.connected || !this.model.entryId || !this.isConnected) return;
    const generation=++this.model.generation;
    await this._stopStream();
    this._errorCode=null;
    this.$("error").hidden=true;
    const message={type:"casambi_bt/events/subscribe",entry_id:this.model.entryId,store_id:this.model.storeId,generation,filters:this.model.filters,mode:this.model.paused?"status_only":"events"};
    if (this.model.cursor!=null) message.after_sequence=this.model.cursor;
    try {
      const unsubscribe=await this._hass.connection.subscribeMessage(data=>this._message(data,generation),message,{resubscribe:false});
      if (generation!==this.model.generation || !this.isConnected) await unsubscribe();
      else this._unsubscribe=unsubscribe;
    } catch { if (generation===this.model.generation) this._showError("streamError"); }
  }

  _message(data,generation) {
    if (generation!==this.model.generation || data.subscription_generation!==generation) return;
    if (data.kind==="status") { this._status=data.status; this._renderStatus(); }
    else if (data.kind==="facets") {
      this._setOptions("device",this.s.device,data.units.map(unit=>[String(unit.unit),`${unit.name} · Unit #${unit.unit}`]));
      this._setOptions("type",this.s.type,data.types.map(type=>[type,this.s[type]||type]));
      this.$("gap").hidden=!data.gaps.length;
    } else if (data.kind==="events") {
      for (const event of data.events) {
        if (event.unit!=null && ![...this.$("device").options].some(option=>option.value===String(event.unit))) {
          this.$("device").add(new Option(`${event.name} · Unit #${event.unit}`,String(event.unit)));
        }
        if (![...this.$("type").options].some(option=>option.value===event.type)) {
          this.$("type").add(new Option(this.s[event.type]||event.type,event.type));
        }
      }
      this._catchingUp=data.phase==="catch_up";
      if (this.model.applyPage(data)) this._renderRows();
      this._renderCounts();
      this._hass.callWS({type:"casambi_bt/events/ack",subscription:data.subscription_id,generation,sequence:data.scanned_to_sequence}).catch(()=>{ if (generation===this.model.generation) this._showError("streamError"); });
    } else if (data.kind==="caught_up") { this._catchingUp=false; this._renderCounts(); }
    else if (data.kind==="error") this._showError(data.code);
  }

  _setOptions(id,label,options) {
    const select=this.$(id), current=select.value;
    select.replaceChildren(new Option(label,""));
    for (const [value,text] of options) select.add(new Option(text,value));
    if ([...select.options].some(option=>option.value===current)) select.value=current;
  }

  async _filter() {
    const filters={};
    if (this.$("search").value.trim()) filters.query=this.$("search").value.trim();
    if (this.$("device").value) filters.unit=Number(this.$("device").value);
    if (this.$("type").value) filters.event_type=this.$("type").value;
    const source=this.$("source").value;
    if (source==="unit_state") filters.source="unit_state";
    else if (source) { filters.source="invocation"; filters.source_stream=source; }
    for (const [id,key] of [["from","start_ms"],["to","end_ms"]]) if(this.$(id).value) filters[key]=new Date(this.$(id).value).getTime();
    if (filters.start_ms!=null && filters.end_ms!=null && filters.end_ms<filters.start_ms) { this._showError("rangeError"); return; }
    this.model.filters=filters;
    const count=["search","device","type","source","from","to"].filter(id=>this.$(id).value.trim()).length;
    this.$("filter-toggle").textContent=this.s.filters+(count?` (${count})`:"");
    const pausedUpper=this.model.cursor??this.model.upper;
    const generation=++this.model.generation;
    this.model.resetQuery();
    this._pages=[];
    this._historyBefore=null;
    this.$("list").scrollTop=0;
    if (this.model.paused) {
      await this._stopStream();
      try {
        const page=await this._hass.callWS({type:"casambi_bt/events/query",entry_id:this.model.entryId,store_id:this.model.storeId,filters,upper_sequence:pausedUpper});
        if (generation!==this.model.generation) return;
        this.model.rows=page.events; this.model.hasMore=page.has_more;
        this.model.cursor=pausedUpper; this.model.upper=pausedUpper;
        this._renderRows(); this._renderCounts();
      } catch { this._showError("archive_read_failed"); return; }
    }
    this._subscribe();
  }

  _latest() {
    this.model.resetQuery();
    this.model.paused=false;
    this._pages=[];
    this._historyBefore=null;
    this.$("list").scrollTop=0;
    this._subscribe();
  }

  async _fromNow() {
    const generation=++this.model.generation;
    await this._stopStream();
    try {
      const page=await this._hass.callWS({type:"casambi_bt/events/query",entry_id:this.model.entryId,store_id:this.model.storeId,filters:this.model.filters});
      if (generation!==this.model.generation) return;
      this.model.cursor=page.upper_sequence; this.model.upper=page.upper_sequence;
      this.model.rows=[]; this.model.follow=true; this.model.paused=false; this.model.unread=0;
      this.model.hasMore=false; this._pages=[]; this._historyBefore=null;
      this.$("list").scrollTop=0; this._renderRows(); this._renderCounts();
      this._subscribe();
    } catch { this._showError("archive_read_failed"); }
  }

  async _history(older) {
    if (!this.model.rows.length || this._historyRequest?.generation===this.model.generation) return;
    this.model.follow=false;
    const generation=this.model.generation;
    const previous={before_sequence:this._historyBefore,upper_sequence:this.model.upper,scrollTop:this.$("list").scrollTop};
    const target=older?{before_sequence:this.model.rows.at(-1).sequence,upper_sequence:this.model.upper,scrollTop:0}:this._pages.at(-1);
    if (!target) return;
    const request={generation};
    this._historyRequest=request;
    this._renderCounts();
    this.$("notice").textContent=this.s.loadingHistory;
    try {
      const message={type:"casambi_bt/events/query",entry_id:this.model.entryId,store_id:this.model.storeId,filters:this.model.filters,upper_sequence:target.upper_sequence};
      if (target.before_sequence!=null) message.before_sequence=target.before_sequence;
      const page=await this._hass.callWS(message);
      if (generation!==this.model.generation) return;
      if (older) this._pages.push(previous);
      else this._pages.pop();
      this._historyBefore=target.before_sequence;
      this.model.rows=page.events;
      this.model.hasMore=page.has_more;
      this._renderRows();
      this.$("list").scrollTop=target.scrollTop;
      this._renderCounts();
    } catch { if (generation===this.model.generation) this._showError("archive_read_failed"); }
    finally {
      if (this._historyRequest===request) this._historyRequest=null;
      this._renderCounts();
    }
  }

  _renderRows() {
    this._list?.setRows(this.model.rows,this.model.selected?.id);
    this.$("empty").hidden=!!this.model.rows.length;
    if (!this.model.rows.length) this.$("empty").textContent=Object.keys(this.model.filters).length?this.s.noMatches:this.s.waiting;
  }

  _renderCounts() {
    if (!this.$("shell")) return;
    this.$("saved").textContent=this._status?.saved?.toLocaleString(this._hass.language)??"—";
    this.$("loaded").textContent=this.model.rows.length.toLocaleString(this._hass.language);
    this.$("pause").textContent=this.model.paused?this.s.resume:this.s.pause;
    this.$("pause").setAttribute("aria-pressed",String(this.model.paused));
    this.$("latest").hidden=this.model.follow && !this.model.unread;
    this.$("latest").textContent=this.model.unread?`${this.s.newEvents} (${this.model.unread.toLocaleString()})` : this.s.latest;
    const loading=this._historyRequest?.generation===this.model.generation;
    this.$("older").disabled=loading || !this.model.hasMore;
    this.$("newer").disabled=loading || !this._pages.length;
    this.$("notice").textContent=this.model.paused?this.s.paused:this._catchingUp?this.s.catchingUp:"";
  }

  _renderStatus() {
    if (!this.$("shell")) return;
    const status=this._status;
    const parts=[`${this.s.ha}: ${this._hass?.connected?this.s.connected:this.s.disconnected}`];
    if (status) {
      this.$("gap").hidden=!status.has_gaps;
      parts.push(`${this.s.bluetooth}: ${this.s[status.state]||status.state}`);
      const unit=status.state==="connected"?status.connection?.gateway_unit:null;
      if (unit!=null || status.gateway_address) parts.push(`${this.s.gateway}: ${unit!=null?`#${unit}`:status.gateway_address}`);
      parts.push(`${this.s.storage}: ${status.storage==="ready"?this.s.ready:status.storage_error}`);
      if (status.storage!=="ready") this.$("status").style.color="var(--error-color)";
      else this.$("status").style.color="";
    }
    this.$("status").textContent=parts.join(" · ");
    const rx=status?.receive||{};
    this.$("receive-values").replaceChildren();
    for (const key of ["packets","type7_packets","invalid_signatures","callback_errors","legacy_emitted","legacy_copies","legacy_paired","last_sequence"]) {
      const span=document.createElement("span"); span.textContent=`${this.s[key]}: ${rx[key]??"—"}`; this.$("receive-values").append(span);
    }
    this._renderCounts();
  }

  _inspect(event,openDevice=false) {
    if (!event) return;
    this._detailScroll=this.$("list").scrollTop;
    this.model.follow=false;
    this.model.selected=event;
    this.$("shell").classList.add("inspected");
    this.$("detail-placeholder").hidden=true;
    this.$("detail").hidden=false;
    this.$("detail-title").textContent=`${event.name}${event.unit==null?"":` · Unit #${event.unit}`}`;
    this.$("detail-description").textContent=inputText(event,this.s);
    const fields=this.$("detail-fields"); fields.replaceChildren();
    const keys=["timestamp","source","source_stream","unit_id","button","button_index","input_action","control","numeric_value","opcode","opcode_name","origin_unit_id","origin_counter","origin_handle","target","target_type","age","lifetime","invocation_flags","packet_sequence","arrival_sequence","interpreted_payload_hex","connection_id"];
    for (const key of keys) if (key in event) {
      const dt=document.createElement("dt"),dd=document.createElement("dd"); dt.textContent=key; dd.textContent=event[key]===null?"null":String(event[key]); fields.append(dt,dd);
    }
    this.$("label-basis").hidden=!event.button_label_basis;
    this.$("label-basis").textContent=this.s.labelBasis;
    this.$("json").textContent=JSON.stringify(event,null,2);
    this.$("copy").textContent=this.s.copy;
    this._renderRows(); this._renderCounts(); this._routeTo(event);
    this._loadUnitLinks(event,openDevice);
  }

  async _loadUnitLinks(event,openDevice) {
    const request=Symbol(); this._unitLookup=request;
    const container=this.$("ha-links");
    container.replaceChildren(); container.hidden=event.unit==null;
    if (event.unit==null) return;
    container.textContent=this.s.haLinksLoading;
    try {
      const links=await this._hass.callWS({type:"casambi_bt/events/unit",entry_id:event.entry_id,unit:event.unit});
      if (!this.isConnected || this._unitLookup!==request) return;
      container.replaceChildren();
      if (!links.device) {
        container.textContent=links.status==="unloaded"?this.s.haNetworkUnloaded:this.s.haDeviceMissing;
        return;
      }
      const device=document.createElement("a");
      device.href=`/config/devices/device/${encodeURIComponent(links.device.id)}`;
      device.textContent=`${this.s.haDevice}: ${links.device.name}`;
      device.onclick=click=>{
        if (click.button || click.metaKey || click.ctrlKey || click.shiftKey || click.altKey) return;
        click.preventDefault(); this._navigateDevice(links.device.id);
      };
      container.append(device);
      for (const entity of links.entities) {
        const button=document.createElement("button"),id=document.createElement("small");
        button.type="button"; button.className="entity-link"; button.disabled=entity.disabled;
        button.textContent=this._hass.states?.[entity.entity_id]?.attributes?.friendly_name||entity.name;
        id.textContent=entity.entity_id+(entity.disabled?` · ${this.s.haEntityDisabled}`:"");
        button.append(id);
        button.onclick=()=>this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:entity.entity_id},bubbles:true,composed:true}));
        container.append(button);
      }
      if (openDevice) this._navigateDevice(links.device.id);
    } catch {
      if (this._unitLookup===request && this.isConnected) container.textContent=this.s.haLinksFailed;
    }
  }

  _navigateDevice(deviceId) {
    window.history.pushState(null,"",`/config/devices/device/${encodeURIComponent(deviceId)}`);
    window.dispatchEvent(new CustomEvent("location-changed",{detail:{replace:false}}));
  }

  _closeDetails() {
    this.model.selected=null;
    this._unitLookup=null;
    this.$("shell")?.classList.remove("inspected");
    if (this.$("detail")) { this.$("detail").hidden=true; this.$("detail-placeholder").hidden=false; }
    if (this._list) { this._renderRows(); this.$("list").scrollTop=this._detailScroll||0; }
    this._routeTo();
  }

  _routeTo(event) {
    const prefix=this._route?.prefix||"/casambi-events";
    const path=`${prefix}/${encodeURIComponent(this.model.entryId)}${event?`/${encodeURIComponent(this.model.storeId)}/${event.sequence}`:""}`;
    if (window.location.pathname.startsWith(prefix)) window.history.replaceState(null,"",path);
  }

  _showError(code) {
    if (!this.$("error")) return;
    this._errorCode=code;
    this.$("error").hidden=false;
    this.$("error-text").textContent=this.s[code]||`${this.s.streamError} (${code})`;
  }

  async _export() {
    const button=this.$("export"); button.disabled=true; button.textContent=this.s.exportBusy;
    try {
      const response=await this._hass.callApiRaw("POST","casambi_bt/events/export",{entry_id:this.model.entryId,store_id:this.model.storeId,filters:this.model.filters});
      if (!response.ok) throw new Error("export_http_failed");
      const blob=await response.blob();
      const tail=await blob.slice(-65536).text();
      if (JSON.parse(tail.trimEnd().split("\n").at(-1)).kind!=="complete") throw new Error("incomplete_export");
      const url=URL.createObjectURL(blob),link=document.createElement("a"); link.href=url; link.download="casambi-events.jsonl"; link.click();
      setTimeout(()=>URL.revokeObjectURL(url),60000);
    } catch { this._showError("exportFailed"); }
    finally { button.disabled=false; button.textContent=this.s.export; }
  }
}

customElements.define("casambi-events-panel",CasambiEventsPanel);
