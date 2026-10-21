const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const elements = new Map(), listeners = {}, intervals = [], requests = [];
function element(selector) {
  if (!elements.has(selector)) elements.set(selector, {
    dataset: {}, classList: {add(){}, remove(){}, toggle(){}},
    addEventListener(name, callback){this[name] = callback},
    closest(){return null}, textContent: '',
    setAttribute(name,value){this[name]=value},
    getAttribute(name){return this[name]},
  });
  return elements.get(selector);
}
const buttons = ['forward','backward','left','right'].map(direction => {
  const button = element(direction); button.dataset.dir = direction; return button;
});
const tabs=['drive','camera'].map((name,index)=>{
  const tab=element('tab-'+name);
  tab['aria-controls']='page-'+name;
  tab['aria-selected']=String(index===0);
  element('#page-'+name).hidden=index!==0;
  return tab;
});
let vehicle = {enabled:false,direction:'stop',speed_percent:0,steering_degrees:0,
  speed_step:5,steering_step:5,steering_max:45,wheel_pwm:{A:0,B:0,C:0,D:0}};
const context = vm.createContext({
  console, Date, setTimeout(){},
  setInterval(fn,ms){intervals.push({fn,ms})},
  addEventListener(name,fn){listeners[name]=fn},
  document:{hidden:false,querySelector:s=>s==='[role=tab]:focus'?null:element(s),
    getElementById:id=>element('#'+id),
    querySelectorAll(selector){return selector==='[data-dir]'?buttons:selector==='[data-page]'?tabs:[]},
    addEventListener(name,fn){listeners[name]=fn}},
  async fetch(path, options){
    if(path==='/api/status') return {json:async()=>({vehicle,
      camera:{recording:false,file:null}})};
    const body=JSON.parse(options.body); requests.push({path,body});
    if(path.endsWith('/enable')) vehicle={...vehicle,enabled:body.enabled,
      direction:body.enabled?'forward':'stop',speed_percent:body.enabled?50:0};
    if(path.endsWith('/drive')) {
      if(body.direction==='stop') vehicle={...vehicle,direction:'stop',speed_percent:0,steering_degrees:0};
      if(body.direction==='forward') vehicle={...vehicle,direction:'forward',speed_percent:vehicle.speed_percent+5};
      if(body.direction==='backward') vehicle={...vehicle,speed_percent:Math.max(0,vehicle.speed_percent-5)};
      if(body.direction==='left') vehicle={...vehicle,direction:'left',steering_degrees:vehicle.steering_degrees-5};
    }
    return {ok:true,json:async()=>({...vehicle})};
  },
});
async function flush(){await new Promise(resolve=>setImmediate(resolve))}
function key(key,repeat=false,code=''){listeners.keydown({key,repeat,code,
  preventDefault(){},target:element('body')})}
(async()=>{
  vm.runInContext(fs.readFileSync('web/app.js','utf8'),context);
  await flush();
  element('#enable').onchange({target:{checked:true}}); await flush();
  assert.equal(vehicle.speed_percent,50);
  key('f'); key('f',true); await flush();
  assert.equal(vehicle.speed_percent,55,'held key must not repeatedly accelerate');
  key('B'); await flush(); assert.equal(vehicle.speed_percent,50);
  buttons[2].click(); buttons[2].click(); await flush();
  assert.equal(vehicle.steering_degrees,-10);
  assert.match(element('#turnValue').textContent,/10°/);
  assert.equal(listeners.keyup,undefined,'release must preserve speed and steering');
  const heartbeat=intervals.find(item=>item.ms===200).fn;
  await heartbeat(); await heartbeat();
  assert.equal(vehicle.speed_percent,50);
  assert.equal(requests.filter(r=>r.path.endsWith('/heartbeat')).length,2);
  const beforeTab=requests.length;
  tabs[1].onclick(); await flush();
  assert.equal(requests.length,beforeTab,'switching camera page must not stop the vehicle');
  assert.equal(vehicle.speed_percent,50);
  await heartbeat();
  assert.equal(requests.at(-1).path,'/api/vehicle/heartbeat','heartbeat continues on camera page');
  key('f'); await flush(); assert.equal(vehicle.speed_percent,50,'camera page does not accept drive shortcuts');
  key(' ',false,'Space'); await flush();
  assert.equal(vehicle.speed_percent,0);
  const count=requests.length; await heartbeat(); assert.equal(requests.length,count);
  // STOP must send a command even when no direction key is held.
  element('#stop').onclick(); await flush();
  assert.equal(requests.at(-1).body.direction,'stop');
  tabs[0].onclick();
  key('f'); await flush(); assert.equal(vehicle.speed_percent,5);
  listeners.blur(); await flush(); assert.equal(vehicle.speed_percent,0);
  console.log('Manual UI: incremental keys, clicks, telemetry, heartbeat and STOP passed');
})().catch(error=>{console.error(error);process.exitCode=1});
