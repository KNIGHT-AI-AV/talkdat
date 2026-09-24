"use strict";
window.TalkDatScribe=({container,el,request,notice,changed})=>{
  const state={data:null,revision:0,sequence:0,saved:0,loaded:false,disposed:false,action:null,saving:null,timer:0,poll:0,reading:0,view:"read",libraryPage:0,librarySignature:""};
  const root=el("section",{class:"scribe-workspace","data-workspace":"scribe"});
  const source=el("select",{"aria-label":"Recording source",disabled:true},[
    el("option",{value:"both",text:"Microphone + system audio"}),el("option",{value:"microphone",text:"Microphone only"}),el("option",{value:"system",text:"System audio only"})]);
  const record=el("button",{class:"primary",text:"Start recording",disabled:true});
  const stop=el("button",{class:"quiet",text:"Stop and keep audio",hidden:true});
  const clock=el("span",{class:"scribe-clock","aria-label":"Recorded duration",text:"0:00"});
  const lamp=el("span",{class:"scribe-lamp","aria-hidden":"true"});
  const phase=el("strong",{text:"Ready when you are"});
  const input=el("p",{class:"secondary"});
  const status=el("p",{class:"scribe-status",role:"status",text:"Opening Scribe..."});
  const strip=el("div",{class:"scribe-deck"},[
    el("div",{class:"scribe-instrument","aria-hidden":"true"},[lamp,el("span",{text:"Talk DAT!"})]),
    el("div",{class:"scribe-capture"},[el("div",{class:"scribe-phase"},[phase,clock]),el("label",{text:"Record"},[source]),
      el("div",{class:"scribe-record-actions"},[record,stop])])]);
  const editor=el("textarea",{"aria-label":"Scribe notes",dir:"auto",spellcheck:true,hidden:true,placeholder:"Your conversation, ready to keep.",disabled:true});
  const paper=el("article",{class:"scribe-paper",dir:"auto","aria-label":"Notes preview"});
  const empty=el("div",{class:"scribe-empty"},[el("h2",{text:"Be in the conversation."}),el("p",{text:"Choose what to record. Scribe keeps the original audio, turns it into words on this computer, and saves notes for you to review."}),
    el("p",{class:"secondary",text:"Microphone records your selected input. System audio records what your computer plays. Choose both for separate tracks."})]);
  const edit=el("button",{class:"quiet",text:"Edit notes",disabled:true});
  const copy=el("button",{class:"quiet",text:"Copy",disabled:true});
  const save=el("button",{class:"primary",text:"Save a copy",disabled:true});
  const words=el("small",{class:"secondary",text:"No notes yet"});
  const retry=el("button",{class:"quiet",text:"Retry transcription",disabled:true});
  const originals=el("button",{class:"quiet",text:"Open originals",disabled:true});
  const permissions=el("button",{class:"quiet",text:"Mac recording permissions",hidden:true});
  const receipt=el("div",{class:"scribe-receipts"});
  const issues=el("ul",{class:"scribe-issues",hidden:true});
  const details=el("details",{class:"scribe-originals"},[el("summary",{text:"Recording and recovery"}),
    el("p",{class:"secondary",text:"Original audio stays in Talk DAT's data folder. It can contain everything heard by the selected source. Sources identify tracks, not individual speakers; transcript sections are approximately 30 seconds."}),
    issues,el("div",{class:"action-list"},[originals,retry,permissions])]);
  const aside=el("aside",{class:"scribe-keep","aria-label":"Saved notes"},[el("h2",{text:"Keep your notes"}),save,
    el("p",{class:"secondary",text:"Save a new Markdown file. Earlier notes stay intact."}),receipt,details]);
  const libraryRows=el("div",{class:"scribe-library-list"});
  const libraryStatus=el("p",{class:"secondary",role:"status"});
  const refreshLibrary=el("button",{class:"quiet",text:"Refresh recordings"});
  const openLibrary=el("button",{class:"quiet",text:"Open recording folder"});
  const previous=el("button",{class:"quiet",text:"Previous recordings",disabled:true});
  const next=el("button",{class:"quiet",text:"More recordings",disabled:true});
  const library=el("details",{class:"scribe-library"},[el("summary",{text:"Saved recordings"}),
    libraryStatus,el("div",{class:"action-list"},[refreshLibrary,openLibrary]),libraryRows,
    el("div",{class:"action-list"},[previous,next])]);
  root.append(strip,input,status,el("div",{class:"scribe-layout"},[
    el("section",{class:"scribe-notes"},[el("header",{},[el("h2",{text:"Notes"}),words,edit,copy]),empty,paper,editor]),aside]));
  root.append(library);container.append(root);
  const call=(operation,extra={})=>request("workspace",{area:"scribe",operation,...extra});
  function fail(error){state.failure=error.message;paint();notice(error.message,true);}
  function preview(){
    paper.replaceChildren();const lines=editor.value.split("\n");let offset=0;
    const more=el("button",{class:"quiet",text:"Continue reading"});
    function append(){more.remove();const end=Math.min(lines.length,offset+300);let paragraph=[];
      function flush(){if(paragraph.length){paper.append(el("p",{text:paragraph.join("\n")}));paragraph=[];}}
      while(offset<end){const line=lines[offset++];const heading=/^(#{1,3})\s+(.+)$/u.exec(line);
        if(heading){flush();paper.append(el(heading[1].length===1?"h2":"h3",{text:heading[2]}));}
        else if(!line.trim()){flush();}
        else if(line.startsWith("- ")){flush();paper.append(el("p",{class:"scribe-point",text:line.slice(2)}));}
        else {const speaker=/^\*\*([^*]+):\*\*\s*(.*)$/u.exec(line);if(speaker){flush();paper.append(el("p",{},[el("strong",{text:speaker[1]+": "}),document.createTextNode(speaker[2])]));}else paragraph.push(line.replace(/^\*([^*]+)\*$/u,"$1"));}}
      flush();if(offset<lines.length)paper.append(more);
    }
    more.onclick=append;append();
  }
  function paintFiles(){
    receipt.replaceChildren();
    const files=state.data?.receipts||[];
    if(!files.length){receipt.append(el("p",{class:"scribe-no-receipt secondary",text:"Saved files will appear here."}));return;}
    for(const [index,file] of files.entries()){
      const open=el("button",{text:"Open",class:"quiet","aria-label":`Open ${file.name}`});
      const folder=el("button",{text:"Folder",class:"quiet","aria-label":`Show folder for ${file.name}`});
      open.onclick=()=>fileAction("open_file",file.id);folder.onclick=()=>fileAction("show_folder",file.id);
      const row=el("div",{class:"scribe-receipt"},[el("strong",{text:file.name}),el("small",{class:"secondary",text:file.current?"Current notes":"Earlier notes"}),el("div",{class:"action-list"},[open,folder])]);
      if(index===0)receipt.append(row);else {let history=receipt.querySelector("details");if(!history){history=el("details",{},[el("summary",{text:"Earlier saves"})]);receipt.append(history);}history.append(row);}
    }
  }
  function paintLibrary(){
    const data=state.data||{},rows=data.library||[];
    const signature=JSON.stringify([rows,state.libraryPage,data.active,data.edited,data.draft_saved,Boolean(state.action)]);
    libraryStatus.textContent=data.library_message||"Looking for saved recordings...";
    refreshLibrary.disabled=Boolean(data.refreshing||state.action);
    if(signature===state.librarySignature)return;state.librarySignature=signature;libraryRows.replaceChildren();
    state.libraryPage=Math.min(state.libraryPage,Math.max(0,Math.floor((rows.length-1)/10)));
    const start=state.libraryPage*10;
    for(const item of rows.slice(start,start+10)){
      const button=el("button",{class:"scribe-library-entry"},[
        el("strong",{text:item.name}),el("span",{class:"secondary",text:({both:"Microphone + system audio",microphone:"Microphone",system:"System audio"})[item.source]||"Retained audio"}),
        el("small",{class:"secondary",text:item.interrupted?"Interrupted recording":item.draft?"Saved draft":"Original audio"})]);
      button.disabled=Boolean(data.active||state.action||data.edited&&!data.draft_saved);button.onclick=()=>run("restore",{id:item.id});libraryRows.append(button);
    }
    previous.disabled=start===0;next.disabled=start+10>=rows.length;
  }
  function paint(){
    const data=state.data||{},ready=state.loaded&&!state.disposed,busy=Boolean(data.active||state.action),recording=data.phase==="recording";
    source.disabled=!ready||busy;record.disabled=!ready||Boolean(state.action)||Boolean(data.active&&!recording)||data.edited||data.other_recording;
    record.textContent=recording?"Finish recording":data.active?"Working...":data.length?"New recording":"Start recording";
    stop.hidden=!data.active||data.saving;stop.disabled=Boolean(state.action);stop.textContent=data.phase==="transcribing"?"Pause transcription":"Stop and keep audio";
    lamp.classList.toggle("recording",recording);strip.classList.toggle("recording",recording);
    phase.textContent=data.edited?(data.draft_saved?"Draft saved for review":"Keeping your draft"):({idle:"Ready when you are",preparing:"Preparing local speech",recording:"Recording",stopping:"Closing audio",transcribing:"Making your notes",ready:"Saved and ready",review:"Review needed",empty:"No words returned",paused:"Stopped, originals kept",error:"Needs attention","close-failed":"Audio still closing","save-failed":"Draft kept"})[data.phase]||"Scribe";
    const seconds=Math.max(0,Number(data.seconds)||0);clock.textContent=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,"0")}`;
    clock.hidden=!seconds&&!recording;
    input.textContent=data.source==="system"?"System output only. Your microphone is not selected.":`Input: ${data.input||"Your selected microphone"}`;
    status.textContent=state.failure||(state.sequence!==state.saved?"Keeping your edits...":data.message||"Choose what to record.");
    const error=Boolean(state.failure||["error","close-failed","save-failed","review"].includes(data.phase));status.setAttribute("role",error?"alert":"status");status.classList.toggle("error",error);
    const hasText=Boolean(editor.value);words.textContent=hasText?`${editor.value.trim().split(/\s+/u).filter(Boolean).length.toLocaleString()} words`:"No notes yet";
    editor.disabled=!ready;editor.readOnly=busy;editor.spellcheck=editor.value.length<32000;
    edit.disabled=!ready||busy||!hasText;edit.textContent=state.view==="edit"?"Read notes":"Edit notes";
    editor.hidden=state.view!=="edit";paper.hidden=state.view==="edit"||!hasText;empty.hidden=hasText||state.view==="edit";
    copy.disabled=!ready||!hasText;save.disabled=!ready||busy||!hasText;
    retry.disabled=!ready||busy||data.edited||!data.originals;originals.disabled=!ready||!data.originals;
    permissions.hidden=data.platform!=="darwin";issues.replaceChildren();issues.hidden=!data.issues?.length;
    for(const problem of data.issues||[])issues.append(el("li",{text:problem}));paintLibrary();
  }
  async function read(revision){let text="",offset=0;do{const part=await call("read",{revision,offset});text+=part.text;offset=part.next;}while(offset!==null);return text;}
  async function sync(data,initial=false,attempt=0){
    if(state.disposed||data.revision<state.revision)return;
    const token=++state.reading,sequence=state.sequence;
    try{
      const refresh=initial||(!state.saving&&state.sequence===state.saved&&data.revision!==state.revision);
      const text=refresh?await read(data.revision):null;
      if(state.disposed||token!==state.reading)return;
      state.data=data;
      if(refresh&&sequence===state.sequence){editor.value=text;state.revision=data.revision;preview();}
      source.value=data.source;paint();paintFiles();changed();
    }catch(error){if(attempt<2&&!state.disposed){const latest=await call("status");if(latest.revision!==data.revision)return sync(latest,initial,attempt+1);}throw error;}
    finally{poll();}
  }
  function poll(){clearTimeout(state.poll);if(!state.disposed&&(state.data?.active||state.data?.refreshing))state.poll=setTimeout(async()=>{try{await sync(await call("status"));}catch(error){fail(error);poll();}},400);}
  function dirty(){state.failure="";state.sequence++;clearTimeout(state.timer);state.timer=setTimeout(()=>keepEdits(),350);paint();changed();}
  editor.addEventListener("input",dirty);
  async function keepEdits(){
    clearTimeout(state.timer);
    if(state.saving){if(!await state.saving)return false;return keepEdits();}
    if(state.sequence===state.saved)return settleDraft();
    if(!state.loaded)return false;
    const sequence=state.sequence,text=editor.value;
    state.saving=(async()=>{try{
      const points=Array.from(text);if(points.length>4000000)throw Error("These notes are too large. Your edits remain in the editor.");
      const transfer=await call("begin_edit",{revision:state.revision});let offset=0;
      for(let index=0;index<points.length;index+=8000){const reply=await call("append_edit",{token:transfer.token,offset,text:points.slice(index,index+8000).join("")});offset=reply.offset;}
      const data=await call("commit_edit",{token:transfer.token});state.revision=data.revision;state.saved=sequence;state.data=data;state.failure="";preview();paint();return true;
    }catch(error){fail(error);return false;}finally{state.saving=null;changed();}})();
    const okay=await state.saving;if(okay&&sequence!==state.sequence)return keepEdits();return okay&&await settleDraft();
  }
  async function settleDraft(){
    try{const deadline=Date.now()+10000;
    while(state.data?.job==="draft"&&!state.disposed&&Date.now()<deadline){
      await new Promise(resolve=>setTimeout(resolve,60));await sync(await call("status"));
    }
    if(state.data?.job==="draft"){notice("The draft is still saving. Your words remain here.",true);return false;}
    return !state.disposed;}catch(error){fail(error);return false;}
  }
  function run(operation,extra={}){
    if(state.action)return state.action;
    state.action=(async()=>{if(!await keepEdits())return;try{state.failure="";await sync(await call(operation,{...(["start","save","retry","restore"].includes(operation)?{revision:state.revision}:{}),...extra}));}catch(error){fail(error);}})();
    paint();return state.action.finally(()=>{state.action=null;paint();changed();});
  }
  record.onclick=()=>run(state.data?.phase==="recording"?"finish":"start");stop.onclick=()=>run("stop");save.onclick=()=>run("save");retry.onclick=()=>run("retry");
  source.onchange=()=>run("source",{source:source.value,config_revision:state.data.config_revision});
  copy.onclick=async()=>{if(!await keepEdits())return;try{notice((await call("copy",{revision:state.revision})).message);}catch(error){fail(error);}};
  edit.onclick=async()=>{if(!await keepEdits())return;state.view=state.view==="edit"?"read":"edit";preview();paint();if(state.view==="edit")editor.focus();};
  async function fileAction(operation,id){try{notice((await call(operation,id?{id}:{})).message);}catch(error){fail(error);}}
  refreshLibrary.onclick=()=>run("library");openLibrary.onclick=()=>fileAction("library_folder");
  previous.onclick=()=>{state.libraryPage--;paintLibrary();};next.onclick=()=>{state.libraryPage++;paintLibrary();};
  originals.onclick=()=>fileAction("originals");permissions.onclick=()=>fileAction("permission");
  root.addEventListener("keydown",event=>{if((event.ctrlKey||event.metaKey)&&event.key==="s"){event.preventDefault();if(!save.disabled)run("save");}});
  (async()=>{try{await sync(await call("open"),true);if(!state.disposed){state.loaded=true;paint();}}catch(error){fail(error);}})();
  return {root,isDirty:()=>state.sequence!==state.saved||Boolean((state.data?.edited&&!state.data?.draft_saved)||state.data?.active),
    leave:async()=>{if(state.action)await state.action;if(!await keepEdits())return false;
      if(state.data?.audio_open||(["preparing","recording","stopping"].includes(state.data?.phase)&&state.data?.active)){notice("Finish or stop the Scribe recording before leaving.",true);return false;}
      if(state.data?.edited&&!state.data?.draft_saved){notice("Save a copy of your edited notes before leaving. The recovery draft could not be saved.",true);return false;}
      return true;},
    dispose:()=>{state.disposed=true;state.reading++;clearTimeout(state.poll);clearTimeout(state.timer);}};
};
