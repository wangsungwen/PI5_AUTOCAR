(() => {
  let source='pi', timer, dual=false, busy=false;
  const sim=document.querySelector('#simPreview');
  const note=document.querySelector('#simNote');
  function nextFrame(){
    clearTimeout(timer);
    if(source!=='pi'&&!document.hidden)
      sim.src=({hood:'/api/sim/hood',road:'/api/sim/road',ue4:'/api/sim/frame'}[source])+'?t='+Date.now();
  }
  sim.onload=()=>{
    note.textContent=({hood:'UE4 車頭／引擎蓋',road:'UE4 前保險桿／道路',ue4:'UE4 車內第一人稱'}[source])+' · 即時串流';
    sim.style.opacity='1';
    if(source!=='pi')timer=setTimeout(nextFrame,120);
  };
  sim.onerror=()=>{
    note.textContent='UE4 未連線：請在 Windows 執行 start_cockpit.cmd';
    sim.style.opacity='0';
    if(source!=='pi')timer=setTimeout(nextFrame,1500);
  };
  document.querySelector('#cameraSource').onchange=e=>{
    source=e.target.value;
    clearTimeout(timer);
    const ue4=source!=='pi';
    if(ue4&&!dual)document.querySelector('#recordView').value=source==='ue4'?'fpv':source;
    document.querySelector('#page-camera').classList.toggle('sim-view',ue4);
    document.querySelector('#preview').hidden=ue4;
    sim.hidden=!ue4;
    note.hidden=!ue4;
    if(ue4){note.textContent='連接 UE4…';nextFrame();}
    else sim.removeAttribute('src');
  };
  document.addEventListener('visibilitychange',()=>{
    clearTimeout(timer);
    if(!document.hidden&&source!=='pi')nextFrame();
  });
  async function refresh(){
    try{
      const r=await fetch('/api/sim/status',{cache:'no-store'});
      if(!r.ok)throw Error('請更新並重啟 Pi 服務');
      const s=await r.json();
      dual=s.dual_recording||s.remote.recording;
      document.querySelector('#dualRecord').textContent=dual?'■ 停止同步側錄':'● Pi＋UE4 同步側錄';
      document.querySelector('#record').disabled=dual||busy;
      document.querySelector('#recordView').disabled=dual||busy;
      document.querySelector('#dualRecord').disabled=busy;
      const session=s.session;
      document.querySelector('#dualStatus').textContent=
        `Pi：${s.pi.recording?'錄影中':'待機'} · UE4：${s.remote.recording?'錄影中':s.remote.connected?'已連線':'未連線'}`+
        (s.remote.error?'\n'+s.remote.error:'')+
        (session?`\nPi：${session.pi_file}\nWindows：${session.ue4_file}`:'');
    }catch(e){document.querySelector('#dualStatus').textContent=e.message;}
    finally{setTimeout(refresh,2000);}
  }
  document.querySelector('#dualRecord').onclick=async()=>{
    if(busy)return;
    const starting=!dual;
    busy=true;document.querySelector('#dualRecord').disabled=true;
    document.querySelector('#record').disabled=true;
    try{
      const r=await fetch('/api/recording/dual/'+(starting?'start':'stop'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:document.querySelector('#recordView').value})});
      const d=await r.json();
      if(!r.ok)throw Error(d.error||'同步側錄失敗');
      dual=starting;
      document.querySelector('#dualStatus').textContent=dual?'兩路錄影已開始':'兩路錄影已停止';
    }catch(e){document.querySelector('#dualStatus').textContent=e.message;}
    finally{busy=false;document.querySelector('#dualRecord').disabled=false;}
  };
  refresh();
})();
