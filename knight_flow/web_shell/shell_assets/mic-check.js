"use strict";
window.TalkDatMicCheck=({container,el,request,notice,mode,changed})=>{
  const root=el("section",{class:"mic-check-workspace","data-workspace":"mic-check"});
  const speech=mode==="speech";
  const input=el("select",{"aria-label":"Input device",disabled:true});
  const refresh=el("button",{text:"Refresh inputs",class:"quiet",disabled:true});
  const start=el("button",{text:speech?"Start speech check":"Check my mic",class:"primary",disabled:true});
  const stop=el("button",{text:"Stop check",class:"quiet",disabled:true});
  const status=el("p",{class:"mic-check-status",role:"status",text:"Microphone off."});
  const selection=el("p",{class:"secondary mic-selection-status",role:"status"});
  const meter=el("meter",{min:0,max:1,value:0,"aria-label":"Microphone input level"});
  const elapsed=el("span",{class:"secondary",text:"0.0 / 3 seconds"});
  const result=el("section",{class:"mic-check-result","aria-label":"Check result"});
  const copy=el("button",{text:"Copy test words",class:"quiet",hidden:true});
  const settings=el("button",{text:"Local models",class:"quiet",onclick:()=>window.TalkDat.navigate("models")});
  let disposed=false,timer=0,data=null,busy=false,action=null,lastDevices="",resultKey="",loaded=false,generation=0;
  const call=(operation,extra={})=>request("workspace",{area:"mic-check",operation,...extra});
  function fail(error){status.textContent=error.message||"The check could not continue. Try again.";status.setAttribute("role","alert");}
  function paint(snapshot){
    if(disposed)return;
    data=snapshot;const check=data.check;const names=data.devices;
    const key=JSON.stringify([names.devices,data.selected]);
    if(key!==lastDevices){
      lastDevices=key;input.replaceChildren(el("option",{value:"",text:"System default"}));
      for(const name of names.devices)input.append(el("option",{value:name,text:name}));
      if(data.selected&&!names.devices.includes(data.selected))input.append(el("option",{value:data.selected,text:data.selected+" (unavailable)"}));
    }
    input.value=data.selected;
    input.disabled=busy||check.active;start.disabled=busy||check.active;
    stop.disabled=busy||!check.active;
    refresh.disabled=busy||names.status==="loading";
    selection.textContent=names.status==="loading"?"Looking for inputs...":names.message||"Selecting a microphone saves it for dictation and these checks.";
    status.textContent=check.message;status.setAttribute("role",check.phase==="error"?"alert":"status");
    root.dataset.phase=check.phase;
    meter.value=Math.min(1,Math.max(0,check.level*6));
    meter.setAttribute("aria-valuetext",check.phase==="listening"?`${Math.round(check.level*100)} percent RMS`:"Not listening");
    elapsed.textContent=`${Number(check.elapsed||0).toFixed(1)} / ${check.seconds} seconds`;
    const next=JSON.stringify([check.report,check.text,check.recognition_ms,check.phase]);
    if(next!==resultKey){
      resultKey=next;result.replaceChildren();
      if(check.report){
        const r=check.report;
        const label={ok:"Level looks usable",dead:"No signal in this sample",too_quiet:"Input is very quiet",too_hot:"Input is clipping",noisy:"Background level is high"}[r.verdict]||"Microphone result";
        result.append(el("h2",{text:label}),el("p",{text:r.advice}));
        const metrics=el("dl",{class:"mic-check-metrics"});
        for(const [name,value] of [["Speech level",r.speech_rms.toFixed(3)],["Quiet level",r.noise_floor.toFixed(3)],["Clipped samples",`${(r.clipping_ratio*100).toFixed(1)}%`]])metrics.append(el("div",{},[el("dt",{text:name}),el("dd",{text:value})]));
        result.append(metrics,el("p",{class:"secondary",text:"A short level check cannot measure recognition accuracy. Pause briefly during the sample so the quiet level has a useful reference."}));
      }else if(speech&&check.phase==="ready"){
        result.append(el("h2",{text:"What the local model heard"}),el("p",{class:"mic-check-transcript",text:check.text||"No words returned."}),el("p",{class:"secondary",text:`Recognition took ${(check.recognition_ms/1000).toFixed(2)} seconds after capture. This can include loading the model; it is not dictation release-to-paste latency.`}));
      }else if(!check.active){
        result.append(el("h2",{text:speech?"Try a sentence you would actually dictate":"A quick check before you dictate"}),el("p",{class:"secondary",text:speech?"Record eight seconds and review the local model's words. No cloud comparison runs here.":"Speak for three seconds with a short pause. Check the level, quiet background and clipping, then adjust the microphone if needed."}));
      }
    }
    copy.hidden=!(check.phase==="ready"&&check.text);copy.disabled=busy;
    changed?.();clearTimeout(timer);
    if(check.active||names.status==="loading")timer=setTimeout(()=>run("status",{},false),120);
  }
  async function run(operation,extra={},interactive=true){
    if(disposed||busy)return false;
    const revision=++generation;
    if(interactive){busy=true;clearTimeout(timer);if(data)paint(data);}
    try{const snapshot=await call(operation,extra);if(revision!==generation)return true;busy=false;paint(snapshot);if(operation==="copy")notice("Test words copied.");return true;}
    catch(error){if(revision!==generation)return false;busy=false;if(data)paint(data);else refresh.disabled=false;if(!disposed)fail(error);return false;}
  }
  start.onclick=()=>{action=run("start");};stop.onclick=()=>{action=run("stop");};
  refresh.onclick=()=>{action=loaded?run("refresh"):run("open",{mode}).then(value=>{loaded=value;return value;});};copy.onclick=()=>{action=run("copy");};
  input.onchange=()=>{action=run("select",{value:input.value});};
  root.append(el("div",{class:"mic-input-row"},[el("label",{},[el("span",{text:"Input device"}),input]),refresh]),selection,
    el("div",{class:"mic-check-stage"},[status,el("div",{class:"mic-level-row"},[meter,elapsed]),el("div",{class:"action-list"},[start,stop])]),
    result,el("div",{class:"action-list"},[copy,...(speech?[settings]:[])]),
    el("p",{class:"secondary mic-check-privacy",text:"The microphone opens only when you start. Stop, leaving this page or closing this window cancels the check. Test audio stays in memory and is discarded; no test is added to History."}));
  container.append(root);
  action=run("open",{mode}).then(value=>{loaded=value;return value;});
  return {root,isDirty:()=>busy||Boolean(data?.check.active),
    leave:async()=>{if(action)await action;if(!loaded)return true;return await run("stop");},
    dispose:()=>{disposed=true;clearTimeout(timer);if(data?.check.active)call("stop").catch(()=>{});}};
};
