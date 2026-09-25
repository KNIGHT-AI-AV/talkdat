"use strict";
window.TalkDatSetup=({container,el,request,notice,changed})=>{
  const chapters=[["welcome","Welcome"],["voice","Voice"],["controls","Controls"],["practice","Try it"]];
  const root=el("section",{class:"setup-workspace","data-workspace":"setup"});
  const nav=el("nav",{class:"setup-chapters","aria-label":"Setup chapters"});
  const body=el("div",{class:"setup-body"});
  const status=el("p",{class:"setup-status",role:"status",text:"Loading your setup..."});
  const back=el("button",{text:"Back",disabled:true}),next=el("button",{text:"Continue",class:"primary",disabled:true});
  const later=el("button",{text:"Save for later",class:"quiet",disabled:true});
  const refresh=el("button",{text:"Refresh setup",class:"quiet"});
  let data=null,busy=false,disposed=false,timer=0,action=null,child=null,rendered="",error="",generation=0,formattingPainted="";
  const call=(operation,extra={})=>request("workspace",{area:"setup",operation,...extra});
  const active=()=>data&&(data.rehearsing||["listening","processing"].includes(data.practice.phase)||data.microphone.check.active);
  const button=(text,onclick,primary=false)=>el("button",{text,onclick,...(primary?{class:"primary"}:{})});
  const go=page=>window.TalkDat.navigate(page);
  function sync(){
    if(disposed)return;
    const index=chapters.findIndex(([id])=>id===data?.chapter);
    back.disabled=!data||busy||index<=0;next.disabled=!data||busy;later.disabled=!data||busy;refresh.disabled=busy;
    next.textContent=data?.chapter==="practice"?"Finish setup":"Continue";
    for(const b of nav.querySelectorAll("button")){b.disabled=!data||busy;b.setAttribute("aria-current",b.dataset.chapter===data?.chapter?"step":"false");}
    for(const b of body.querySelectorAll("[data-setup-action]"))b.disabled=busy;
    status.textContent=error||data?.message||"Choose a section. Every check is optional.";status.setAttribute("role",error?"alert":"status");
    changed?.();
  }
  function manage(text,handler,primary=false){const b=button(text,handler,primary);b.dataset.setupAction="true";return b;}
  function link(text,page){return manage(text,()=>go(page));}
  function permissionRows(){
    if(!data.permissions.length)return null;
    const section=el("section",{class:"setup-permissions","aria-label":"Mac permissions"},[el("h3",{text:"Allow the parts you use"}),el("p",{text:"Your microphone captures speech. Accessibility lets Talk DAT type into other apps. Input Monitoring lets it hear your trigger."})]);
    const labels={granted:"Allowed",denied:"Not allowed","not asked":"Review in Settings",unknown:"Could not check"};
    for(const p of data.permissions)section.append(el("div",{class:"setup-permission"},[el("div",{},[el("strong",{text:p.label}),el("span",{class:"secondary",text:labels[p.state]||labels.unknown})]),manage("Review "+p.label,()=>run("permission",{value:p.id}))]));
    section.append(manage("Refresh permissions",()=>run("state")));return section;
  }
  // Owner decision 2026-09-23: the anonymous usage counts are mentioned once, here, as a line and
  // the toggle, with no nag. data.usage_counts is null in a build that cannot send them.
  function usageRow(){
    if(!data.usage_counts)return null;
    const toggle=el("button",{class:"switch",type:"button",role:"switch","aria-checked":Boolean(data.usage_counts.on),"aria-labelledby":"setup-usage-label","aria-describedby":"setup-usage-help"});
    toggle.dataset.setupAction="true";
    toggle.onclick=()=>run("usage",{revision:data.revision,value:toggle.getAttribute("aria-checked")!=="true"});
    return el("section",{class:"setup-usage","aria-label":"Anonymous usage counts"},[el("div",{},[el("strong",{id:"setup-usage-label",text:"Share anonymous usage counts"}),
      el("p",{id:"setup-usage-help",text:"First open, first dictation, still in use, day 7. Never your audio or text. Change it any time in Settings, Privacy."})]),toggle]);
  }
  // Smart formatting: the local writing model. Optional, never part of Finish setup.
  function formattingCard(){
    const card=body.querySelector(".setup-formatting");if(!card)return;
    const f=data.formatting;const visible=Boolean(f&&f.offer_in_setup);card.hidden=!visible;
    // X-687: the card rebuilds about once a second while the model downloads; never
    // under a pressed button (it repaints on the next poll after the release).
    if(window.TalkDatPointerHeld?.())return;
    const signature=JSON.stringify([f,data.formatting_choice]);if(!visible||signature===formattingPainted)return;formattingPainted=signature;
    const later=data.formatting_choice==="later";
    const change=value=>run("formatting",{revision:data.revision,value});
    const head=el("div",{class:"setup-formatting-head"},[el("h3",{text:f.title})]);
    if(f.recommended&&f.can_start)head.append(el("span",{class:"setup-formatting-badge",text:f.recommended_label}));
    const status=el("p",{class:"setup-formatting-status",role:"status",text:f.label+(f.message?". "+f.message:"")});
    const parts=[head,el("p",{text:f.explanation})];
    if(f.note)parts.push(el("p",{class:"secondary",text:f.note}));
    parts.push(status);
    if(f.state==="downloading")parts.push(el("progress",{max:100,...(Number.isInteger(f.percent)?{value:f.percent}:{}),"aria-label":f.label}));
    const actions=el("div",{class:"setup-route-actions"});
    if(f.can_start)actions.append(manage(f.state==="failed"?"Retry":"Set up smart formatting",()=>change("start"),f.recommended&&!later));
    if(f.state==="not_set_up"&&!later)actions.append(manage("Not now",()=>change("later")));
    if(f.download_page)actions.append(manage("Get Ollama",()=>change("download_page")),manage("Check again",()=>change("check")));
    if(actions.childElementCount)parts.push(actions);
    if(later&&f.state==="not_set_up")parts.push(el("p",{class:"secondary",text:"Not now. Set it up any time in Settings, Formatting."}));
    if(f.state==="downloading")parts.push(el("p",{class:"secondary",text:"Keep going with setup. The download continues in the background, and formatting starts using the model as soon as it is ready."}));
    card.replaceChildren(...parts);sync();
  }
  function render(){
    child?.dispose?.();child=null;body.replaceChildren();rendered=data.chapter;
    if(data.chapter==="welcome"){
      // X-685: the Pill's own art (workspaces.css, --pill-strip), never a drawing of it.
      const instrument=el("div",{class:"setup-instrument","aria-hidden":"true"},[el("div",{class:"setup-pill"},[el("span",{class:"setup-pill-frames"}),el("span",{class:"setup-pill-frames setup-pill-next"})])]);
      const text=el("div",{class:"setup-welcome-copy"},[el("h2",{text:"Set up Talk DAT!"}),el("p",{text:"Choose where speech is processed, test your microphone and try a sentence. Your test stays here for you to review."}),
        el("p",{class:"secondary",text:data.completed?"You have completed setup before. Revisit any section to check a new microphone or refresh your controls.":"Start with what you need. You can skip a check and come back from Help."}),manage("Set up my voice",()=>chapter("voice"),true)]);
      body.append(el("div",{class:"setup-welcome"},[instrument,text]),el("details",{class:"setup-orientation"},[el("summary",{text:"Where to find everything"}),el("p",{text:"The Pill is the small Talk DAT! bar on your screen. Hold your shortcut to talk and let go to finish. Click the Pill for hands-free recording, or right-click it (Control-click on a Mac) to open the menu."}),el("p",{text:"History keeps saved dictations. Scratchpad holds your notes. Writing brings formatting, Words and Ramble together."}),link("Explore the menu","menu-order")]));
    }
    if(data.chapter==="voice"){
      body.append(el("h2",{text:"Choose where speech becomes text"}),el("p",{class:"setup-route-summary"}),el("div",{class:"setup-route-actions"},[
        manage("Use Local",()=>run("route",{revision:data.revision,value:"local"})),manage("Use my provider",()=>run("route",{revision:data.revision,value:"byok"})),link("Speech settings","speech"),link("Local models","models")]),
        el("p",{class:"secondary",text:"Local speech needs a downloaded model. Your provider needs your own configured key. Model downloads and microphone checks begin only when you choose them."}),
        el("section",{class:"setup-formatting","aria-label":"Smart formatting",hidden:true}));formattingPainted="";
      const permissions=permissionRows();if(permissions)body.append(permissions);
      const mic=el("div",{class:"setup-microphone"},[el("h2",{text:"Test your microphone"})]);body.append(mic);
      child=window.TalkDatMicCheck({container:mic,el,notice,mode:"mic",changed,
        request:async(_method,payload)=>{const {area,...entry}=payload;const result=await call("mic",{request:entry});if(!disposed&&rendered==="voice"&&data.chapter==="voice"){data=result;paint();}return result.microphone;}});
    }
    if(data.chapter==="controls"){
      body.append(el("h2",{text:"Your dictation shortcut"}),el("p",{text:"Hold these keys together to dictate. Release them to finish."}),
        el("div",{class:"setup-keycaps","aria-label":"Your configured trigger"},data.shortcut.map(text=>el("kbd",{text}))),
        el("p",{class:"setup-rehearsal",role:"status"}),el("div",{class:"setup-route-actions"},[manage("Check my trigger",()=>run("rehearse"),true),manage("End trigger check",()=>run("cancel")),link("Change controls","dictation")]),
        el("p",{class:"secondary",text:"The 30-second trigger check listens for the configured keys without recording audio. Regular shortcuts resume when it finishes, expires or you leave."}),
        el("div",{class:"setup-control-lessons"},[el("h3",{text:"Hands-free dictation"}),el("p",{text:"Click the Pill once to start hands-free dictation, then click again to finish. Your configured Stop and Panic controls remain available."}),el("h3",{text:"Your menu"}),el("p",{text:"Right-click the Pill for your compact menu. Put frequent tools near the top in Appearance, then Menu layout."}),link("Arrange my menu","menu-order")]));
    }
    if(data.chapter==="practice"){
      const result=el("textarea",{class:"setup-result",readonly:true,rows:6,"aria-label":"Your practice result",placeholder:"Your finished words will appear here."});
      body.append(el("h2",{text:"Say something you would actually write"}),el("p",{text:"Try a message, a thought or a short list. Start here, speak naturally, then finish recording. Review what Talk DAT produced."}),
        el("p",{class:"setup-practice-status",role:"status"}),el("p",{class:"setup-formatting-note secondary",role:"status",hidden:true}),result,el("div",{class:"setup-practice-actions"},[
          manage("Start practice",()=>run("practice"),true),manage("Finish recording",()=>run("stop")),manage("Cancel practice",()=>run("cancel")),manage("Copy result",()=>run("copy"))]));
      const details=el("details",{class:"setup-writing"},[el("summary",{text:"Choose a writing style (optional)"}),el("p",{text:"These presets update your existing formatting settings. Keep your current settings by leaving this closed."})]);
      for(const preset of data.presets)details.append(el("div",{class:"setup-preset"},[el("div",{},[el("strong",{text:preset.label}),el("p",{text:preset.description})]),manage("Use "+preset.label,()=>run("preset",{revision:data.revision,value:preset.id}))]));
      body.append(...[details,el("ul",{class:"setup-receipts","aria-label":"Checks actually completed"}),usageRow()].filter(Boolean),el("p",{class:"setup-terms",text:"By choosing Finish setup, you agree to the Terms of Use and acknowledge the Privacy Policy."}),el("div",{class:"setup-route-actions"},[manage("Terms of Use",()=>run("document",{value:"terms"})),manage("Privacy Policy",()=>run("document",{value:"privacy"}))]));
    }
  }
  function paint(){
    if(disposed||!data)return;
    if(rendered!==data.chapter)render();
    const route=body.querySelector(".setup-route-summary");if(route)route.textContent=data.local_only?"Local-only privacy is on. Speech stays on this computer.":`Current route: ${data.provider}.`;
    const rehearsal=body.querySelector(".setup-rehearsal");if(rehearsal)rehearsal.textContent=data.rehearsing?"Hold your configured keys together now. The microphone stays off.":data.flags.hotkey_rehearsed?"Your configured trigger was detected.":"Choose Check my trigger when you are ready.";
    const practice=body.querySelector(".setup-practice-status");if(practice){practice.textContent=data.practice.message;practice.setAttribute("role",data.practice.phase==="empty"?"alert":"status");}
    const result=body.querySelector(".setup-result");if(result&&result.value!==data.practice.text)result.value=data.practice.text;
    const receipts=body.querySelector(".setup-receipts");if(receipts)receipts.replaceChildren(...[["microphone_tested","Microphone measured"],["hotkey_rehearsed","Trigger detected"],["dictation_tested","Practice words received"]].map(([key,label])=>el("li",{text:label+": "+(data.flags[key]?"checked":"not checked"),class:data.flags[key]?"checked":""})));
    formattingCard();
    const usage=body.querySelector(".setup-usage .switch");if(usage&&data.usage_counts)usage.setAttribute("aria-checked",String(Boolean(data.usage_counts.on)));
    const note=body.querySelector(".setup-formatting-note");
    if(note){const f=data.formatting;const downloading=f?.state==="downloading";note.hidden=!downloading;
      note.textContent=downloading?`Smart formatting is still getting ready (${f.label}). Until then your practice uses the built-in rules.`:"";}
    sync();
    const listening=data.practice.phase==="listening",processing=data.practice.phase==="processing";
    for(const b of body.querySelectorAll(".setup-practice-actions button")){
      if(b.textContent==="Start practice")b.disabled=busy||listening||processing;
      if(b.textContent==="Finish recording")b.disabled=busy||!listening;
      if(b.textContent==="Cancel practice")b.disabled=busy||(!listening&&!processing);
      if(b.textContent==="Copy result")b.disabled=busy||!data.practice.text;
    }
    clearTimeout(timer);if(data.rehearsing||listening||processing)timer=setTimeout(()=>run("state",{},false),180);
    else if(["downloading","checking"].includes(data.formatting?.state))timer=setTimeout(()=>run("state",{},false),1000);
  }
  function run(operation,extra={},interactive=true){const work=perform(operation,extra,interactive);if(interactive)action=work;return work;}
  async function perform(operation,extra={},interactive=true){
    if(disposed||busy)return false;const current=++generation;if(interactive){busy=true;clearTimeout(timer);sync();}
    try{const value=await call(operation,extra);if(disposed||current!==generation)return false;data=value;error="";busy=false;paint();return true;}
    catch(e){if(!disposed&&current===generation){error=e.message;notice(error,true);}return false;}
    finally{if(!disposed&&current===generation){busy=false;paint();}}
  }
  async function chapter(value){
    if(busy)return false;if(child&&!await child.leave())return false;
    return run("chapter",{revision:data.revision,value});
  }
  for(const [id,label] of chapters){const b=el("button",{text:label,"data-chapter":id,disabled:true});b.onclick=()=>{action=chapter(id);};nav.append(b);}
  back.onclick=()=>{action=chapter(chapters[Math.max(0,chapters.findIndex(([id])=>id===data.chapter)-1)][0]);};
  next.onclick=()=>{action=data.chapter==="practice"?run("finish",{revision:data.revision,accepted:true}):chapter(chapters[chapters.findIndex(([id])=>id===data.chapter)+1][0]);};
  later.onclick=()=>go("general");refresh.onclick=()=>{action=(async()=>{if(child&&!await child.leave())return;rendered="";return run("state");})();};
  root.append(nav,body,status,el("div",{class:"setup-footer"},[later,refresh,el("div",{class:"setup-next"},[back,next])]));container.append(root);action=run("state");
  return {root,isDirty:()=>busy||Boolean(active()),
    leave:async()=>{if(action)await action;if(busy)return false;if(child&&!await child.leave())return false;if(!data)return true;
      if(!await run("cancel"))return false;return run("chapter",{revision:data.revision,value:data.chapter});},
    dispose:()=>{disposed=true;clearTimeout(timer);child?.dispose?.();call("cancel").catch(()=>{});}};
};
