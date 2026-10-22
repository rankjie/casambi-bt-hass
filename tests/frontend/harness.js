import "/assets/casambi-events.js";

const storeId="fixture-store", entryId="fixture-network";
const records=[];
const streams=new Map();
let nextSubscription=0;
const panel=document.querySelector("casambi-events-panel");
const makeRecord=sequence=>({id:`${storeId}:${sequence}`,sequence,entry_id:entryId,connection_id:"fixture-session",time:Date.now()+sequence,timestamp:new Date().toISOString(),unit:30,unit_id:30,name:"Fixture Switch",type:"input",value:`ButtonEvent[1] pressed=${sequence%2}`,source:"invocation",source_stream:"button_event",button:1,button_index:1,button_event_index:1,button_label_basis:"four_gang_compatibility",pressed:!!(sequence%2),input_action:sequence%2?"press":"release"});
const initialCount=new URLSearchParams(window.location.search).has("empty")?0:600;
for(let sequence=1;sequence<=initialCount;sequence++) records.push(makeRecord(sequence));
const status=()=>({entry_id:entryId,name:"Synthetic network",address:"11:22:33:44:55:66",gateway_address:"AA:BB:CC:DD:EE:02",state:"connected",storage:"ready",saved:records.length,connection:{gateway_unit:2},receive:{packets:records.length,type7_packets:records.length,invalid_signatures:0,callback_errors:0}});
const matches=(row,filters={})=>(filters.unit==null||row.unit===filters.unit)&&(!filters.event_type||row.type===filters.event_type)&&(!filters.source||row.source===filters.source)&&(!filters.source_stream||row.source_stream===filters.source_stream)&&(!filters.query||JSON.stringify(row).toLowerCase().includes(filters.query.toLowerCase()))&&(filters.start_ms==null||row.time>=filters.start_ms)&&(filters.end_ms==null||row.time<=filters.end_ms);
function query(filters,upper,before,after){
  let rows=records.filter(row=>row.sequence<=upper&&matches(row,filters)&&(before==null||row.sequence<before)&&(after==null||row.sequence>after));
  rows.sort((a,b)=>after==null?b.sequence-a.sequence:a.sequence-b.sequence);
  const has_more=rows.length>250; rows=rows.slice(0,250);
  return {events:rows,has_more,upper_sequence:upper,before_sequence:has_more?rows.at(-1).sequence:null,scanned_to_sequence:after!=null&&has_more?rows.at(-1).sequence:upper};
}
function emit(stream,kind,data={}){
  stream.callback({kind,schema_version:1,store_id:storeId,entry_id:entryId,subscription_id:stream.id,subscription_generation:stream.message.generation,...data});
}
function deliver(stream){
  if(!streams.has(stream.id))return;
  emit(stream,"status",{status:status()});
  if(stream.message.mode==="status_only"||stream.pending)return;
  const upper=records.length;
  if(stream.cursor==null){
    emit(stream,"facets",{units:records.length?[{unit:30,name:"Fixture Switch"}]:[],types:records.length?["input"]:[],gaps:[]});
    const page=query(stream.message.filters,upper);stream.pending=page.scanned_to_sequence;
    emit(stream,"events",{phase:"snapshot",...page});
  }else if(stream.cursor<upper){
    const page=query(stream.message.filters,upper,null,stream.cursor);stream.pending=page.scanned_to_sequence;
    emit(stream,"events",{phase:"live",...page});
  }else emit(stream,"caught_up",{scanned_to_sequence:stream.cursor});
}
class FixtureConnection{
  constructor(){this.listeners=new Map();}
  addEventListener(kind,callback){if(!this.listeners.has(kind))this.listeners.set(kind,new Set());this.listeners.get(kind).add(callback);}
  removeEventListener(kind,callback){this.listeners.get(kind)?.delete(callback);}
  signal(kind){for(const callback of this.listeners.get(kind)||[])callback();}
  async subscribeMessage(callback,message){
    const id=++nextSubscription,stream={id,callback,message,cursor:message.after_sequence,pending:null};
    streams.set(id,stream);setTimeout(()=>deliver(stream),0);
    return async()=>{streams.delete(id);};
  }
}
const connection=new FixtureConnection();
let hass={language:new URLSearchParams(window.location.search).get("language")||"zh-Hans",connected:true,connection,config:{time_zone:"Europe/Amsterdam"},locale:{time_zone:"server"},states:{}};
hass.callWS=async message=>{
  if(message.type==="casambi_bt/events/networks")return {store_id:storeId,networks:[status()]};
  if(message.type==="casambi_bt/events/ack"){
    const stream=streams.get(message.subscription);
    if(stream){stream.cursor=message.sequence;stream.pending=null;setTimeout(()=>deliver(stream),0);}return;
  }
  if(message.type==="casambi_bt/events/query")return query(message.filters,message.upper_sequence??records.length,message.before_sequence);
  if(message.type==="casambi_bt/events/get")return records.find(row=>row.sequence===message.sequence);
  if(message.type==="casambi_bt/events/unit")return {unit:message.unit,status:"ready",device:{id:"fixture-device",name:"Fixture Switch"},entities:[{entity_id:"sensor.fixture_switch_last_event",name:"Last event",disabled:false},{entity_id:"sensor.fixture_switch_config",name:"Configuration",disabled:true}]};
  throw new Error("Unexpected fixture command");
};
hass.callApiRaw=async()=>new Response(JSON.stringify({kind:"manifest"})+"\n"+records.map(event=>JSON.stringify({kind:"event",event})).join("\n")+"\n"+JSON.stringify({kind:"complete",count:records.length})+"\n");
panel.route={prefix:"/casambi-events",path:""};panel.hass=hass;
panel.addEventListener("hass-more-info",event=>document.getElementById("native-action").textContent=`HA more-info: ${event.detail.entityId}`);
window.addEventListener("location-changed",()=>document.getElementById("native-action").textContent=`HA navigation: ${window.location.pathname}`);
document.getElementById("append").onclick=()=>{records.push(makeRecord(records.length+1));for(const stream of streams.values())deliver(stream);};
document.getElementById("burst").onclick=()=>{const first=records.length+1;for(let n=first;n<first+10_000;n++)records.push(makeRecord(n));for(const stream of streams.values())deliver(stream);};
document.getElementById("update").onclick=()=>{hass={...hass,states:{fixture:{state:Math.random()}}};panel.hass=hass;};
document.getElementById("disconnect").onclick=()=>{hass={...hass,connected:false};streams.clear();panel.hass=hass;connection.signal("disconnected");};
document.getElementById("reconnect").onclick=()=>{hass={...hass,connected:true};panel.hass=hass;connection.signal("ready");};
document.getElementById("theme").onclick=()=>document.body.classList.toggle("dark");
document.getElementById("phone").onclick=()=>panel.style.width="390px";
document.getElementById("desktop").onclick=()=>panel.style.width="100%";
