"use strict";
window.TalkDatStats=({container,el,request,notice})=>{
  const root=el("section",{"data-workspace":"stats",class:"activity-workspace"});
  const refresh=el("button",{text:"Refresh"});
  const history=el("button",{text:"Read History",class:"quiet",onclick:()=>window.TalkDat.navigate("history")});
  const status=el("p",{class:"secondary activity-status",role:"status",text:"Reading saved activity..."});
  const body=el("div",{class:"activity-body"});
  let timer=0,disposed=false,painted=0;
  const number=value=>Number(value||0).toLocaleString();
  const minutes=value=>value>=60?`${Math.floor(value/60)}h ${value%60}m`:`${value}m`;
  const call=operation=>request("workspace",{area:"stats",operation});
  const date=value=>{const [y,m,d]=value.split("-").map(Number);return new Date(y,m-1,d);};
  function metric(label,value,detail){return el("div",{class:"activity-metric"},[
    el("p",{class:"secondary",text:label}),el("strong",{text:value}),el("small",{class:"secondary",text:detail})]);}
  function line(label,value){return el("div",{class:"activity-detail"},[el("dt",{text:label}),el("dd",{text:value})]);}
  function render(data){
    const a=data.activity,s=data.speech;
    const counts=el("div",{class:"activity-metrics"},[
      metric("Saved words",number(a.words),`${number(a.entries)} saved entries`),
      metric("Today",number(a.today),`${number(a.streak_days)} ${a.streak_days===1?"day":"days"} in a row`),
      metric("Typing time saved",minutes(a.minutes_saved),"Estimate from saved dictation")]);
    const bars=el("ol",{class:"activity-week","aria-label":"Saved entries in the last seven days"});
    const largest=Math.max(1,...a.daily.map(day=>day.entries));
    for(const day of a.daily){
      const stamp=date(day.date);
      const bar=el("span",{class:"activity-bar","aria-hidden":"true"});bar.style.height=`${day.entries?Math.max(2,day.entries/largest*92):0}px`;
      bars.append(el("li",{"aria-label":`${stamp.toLocaleDateString(undefined,{month:"long",day:"numeric"})}: ${number(day.entries)} entries`},[
        el("span",{class:"activity-amount",text:number(day.entries)}),el("div",{class:"activity-bar-track"},[bar]),
        el("span",{class:"secondary",text:stamp.toLocaleDateString(undefined,{weekday:"short"})})]));
    }
    const week=el("section",{class:"activity-week-panel"},[el("h2",{text:"The past seven days"}),bars,
      el("p",{class:"secondary",text:`${number(a.active_days)} active days in saved history. Dates use this computer's time zone.`})]);
    const types=el("dl",{class:"activity-types"});
    for(const row of a.by_type)types.append(line(row.label,number(row.entries)));
    const entries=el("section",{class:"activity-breakdown"},[el("h2",{text:"What you've saved"}),a.entries?types:el("p",{class:"secondary",text:"Saved dictations, rewrites and translations will appear here."})]);
    const route=el("section",{class:"activity-route"},[el("h2",{text:"Current speech setup"}),el("dl",{},[
      line("Provider",s.provider_label),line("Model",s.model_label||s.model||"Automatic"),
      line("Speech time",`${number(s.total_minutes)} min, estimated`),
      line("Per dictation day",a.dictation_active_days?`${number(s.minutes_per_active_day)} min, estimated`:"Not enough dated history")])]);
    const estimate=el("details",{class:"activity-estimates"},[el("summary",{text:"About these estimates"})]);
    const cost=!s.is_cloud?"This local speech route has no per-minute provider charge.":
      !a.dictation_active_days?"Not enough dated history to project processing costs.":
      s.estimated_monthly_cost===null?"No processing-rate estimate is available for this model.":
      `At the listed rate, using today's model and your average dictation-day volume on all 30 days would project $${s.estimated_monthly_cost.toFixed(2)} in speech processing. The rate table is dated August 4, 2026 and may be outdated.`;
    estimate.append(el("p",{class:"secondary",text:"Typing time compares 40 typed words per minute with 150 spoken words per minute. Speech time uses saved dictation words, not measured audio duration. Word counts are approximate; rewrites and translations are included in saved words but excluded from speech estimates."}),
      el("p",{class:"secondary",text:"Current settings may differ from the routes used for older entries. These estimates are not a bill and exclude writing models and other charges. Talk DAT itself is free."}),
      el("p",{class:"secondary",text:cost}));
    const notes=[];
    if(!data.history_enabled)notes.push("Saving transcript history is off. These totals include only entries already saved.");
    if(a.capped)notes.push(`Showing the most recent ${number(a.limit)} saved entries.`);
    if(a.unknown_dates)notes.push(`${number(a.unknown_dates)} ${a.unknown_dates===1?"entry has":"entries have"} no usable date; ${a.unknown_dates===1?"it counts":"they count"} in totals but not the calendar.`);
    body.replaceChildren(counts,...(notes.length?[el("aside",{class:"activity-notes","aria-label":"About saved history"},notes.map(text=>el("p",{class:"activity-note secondary",text})))]:[]),week,
      el("div",{class:"activity-columns"},[entries,route]),estimate);
  }
  async function update(operation){
    clearTimeout(timer);
    refresh.disabled=true;
    try{
      const result=await call(operation);if(disposed)return;
      refresh.disabled=result.phase==="loading";
      status.setAttribute("role",result.phase==="error"?"alert":"status");
      status.textContent=result.phase==="loading"?"Refreshing saved activity...":result.message||"Based on history saved on this computer.";
      if(result.data && result.phase!=="loading" && result.revision!==painted){render(result.data);painted=result.revision;}
      if(result.phase==="loading")timer=setTimeout(()=>update("status"),180);
    }catch(error){if(!disposed){refresh.disabled=false;status.setAttribute("role","alert");status.textContent="Activity could not refresh. Your saved history is unchanged. Try Refresh again.";}}
  }
  refresh.addEventListener("click",()=>update("refresh"));
  root.append(el("div",{class:"action-list"},[refresh,history]),status,body);container.append(root);update("refresh");
  return {root,leave:async()=>true,dispose:()=>{disposed=true;clearTimeout(timer);}};
};
