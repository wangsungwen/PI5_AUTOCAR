const $=s=>document.querySelector(s), state={recording:false,keepAlive:false,detectionEnabled:false};
async function api(path,body={}){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'操作失敗');return d}
function showError(e){$('#message').textContent=e.message;setTimeout(()=>$('#message').textContent='',3000)}
function render(s){$('#connection').textContent='連線';$('#connection').classList.remove('bad');renderVehicle(s.vehicle);$('#camera').textContent=s.camera.recording?'錄影中':'待機';$('#enable').checked=s.vehicle.enabled;state.recording=s.camera.recording;$('#record').textContent=s.camera.recording?'■ 停止錄影':'● 開始錄影';$('#record').classList.toggle('active',s.camera.recording);$('#file').textContent=s.camera.file||'尚未建立錄影';if(s.detection){const wasEnabled=state.detectionEnabled,nextEnabled=Boolean(s.detection.enabled);state.detectionEnabled=nextEnabled;$('#detection').checked=nextEnabled;$('#previewMode').textContent=nextEnabled?`YOLO26 NCNN 推論畫框 · ${s.detection.imgsz}×${s.detection.imgsz}`:'原始畫面 · 推論已關閉';$('#detectionFps').textContent=nextEnabled?`${s.detection.fps.toFixed(1)} FPS`:'已關閉';$('#detectionCount').textContent=nextEnabled?s.detection.count:'—';$('#detectionLabels').textContent=s.detection.error||(!nextEnabled?'顯示原始畫面':s.detection.labels||'無物件');renderProfiles(s.detection);if(s.detection.error)$('#previewState').textContent='推論錯誤';if(wasEnabled&&!nextEnabled)reloadPreview()}if(s.gimbal)$('#gimbalPosition').textContent=`水平 ${s.gimbal.pan}° · 俯仰 ${s.gimbal.tilt}°${s.gimbal.backend==='mock'?'（模擬）':''}`;if(s.autopilot){$('#autopilot').checked=s.autopilot.enabled;$('#traffic').textContent=s.autopilot.traffic;$('#laneConfidence').textContent=`${Math.round(s.autopilot.lane_confidence*100)}%`;$('#steering').textContent=s.autopilot.steering.toFixed(3);$('#autoFps').textContent=s.autopilot.fps.toFixed(1);$('#autoError').textContent=s.autopilot.error||''}}
function renderProfiles(d){const select=$('#detectionProfile'),selected=`${d.model}|${d.imgsz}`,signature=(d.profiles||[]).map(p=>`${p.model}|${p.imgsz}`).join(',');if(select.dataset.signature!==signature){select.replaceChildren(...(d.profiles||[]).map(p=>{const o=document.createElement('option');o.value=`${p.model}|${p.imgsz}`;o.textContent=p.name;return o}));select.dataset.signature=signature;select.dataset.dirty=''}if(!select.dataset.dirty&&[...select.options].some(o=>o.value===selected))select.value=selected;select.disabled=d.enabled;$('#applyDetectionProfile').disabled=d.enabled||!select.options.length}
async function status(){try{render(await(await fetch('/api/status',{cache:'no-store'})).json())}catch(e){$('#connection').textContent='離線';$('#connection').classList.add('bad')}}
function renderVehicle(v){
  $('#vehicle').textContent=v.enabled?'已啟用':'停用';
  $('#direction').textContent=({stop:'停止',forward:'前進',left:'左彎',right:'右彎',auto:'自動'})[v.direction]||v.direction;
  $('#speedValue').textContent=v.direction==='auto'?'自動控制':`${v.speed_percent}%`;
  const angle=v.steering_degrees;
  $('#turnValue').textContent=v.direction==='auto'?'自動控制':angle===0?'0° 直行':`${angle<0?'左':'右'} ${Math.abs(angle)}°`;
  $('#wheelValues').textContent=Object.entries(v.wheel_pwm).map(([wheel,value])=>`${wheel}: ${value}%`).join(' · ');
  $('#driveSteps').textContent=`每次加減 ${v.speed_step}% · 每次轉向 ${v.steering_step}° · 範圍 ±${v.steering_max}°`;
  $('#enable').checked=v.enabled;
  if(!v.enabled||v.direction==='stop'||v.direction==='auto')state.keepAlive=false;
}
// Serialize clicks so fast F/B/L/R inputs reach the controller in order.
let controlQueue=Promise.resolve();
function control(action){controlQueue=controlQueue.then(action).catch(e=>{state.keepAlive=false;showError(e)});return controlQueue}
function drive(dir){return control(async()=>{const v=await api('/api/vehicle/drive',{direction:dir});renderVehicle(v);state.keepAlive=v.enabled&&v.direction!=='stop'&&v.direction!=='auto'})}
function stop(){state.keepAlive=false;return drive('stop')}
document.querySelectorAll('[data-dir]').forEach(el=>el.addEventListener('click',()=>drive(el.dataset.dir)));
$('#stop').onclick=stop;
$('#straight').onclick=()=>drive('center');
$('#enable').onchange=e=>{const enabled=e.target.checked;control(async()=>{const v=await api('/api/vehicle/enable',{enabled});renderVehicle(v);state.keepAlive=enabled&&v.direction!=='stop'&&v.direction!=='auto'})};
let heartbeatPending=false;
setInterval(async()=>{
  if(!state.keepAlive||document.hidden||heartbeatPending)return;
  heartbeatPending=true;
  try{const v=await api('/api/vehicle/heartbeat');renderVehicle(v)}
  catch(e){state.keepAlive=false;showError(e)}
  finally{heartbeatPending=false}
},200);
$('#record').onclick=async()=>{try{await api(state.recording?'/api/camera/stop':'/api/camera/start');status()}catch(e){showError(e)}};
function reloadPreview(){preview.src='/api/camera/stream?t='+Date.now();$('#previewState').textContent='切換中';$('#previewError').hidden=true}
$('#detection').onchange=async e=>{const enabled=e.target.checked;try{await api('/api/detection/enable',{enabled});state.detectionEnabled=enabled;reloadPreview();status()}catch(x){e.target.checked=!enabled;showError(x);status()}};
$('#detectionProfile').onchange=e=>{e.target.dataset.dirty='1'};
$('#applyDetectionProfile').onclick=async()=>{const select=$('#detectionProfile'),[model,imgsz]=select.value.split('|');try{await api('/api/detection/configure',{model,imgsz:Number(imgsz)});select.dataset.dirty='';$('#previewMode').textContent=`已切換至 ${imgsz}×${imgsz}`;status()}catch(e){showError(e);status()}};
$('#autopilot').onchange=async e=>{state.keepAlive=false;try{await api('/api/autopilot/enable',{enabled:e.target.checked});if(e.target.checked)reloadPreview();status()}catch(x){e.target.checked=false;showError(x);status()}};
const keys={f:'forward',b:'backward',l:'left',r:'right',ArrowUp:'forward',w:'forward',ArrowDown:'backward',s:'backward',ArrowLeft:'left',a:'left',ArrowRight:'right',d:'right'};
addEventListener('keydown',e=>{
  if(e.repeat)return;
  if(e.code==='Space'){e.preventDefault();stop();return}
  if(e.target.closest('input,select,textarea,[contenteditable="true"]'))return;
  const dir=keys[e.key]||keys[e.key.toLowerCase()];
  if(dir){e.preventDefault();drive(dir)}
});
addEventListener('blur',()=>stop());
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop()});
setInterval(status,1000);status();
const preview=$('#preview');
preview.onload=()=>{$('#previewState').textContent=state.detectionEnabled?'推論中':'原始畫面';$('#previewError').hidden=true};
preview.onerror=()=>{$('#previewState').textContent='無畫面';$('#previewError').hidden=false};
$('#retryPreview').onclick=reloadPreview;
document.querySelectorAll('[data-gimbal]').forEach(el=>el.onclick=async()=>{try{await api('/api/gimbal/move',{axis:el.dataset.gimbal,delta:Number(el.dataset.delta)});status()}catch(e){showError(e)}});
$('#gimbalCenter').onclick=async()=>{try{await api('/api/gimbal/center');status()}catch(e){showError(e)}};
