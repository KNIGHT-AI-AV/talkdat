"use strict";
// The screen a launch opens on. His report, 2026-09-21: the app came up on
// whatever settings page the last session left behind, which is not a
// greeting. The hero renders from the first status call so Home is never the
// thing being waited for; the activity figures walk the history store on a
// worker and fill in when they land.
window.TalkDatHome=({container,el,request,notice})=>{
  const root=el("section",{"data-workspace":"home",class:"home-workspace"});
  const hero=el("header",{class:"home-hero"});
  const metrics=el("div",{class:"home-metrics"});
  const news=el("section",{class:"home-news"});
  const status=el("p",{class:"secondary home-status",role:"status",text:"Getting things ready..."});
  let timer=0,disposed=false,painted=0,heroPainted=false;
  const number=value=>Number(value||0).toLocaleString();
  const minutes=value=>value>=60?`${Math.floor(value/60)}h ${value%60}m`:`${value}m`;
  const call=operation=>request("workspace",{area:"home",operation});
  function greetingWord(){
    const hour=new Date().getHours();
    return hour<5?"Good evening":hour<12?"Good morning":hour<18?"Good afternoon":"Good evening";
  }
  function key(text){
    // Each key cap is its own element so the shortcut reads as keys, not prose.
    const row=el("span",{class:"home-keys","aria-label":text.replace(/\+/g," plus ")});
    text.split("+").forEach((cap,index)=>{
      if(index)row.append(el("span",{class:"home-key-plus","aria-hidden":"true",text:"+"}));
      row.append(el("kbd",{class:"home-key",text:cap}));
    });
    return row;
  }
  function action(label,detail,page){
    const button=el("button",{class:"home-action",type:"button",onclick:()=>window.TalkDat.navigate(page)});
    button.append(el("strong",{text:label}),el("small",{class:"secondary",text:detail}));
    return button;
  }
  function renderHero(g){
    const shortcuts=g.shortcuts||{};
    const speech=g.speech||{};
    // A name is optional; without one the greeting still reads as a sentence.
    const who=(g.name||"").trim();
    const lines=[el("h1",{class:"home-greeting",text:who?`${greetingWord()}, ${who}.`:greetingWord()+"."})];
    if(shortcuts.push_to_talk){
      lines.push(el("p",{class:"home-lede"},[
        el("span",{text:"Hold "}),key(shortcuts.push_to_talk),el("span",{text:" and speak. Let go when you are done."})]));
    } else {
      lines.push(el("p",{class:"home-lede",text:"Set a dictation shortcut in Dictation settings to start talking."}));
    }
    if(shortcuts.hands_free){
      lines.push(el("p",{class:"secondary home-sub"},[
        el("span",{text:"Prefer not to hold it? "}),key(shortcuts.hands_free),el("span",{text:" toggles hands free."})]));
    }
    const chip=el("p",{class:"home-chip secondary"},[
      el("span",{class:`home-dot ${speech.local?"is-local":"is-cloud"}`,"aria-hidden":"true"}),
      el("span",{text:speech.local
        ?`Speech runs on this computer (${speech.model||"local model"}).`
        :`Speech runs through ${speech.label||"your provider"} (${speech.model||"automatic"}).`})]);
    // Find-more P0-3 and P0-7: what the launch found (a take waiting in
    // Recovery, settings that could not be read) is said above the greeting.
    const alerts=(g.alerts||[]).filter(a=>a&&a.text).map(a=>{
      const line=el("div",{class:"home-alert",role:"alert"},[el("p",{text:a.text})]);
      if(a.page==="recovery")line.append(el("button",{type:"button",class:"quiet",text:"Open Recovery",
        onclick:()=>window.TalkDat.navigate("recovery")}));
      return line;
    });
    hero.replaceChildren(...alerts,...lines,chip);
  }
  // What's new is read as Markdown blocks by the app (2026-09-23): the
  // section's opening paragraph arrives as `summary`, its "- " items as
  // `notes`, each one a whole sentence. Nothing here splits or clamps them.
  function renderNews(g){
    const summary=(g.summary||[]).filter(Boolean);
    const notes=(g.notes||[]).filter(Boolean);
    news.replaceChildren(el("h2",{text:`What's new in ${g.version||"this version"}`}));
    for(const paragraph of summary)news.append(el("p",{class:"home-news-summary",text:paragraph}));
    if(notes.length){
      const list=el("ul",{class:"home-notes"});
      for(const note of notes)list.append(el("li",{},[el("span",{class:"home-note-text",text:note})]));
      news.append(list);
    }
    if(g.more_notes>0)news.append(el("p",{class:"secondary home-notes-more",
      text:`Plus ${g.more_notes} more ${g.more_notes===1?"change":"changes"} in this version.`}));
    if(!summary.length&&!notes.length){
      news.append(el("p",{class:"secondary",text:"This build's notes are not bundled. Help has the full history."}));
    }
    news.append(updateRow);
  }
  // Check for updates answers HERE (2026-09-23; it used to open Settings >
  // General, where nothing checked either). The app runs its own update check
  // and Home shows the answer in place; Install opens the app's verified
  // Update window for the release the check found.
  const updateStatus=el("p",{class:"home-update-status",role:"status","aria-live":"polite",hidden:true});
  const checkButton=el("button",{class:"quiet",type:"button",text:"Check for updates",onclick:()=>update("check_updates")});
  const installButton=el("button",{class:"primary",type:"button",text:"Install update",hidden:true,onclick:()=>update("install_update")});
  const updateRow=el("div",{class:"home-update"},[checkButton,installButton,updateStatus]);
  function renderUpdate(u){
    const phase=u?.phase||"idle";
    checkButton.disabled=phase==="checking";
    installButton.hidden=phase!=="available";
    installButton.textContent=u?.version?`Install ${u.version}`:"Install update";
    updateStatus.textContent=u?.message||"";
    updateStatus.hidden=!updateStatus.textContent;
    updateStatus.setAttribute("role",phase==="failed"?"alert":"status");
    updateStatus.classList.toggle("is-problem",phase==="failed");
    updateRow.dataset.phase=phase;
  }
  function renderMetrics(a){
    if(!a){metrics.replaceChildren();return;}
    if(!a.history_enabled){
      metrics.replaceChildren(el("p",{class:"secondary",
        text:"Saving history is off, so there is nothing to total up here. Your words still reach your apps."}));
      return;
    }
    const tile=(label,value,detail)=>el("div",{class:"home-metric"},[
      el("p",{class:"secondary",text:label}),el("strong",{text:value}),el("small",{class:"secondary",text:detail})]);
    metrics.replaceChildren(
      tile("Words dictated",number(a.words),`${number(a.entries)} saved entries`),
      tile("Typing time saved",minutes(a.minutes_saved),"Estimate from saved dictation"),
      tile("Streak",`${number(a.streak_days)} ${a.streak_days===1?"day":"days"}`,"In a row, on this computer"));
  }
  // X-611: an update ready to install is answered here. It was the Tk Update
  // window every existing user met on every release. The install is the
  // app's own verified path; this panel shows its words and its progress.
  const offerPanel=el("section",{class:"home-offer","aria-label":"Update ready",hidden:true});
  let offerPainted="",lastOffer=null;
  function renderOffer(o){
    lastOffer=o||null;
    if(!o){offerPanel.hidden=true;offerPanel.replaceChildren();offerPainted="";return;}
    offerPanel.hidden=false;
    const shape=JSON.stringify([o.latest,o.phase,o.can_install]);
    if(shape!==offerPainted){
      const button=(text,op,primary)=>el("button",{type:"button",text,class:primary?"primary":"quiet","data-op":op,onclick:()=>update(op)});
      const buttons=[];
      if(o.can_install&&o.phase!=="started")buttons.push(button(o.phase==="failed"?"Try again":"Install now","update_install",true));
      buttons.push(button("View on GitHub","update_github",false));
      if(o.phase!=="started")buttons.push(button("Skip this version","update_skip",false),button("Later","update_later",false));
      const details=(o.details||[]).length?"  ·  "+o.details.join("  ·  "):"";
      offerPanel.replaceChildren(
        el("h2",{text:"A new version of Talk DAT! is ready"}),
        el("p",{class:"home-offer-version",text:`${o.current} → ${o.latest}${details}`}),
        el("div",{class:"home-offer-notes",tabindex:"0","aria-label":"What changed",text:o.notes||"This release has no notes."}),
        el("progress",{class:"home-offer-progress",max:"100","aria-label":"Update download"}),
        el("p",{class:"home-offer-status",role:"status","aria-live":"polite"}),
        el("div",{class:"action-list home-offer-actions"},buttons));
      offerPainted=shape;
    }
    const installing=o.phase==="installing";
    offerPanel.querySelectorAll("button").forEach(b=>{if(b.dataset.op!=="update_github")b.disabled=installing;});
    const bar=offerPanel.querySelector("progress");
    bar.hidden=o.percent==null;if(o.percent!=null)bar.value=o.percent;
    const line=offerPanel.querySelector(".home-offer-status");
    line.textContent=o.status||"";line.setAttribute("role",o.phase==="failed"?"alert":"status");
  }
  async function update(operation){
    clearTimeout(timer);
    const offerOperation=operation.startsWith("update_");
    const asked=operation==="check_updates"||operation==="install_update";
    if(asked)checkButton.disabled=true;
    try{
      const result=await call(operation);if(disposed)return;
      if(result.greeting&&!heroPainted){renderHero(result.greeting);renderNews(result.greeting);heroPainted=true;}
      status.setAttribute("role",result.phase==="error"?"alert":"status");
      status.textContent=result.phase==="loading"?"Adding up your saved words..."
        :result.phase==="error"?(result.message||"Your activity could not load."):"";
      status.hidden=!status.textContent;
      if(result.activity&&result.phase!=="loading"&&result.revision!==painted){renderMetrics(result.activity);painted=result.revision;}
      renderUpdate(result.update);
      renderOffer(result.offer);
      if(result.notice)notice(result.notice);
      const checking=result.update?.phase==="checking";
      const installing=result.offer?.phase==="installing";
      if(result.phase==="loading"||checking||installing)timer=setTimeout(()=>update("status"),result.phase==="loading"?180:installing?250:300);
    }catch(error){
      if(disposed)return;
      if(offerOperation){notice(error.message||"That update action did not finish.",true);return;}
      if(asked){
        checkButton.disabled=false;
        renderUpdate({phase:"failed",message:error.message||"Couldn't check for updates. Try again in a minute."});
        return;
      }
      status.hidden=false;status.setAttribute("role","alert");
      status.textContent="Home could not load. Your settings and words are unchanged.";
    }
  }
  const quick=el("div",{class:"home-actions"},[
    action("History","Find and reuse a recent dictation","history"),
    action("Scratchpad","Write and keep notes","scratchpad"),
    action("Translate","Translate text into another language","translation"),
    action("Settings","Shortcuts, speech and formatting","general")]);
  root.append(hero,offerPanel,quick,metrics,news,status);container.append(root);update("refresh");
  // Leaving (or closing) while the verified installer runs is refused, as the
  // Update window refused it.
  const leave=async()=>{
    if(lastOffer?.phase!=="installing")return true;
    notice("The verified installer is being prepared. Wait for it to finish.",true);return false;
  };
  return {root,page:"home",leave,dispose:()=>{disposed=true;clearTimeout(timer);}};
};
