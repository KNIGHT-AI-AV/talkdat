"use strict";
window.TalkDatWorkspaces = (() => {
  function history({container, el, request, notice}) {
    const state={query:"",pinned:false,offset:0,selected:null,generation:0,reading:0,timer:0,next:null,exportGeneration:0,exportTimer:0,exportActive:false,receiptSignature:"",preferences:{clock:"12h"}};
    const root=el("section",{"data-workspace":"history",class:"document-workspace"});
    const collection=el("div",{class:"document-collection"});
    const reader=el("article",{class:"document-reader","aria-label":"Selected dictation"});
    const search=el("input",{type:"search","aria-label":"Search dictation history",placeholder:"Search your words"});
    const all=el("button",{text:"Recent","aria-pressed":"true"});
    const pinned=el("button",{text:"Pinned","aria-pressed":"false"});
    const tabs=el("div",{class:"segmented",role:"group","aria-label":"History view"},[all,pinned]);
    const list=el("div",{class:"document-list",role:"group","aria-label":"Dictations"});
    const count=el("p",{class:"secondary",role:"status"});
    const older=el("button",{text:"Older entries",class:"quiet"});
    const newer=el("button",{text:"Newer entries",class:"quiet"});
    const empty=()=>reader.replaceChildren(el("p",{class:"empty secondary",text:"Choose a dictation to read it here."}));
    async function call(operation,extra={}) {
      return request("workspace",{area:"history",operation,...(['utility','export'].includes(operation)?{}:{pinned:state.pinned}),...extra});
    }
    function stamp(value) {
      if(value==null||!Number.isFinite(new Date(value*1000).getTime()))return "Date unavailable";
      return new Date(value*1000).toLocaleString(undefined,{month:"short",day:"numeric",hour:"numeric",minute:"2-digit",hour12:state.preferences.clock!=="24h"});
    }
    async function select(row,focus=false,openReader=true) {
      state.selected=row;
      const generation=++state.reading;
      if(openReader)root.classList.add("reading");
      for(const button of list.querySelectorAll("button"))button.setAttribute("aria-pressed",String(button.dataset.entry===row.id));
      const back=el("button",{text:"Back to history",class:"quiet reader-back",onclick:()=>{root.classList.remove("reading");list.querySelector('[aria-pressed="true"]')?.focus();}});
      const copy=el("button",{text:"Copy full text"});
      const pin=el("button",{text:row.pinned?"Unpin":"Pin","aria-pressed":row.pinned});
      const text=el("div",{class:"document-text",tabindex:"0","aria-label":"Dictation text",text:"Loading your words..."});
      const more=el("button",{text:"Read more",class:"quiet",hidden:true});
      reader.replaceChildren(el("header",{class:"document-actions"},[back,el("time",{text:stamp(row.created_at)}),copy,pin]),text,more);
      async function command(operation,button) {
        button.disabled=true;
        try {
          const result=await call(operation,{id:row.id});
          if(result.message)notice(result.message);
          if(operation!=="copy")await load();
        }catch(error){notice(error.message,true);}finally{button.disabled=false;}
      }
      copy.addEventListener("click",()=>command("copy",copy));
      pin.addEventListener("click",()=>command(row.pinned?"unpin":"pin",pin));
      async function read(offset=0) {
        more.disabled=true;
        try {
          const result=await call("read",{id:row.id,offset});
          if(generation!==state.reading)return;
          if(offset===0)text.textContent=result.text;else text.append(document.createTextNode(result.text));
          more.hidden=result.next===null;
          more.onclick=()=>read(result.next);
          if(focus&&offset===0)text.focus({preventScroll:true});
        }catch(error){if(generation===state.reading){text.textContent="This entry could not load. Refresh History to try again.";notice(error.message,true);}}
        finally{more.disabled=false;}
      }
      await read();
    }
    async function load() {
      const generation=++state.generation;
      count.textContent="Loading local history...";
      try {
        const result=await call("list",{query:state.query,offset:state.offset});
        if(generation!==state.generation||!root.isConnected)return;
        state.preferences=result.preferences||state.preferences;
        design.value=state.preferences.report_design||"boardroom";
        list.replaceChildren();
        count.textContent=result.total ? `${result.offset+1} to ${result.offset+result.entries.length} of ${result.total}${state.pinned?" pinned":" recent"}` : state.query?"No matching dictations.":state.pinned?"Pin a dictation to keep it close.":"Your saved dictations will appear here.";
        older.disabled=result.next===null;newer.disabled=state.offset===0;state.next=result.next;
        for(const row of result.entries) {
          const button=el("button",{class:"document-entry","data-entry":row.id,"aria-pressed":state.selected?.id===row.id},[
            el("time",{text:stamp(row.created_at)}),el("span",{text:row.preview}),
            el("small",{text:row.pinned?"Pinned":row.type.replaceAll("_"," ")})]);
          button.addEventListener("click",()=>select(row,true));list.append(button);
        }
        const selected=result.entries.find(row=>row.id===state.selected?.id);
        if(selected)await select(selected,false,root.classList.contains("reading"));
        else if(result.entries.length && innerWidth>800)await select(result.entries[0]);
        else {state.selected=null;state.reading++;empty();root.classList.remove("reading");}
      }catch(error){if(generation===state.generation){count.textContent="History could not load.";notice(error.message,true);}}
    }
    search.addEventListener("input",()=>{state.query=search.value;state.offset=0;clearTimeout(state.timer);state.timer=setTimeout(load,220);});
    for(const [button,value] of [[all,false],[pinned,true]])button.addEventListener("click",()=>{
      state.pinned=value;state.offset=0;state.selected=null;
      all.setAttribute("aria-pressed",String(!value));pinned.setAttribute("aria-pressed",String(value));load();
    });
    older.addEventListener("click",()=>{if(state.next!==null){state.offset=state.next;load();}});
    newer.addEventListener("click",()=>{state.offset=Math.max(0,state.offset-30);load();});
    const options=el("details",{class:"workspace-options"},[el("summary",{text:"Export and manage"})]);
    const actions=el("div",{class:"action-list"});
    const confirmation=el("dialog",{class:"note-delete-dialog","aria-labelledby":"history-clear-title"});
    const confirmTitle=el("h2",{id:"history-clear-title"});const confirmText=el("p");
    const cancel=el("button",{text:"Keep everything"}),confirm=el("button",{text:"Clear"});
    confirmation.append(confirmTitle,confirmText,el("div",{class:"action-list"},[cancel,confirm]));
    cancel.addEventListener("click",()=>confirmation.close());
    let pendingClear="";
    async function utility(action,value=""){
      try{const result=await call("utility",{action,value});if(result.message)notice(result.message);if(result.page)window.TalkDat.navigate(result.page);await load();}
      catch(error){notice(error.message,true);}
    }
    confirm.addEventListener("click",async()=>{confirm.disabled=true;await utility(pendingClear,true);confirm.disabled=false;confirmation.close();});
    for(const [action,label] of [["copy_results","Copy matching entries"],["open_history","Open history file"],["stats","Your stats"],["clear_text","Clear text history"],["clear_audio","Clear recordings"]]){
      const button=el("button",{text:label});
      button.addEventListener("click",async()=>{
        if(action.startsWith("clear_")){pendingClear=action;confirmTitle.textContent=label+"?";
          confirmText.textContent=action==='clear_text'?"Delete local text history and live drafts. Pinned entries, notes and protected recordings stay. This cannot be undone.":"Delete all locally protected voice recordings. Saved text, pins and notes stay. This cannot be undone.";
          confirm.textContent=label;confirmation.showModal();return;}
        if(action==='copy_results'){try{notice((await call(action,{query:state.query})).message);}catch(error){notice(error.message,true);}return;}
        await utility(action);
      });actions.append(button);
    }
    const clock=el("button",{text:"Switch 12 / 24-hour time"});clock.addEventListener("click",()=>utility("clock",state.preferences.clock==='24h'?'12h':'24h'));actions.append(clock);
    const design=el("select",{"aria-label":"PDF report design"});
    for(const name of ["boardroom","modern","minimal"])design.append(el("option",{value:name,text:name[0].toUpperCase()+name.slice(1)}));
    design.addEventListener("change",()=>utility("report_design",design.value));
    const exportPanel=el("section",{class:"history-export-panel","aria-label":"Save history"});
    const exportFormat=el("select",{"aria-label":"History export format"});
    for(const [value,label] of [["txt","History as text"],["md","History as Markdown"],["srt","Subtitle draft (estimated)"],["pdf","Latest entry as PDF"]])exportFormat.append(el("option",{value,text:label}));
    const save=el("button",{text:"Save a copy",class:"primary"});
    const exportHelp=el("p",{class:"secondary history-export-help"});
    const exportStatus=el("p",{role:"status",class:"history-export-status",hidden:true});
    const receipts=el("ul",{class:"history-export-receipts","aria-label":"Saved documents this session",hidden:true});
    const olderExports=el("button",{text:"Show previous documents",class:"quiet","aria-expanded":"false",hidden:true});
    let showEarlier=false;
    olderExports.addEventListener("click",()=>{
      showEarlier=!showEarlier;olderExports.setAttribute("aria-expanded",String(showEarlier));
      olderExports.textContent=showEarlier?"Hide previous documents":`Show previous documents (${Math.max(0,receipts.children.length-1)})`;
      Array.from(receipts.children).forEach((node,index)=>node.hidden=index>0&&!showEarlier);
    });
    const designRow=el("label",{text:"PDF report design",hidden:true},[design]);
    function exportHint(){
      designRow.hidden=exportFormat.value!=="pdf";
      exportHelp.textContent=exportFormat.value==='pdf'?"Save the latest nonblank entry using the selected report design.":exportFormat.value==='srt'?"Estimated timing, starting at zero. Align this draft to your recording before use. Includes up to 20,000 recent entries.":"Save up to 20,000 recent entries. Search and pins do not change this export.";
    }
    function paintExports(result){
      state.exportActive=result.active;save.disabled=result.active;exportFormat.disabled=result.active;design.disabled=result.active;
      save.textContent=result.active?"Saving...":"Save a copy";
      exportStatus.hidden=!result.message;exportStatus.textContent=result.message;exportStatus.classList.toggle("error",!!result.error);
      receipts.hidden=!result.receipts.length;
      olderExports.hidden=result.receipts.length<2;
      olderExports.textContent=showEarlier?"Hide previous documents":`Show previous documents (${Math.max(0,result.receipts.length-1)})`;
      const signature=JSON.stringify(result.receipts);
      if(signature!==state.receiptSignature){
        state.receiptSignature=signature;receipts.replaceChildren();
        for(const [index,row] of result.receipts.entries()){
          const details=[`${row.entries.toLocaleString()} ${row.entries===1?'entry':'entries'}`];
          if(row.capped)details.push("Recent 20,000 only");
          if(row.estimated_timing)details.push("Estimated timing; align before use");
          if(row.unknown_dates)details.push(`${row.unknown_dates.toLocaleString()} ${row.unknown_dates===1?'date':'dates'} unavailable; text kept`);
          const open=el("button",{text:"Open",class:"quiet","aria-label":`Open ${row.name}`});
          const folder=el("button",{text:"Show folder",class:"quiet","aria-label":`Show folder for ${row.name}`});
          open.addEventListener("click",()=>exportCommand("open",{id:row.id}));
          folder.addEventListener("click",()=>exportCommand("folder",{id:row.id}));
          receipts.append(el("li",{hidden:index>0&&!showEarlier?true:null},[el("strong",{text:row.name}),el("small",{text:details.join(" · ")}),el("div",{class:"action-list"},[open,folder])]));
        }
      }
      clearTimeout(state.exportTimer);
      if(result.active)state.exportTimer=setTimeout(()=>exportCommand("status"),450);
    }
    async function exportCommand(command,extra={}){
      const generation=++state.exportGeneration;
      clearTimeout(state.exportTimer);
      if(command==='start'){save.disabled=true;exportFormat.disabled=true;design.disabled=true;}
      try{
        const result=await call("export",{command,...extra});
        if(generation!==state.exportGeneration||!root.isConnected)return;
        paintExports(result);
      }catch(error){
        if(generation!==state.exportGeneration||!root.isConnected)return;
        exportStatus.hidden=false;exportStatus.textContent=error.message;exportStatus.classList.add("error");
        save.disabled=!!state.exportActive;exportFormat.disabled=!!state.exportActive;design.disabled=!!state.exportActive;
        if(state.exportActive)state.exportTimer=setTimeout(()=>exportCommand("status"),900);
      }
    }
    exportFormat.addEventListener("change",exportHint);
    save.addEventListener("click",()=>exportCommand("start",{format:exportFormat.value}));
    exportPanel.append(el("div",{class:"history-export-controls"},[exportFormat,save]),designRow,exportHelp,exportStatus,receipts,olderExports);
    exportHint();options.append(exportPanel);

    options.append(actions);
    collection.append(search,tabs,options,count,list,el("div",{class:"document-pager"},[newer,older]),confirmation);
    empty();root.append(collection,reader);container.append(root);load();exportCommand("status");
    return {root,leave:async()=>true,dispose:()=>{clearTimeout(state.timer);clearTimeout(state.exportTimer);state.generation++;state.reading++;state.exportGeneration++;}};
  }
  return {history};
})();
