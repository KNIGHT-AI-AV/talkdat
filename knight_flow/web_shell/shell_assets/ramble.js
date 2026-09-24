"use strict";
window.TalkDatRamble = ({container,el,request,notice,changed}) => {
  const state={data:null,revision:0,sequence:0,saved:0,saving:null,action:null,loaded:false,disposed:false,timer:0,poll:0,reading:0};
  const root=el("section",{class:"ramble-workspace","data-workspace":"ramble"});
  const record=el("button",{text:"Record",disabled:true});
  const stop=el("button",{text:"Cancel recording",class:"quiet",hidden:true});
  const finish=el("button",{text:"Finish writing",disabled:true});
  const cancel=el("button",{text:"Stop finishing",hidden:true});
  const saveDocument=el("button",{text:"Save document",class:"primary",disabled:true});
  const status=el("p",{class:"ramble-status",role:"status",text:"Opening your Ramble..."});
  const counter=el("small",{class:"secondary",text:"Your draft"});
  const copy=el("button",{text:"Copy",class:"quiet",disabled:true});
  const clear=el("button",{text:"Clear",class:"quiet",disabled:true});
  const editor=el("textarea",{"aria-label":"Ramble draft",placeholder:"A thought, a letter, a plan.\n\nRecord it here, or start writing.",spellcheck:true,dir:"auto",disabled:true});
  const original=el("textarea",{"aria-label":"Original Ramble text",readonly:true,dir:"auto",spellcheck:false});
  const originals=el("details",{class:"ramble-original workspace-options",hidden:true},[el("summary",{text:"Original text"})]);
  const restore=el("button",{text:"Restore original",class:"quiet"});
  const copyOriginal=el("button",{text:"Copy original",class:"quiet"});
  originals.append(el("p",{class:"secondary",text:"The text kept before the latest writing finish. You can return to it at any time."}),original,el("div",{class:"action-list"},[restore,copyOriginal]));
  const format=el("select",{"aria-label":"Document format",disabled:true});
  const style=el("select",{"aria-label":"PDF style",disabled:true});
  const styleLabel=el("label",{text:"Style"},[style]);
  const preview=el("div",{class:"ramble-paper","aria-hidden":"true"},[
    el("span",{class:"ramble-paper-kicker",text:"TALK DAT!"}),el("strong",{text:"Room for\na thought."}),
    el("span",{class:"ramble-paper-rule"}),el("i"),el("i"),el("i"),el("i"),el("i")]);
  const previewLabel=el("p",{class:"secondary ramble-preview-label",text:"PDF style preview"});
  const files=el("div",{class:"ramble-files"});
  const savedSection=el("section",{class:"ramble-saved",hidden:true},[el("h2",{text:"Saved documents"}),files]);
  const setup=el("p",{class:"secondary ramble-setup",hidden:true},[
    document.createTextNode("Recording and finishing need a writing model. "),
    el("button",{class:"quiet",text:"Open Formatting",onclick:()=>window.TalkDat.navigate("formatting")})]);
  const layout=el("div",{class:"ramble-layout"},[
    el("div",{class:"ramble-writing"},[el("article",{class:"ramble-editor"},[
      el("header",{},[el("h2",{text:"Draft"}),counter,copy,clear]),editor]),originals]),
    el("aside",{class:"ramble-export","aria-label":"Document design"},[
      el("h2",{text:"Your document"}),el("label",{text:"Format"},[format]),styleLabel,preview,previewLabel,savedSection])]);
  const dialog=el("dialog",{"aria-labelledby":"ramble-confirm-title"});
  const dialogTitle=el("h2",{id:"ramble-confirm-title"}),dialogText=el("p");
  const keep=el("button",{text:"Keep editing",autofocus:true}),confirm=el("button",{class:"primary"});
  let confirmation=null;
  function answer(value){const resolve=confirmation;confirmation=null;if(dialog.open)dialog.close();resolve?.(value);}
  keep.onclick=()=>answer(false);confirm.onclick=()=>answer(true);
  dialog.addEventListener("cancel",event=>{event.preventDefault();answer(false);});
  function ask(title,text,label){if(confirmation)return Promise.resolve(false);dialogTitle.textContent=title;dialogText.textContent=text;confirm.textContent=label;return new Promise(resolve=>{confirmation=resolve;dialog.showModal();});}
  dialog.append(dialogTitle,dialogText,el("div",{class:"dialog-actions"},[keep,confirm]));
  root.append(el("div",{class:"ramble-toolbar"},[record,stop,finish,cancel,saveDocument]),status,setup,layout,
    el("p",{class:"secondary ramble-session-note",text:"Your draft stays in this app session. Save a document to keep it after closing Talk DAT."}),dialog);
  container.append(root);
  const call=(operation,extra={})=>request("workspace",{area:"ramble",operation,...extra});
  function error(failure){state.failure=failure.message;paint();notice(failure.message,true);}
  function dirty(){state.failure="";state.sequence++;clearTimeout(state.timer);state.timer=setTimeout(()=>save(),350);paint();changed();}
  editor.addEventListener("input",dirty);
  for(const field of [format,style])field.addEventListener("change",dirty);
  function paint(){
    const data=state.data||{},ready=state.loaded&&!state.disposed,busy=Boolean(data.active||state.action),recording=Boolean(data.recording);
    const characters=Array.from(editor.value).length,hasText=Boolean(editor.value.trim());
    editor.spellcheck=characters<=32000;
    editor.disabled=!ready;editor.readOnly=recording||data.kind==='export';
    format.disabled=style.disabled=!ready||busy||recording;
    record.disabled=!ready||busy||data.stopping;record.textContent=data.stopping?"Finishing recording...":recording?"Finish recording":hasText?"Record more":"Record";
    stop.hidden=!recording;stop.disabled=Boolean(state.action);
    finish.disabled=!ready||busy||recording||!hasText||characters>1000000;
    saveDocument.disabled=!ready||busy||recording||!hasText||characters>1000000;
    cancel.hidden=data.kind!=='finish';cancel.disabled=Boolean(data.cancelling||state.action);
    copy.disabled=!ready||!hasText;clear.disabled=!ready||busy||recording||(!hasText&&!data.original_length);
    restore.disabled=!ready||busy||recording;
    counter.textContent=`${editor.value.trim()?editor.value.trim().split(/\s+/u).length.toLocaleString():0} words · ${characters.toLocaleString()} characters`;
    status.textContent=state.failure||(state.sequence!==state.saved?"Keeping your draft...":data.message||"Choose a format, then record or add your draft.");
    status.setAttribute("role",state.failure||data.error?"alert":"status");status.classList.toggle("error",Boolean(state.failure||data.error));
    originals.hidden=!data.original_length;
    styleLabel.hidden=preview.hidden=previewLabel.hidden=format.value!=='pdf';
    const design=state.styles?.find(item=>item.value===style.value);
    if(design){const color=values=>`rgb(${values.map(value=>Math.round(value*255)).join(",")})`;
      for(const [key,value] of [["paper",design.paper],["paper-ink",design.ink],["paper-accent",design.accent]])preview.style.setProperty("--"+key,color(value));
      const title=preview.querySelector("strong");title.style.fontFamily=design.title_font;title.style.fontSize=`${design.title_size*.8}px`;title.style.textTransform=design.caps?"uppercase":"none";
      preview.style.textAlign=design.center?"center":"left";preview.style.padding=`${design.margin*.35}px`;preview.querySelector(".ramble-paper-rule").hidden=!design.rule;}
    previewLabel.textContent=`${style.selectedOptions[0]?.textContent||"PDF"} style preview`;
  }
  async function read(part,revision,id){let value="",offset=0;do{const row=await call("read",{part,revision,offset,id});value+=row.text;offset=row.next;}while(offset!==null);return value;}
  function paintFiles(){files.replaceChildren();savedSection.hidden=!state.data?.exports?.length;
    for(const file of state.data?.exports||[]){const open=el("button",{text:"Open",class:"quiet","aria-label":`Open ${file.name}`});const folder=el("button",{text:"Show folder",class:"quiet"});
      open.onclick=()=>fileAction("open_export",file.id);folder.onclick=()=>fileAction("show_folder",file.id);
      files.append(el("div",{class:"ramble-saved-file"},[el("strong",{text:file.name}),el("small",{class:"secondary",text:file.revision===state.revision?"Current draft":"Earlier draft"}),el("div",{class:"action-list"},[open,folder])]));}}
  async function fileAction(operation,id){try{notice((await call(operation,{id})).message);}catch(failure){error(failure);}}
  async function sync(data,initial=false,attempt=0){
    if(state.disposed||(!initial&&data.revision<state.revision))return;
    try {
    const reading=++state.reading,sequence=state.sequence;
    const refresh=initial||(!state.saving&&state.sequence===state.saved&&data.revision!==state.revision);
    state.data=data;
    const text=refresh?await read("draft",data.revision):null;
    const refreshOriginal=data.original_id!==state.originalId;
    const source=refreshOriginal&&data.original_length?await read("original",data.revision,data.original_id):"";
    if(state.disposed||reading!==state.reading)return;
    // Publish the draft and its original together after both reads succeed.
    if(refresh&&sequence===state.sequence){editor.value=text;state.revision=data.revision;format.value=data.format;style.value=data.style;}
    if(refreshOriginal){original.value=source;state.originalId=data.original_id;}
    paint();paintFiles();changed();
    }catch(failure){
      // A fast worker can finish between the status reply and the chunk read.
      // Refresh that snapshot instead of stranding the page in its busy state.
      if(attempt<2&&!state.disposed){const latest=await call("status");
        if(latest.revision!==data.revision||latest.original_id!==data.original_id)return sync(latest,initial,attempt+1);}
      throw failure;
    }finally{poll();}
  }
  function poll(){clearTimeout(state.poll);if(!state.disposed&&(state.data?.active||state.data?.recording))state.poll=setTimeout(async()=>{try{await sync(await call("status"));}catch(failure){error(failure);poll();}},600);}
  async function save(){
    clearTimeout(state.timer);
    if(state.saving){if(!await state.saving)return false;return save();}
    if(state.sequence===state.saved)return true;
    if(!state.loaded)return false;
    const sequence=state.sequence,text=editor.value,formatValue=format.value,styleValue=style.value;
    state.saving=(async()=>{try{
      const chunks=Array.from(text);if(chunks.length>1000000)throw Error("The draft is too large. Copy your edits before leaving.");
      const transfer=await call("begin_edit",{revision:state.revision});let offset=0;
      for(let index=0;index<chunks.length;index+=16000){const answer=await call("append_edit",{token:transfer.token,offset,text:chunks.slice(index,index+16000).join("")});offset=answer.offset;}
      let data=await call("commit_edit",{token:transfer.token});state.revision=data.revision;
      if(data.format!==formatValue||data.style!==styleValue)data=await call("options",{format:formatValue,style:styleValue});
      state.failure="";state.saved=sequence;state.data=data;paint();paintFiles();poll();return true;
    }catch(failure){error(failure);return false;}finally{state.saving=null;changed();}})();
    const okay=await state.saving;
    if(okay&&state.sequence!==state.saved)return save();
    return okay;
  }
  function run(operation,extra={}){
    if(state.action)return state.action;
    state.action=(async()=>{if(!await save())return;try{state.failure="";await sync(await call(operation,{revision:state.revision,...extra}));}catch(failure){error(failure);}})();
    paint();return state.action.finally(()=>{state.action=null;paint();});
  }
  record.onclick=()=>run(state.data?.recording?"speech_stop":"speech_start");
  stop.onclick=async()=>{if(await ask("Cancel this recording?","Keep the previous draft. This recording will not be added to it.","Cancel recording"))await run("speech_cancel");};
  finish.onclick=()=>run("finish");cancel.onclick=()=>run("cancel_finish");saveDocument.onclick=()=>run("export");
  async function copyText(part){if(!await save())return;try{notice((await call("copy",{part,revision:state.revision,id:state.originalId})).message);}catch(failure){error(failure);}}
  copy.onclick=()=>copyText("draft");copyOriginal.onclick=()=>copyText("original");
  clear.onclick=async()=>{if(await ask("Clear this draft?","Clear the current draft and its original text. Documents already saved stay on your computer.","Clear draft"))await run("clear",{confirmed:true});};
  restore.onclick=async()=>{if(await ask("Restore original text?","Replace the current editor text with the version kept before finishing. Copy any newer edits you want to keep first.","Restore original"))await run("restore_original");};
  root.addEventListener("keydown",event=>{if((event.ctrlKey||event.metaKey)&&event.key==='s'){event.preventDefault();if(!saveDocument.disabled)run("export");}});
  async function open(){try{const data=await call("open");if(state.disposed)return;
    for(const item of data.formats)format.append(el("option",{value:item.value,text:item.label}));
    state.styles=data.styles;for(const item of data.styles)style.append(el("option",{value:item.value,text:item.label}));
    setup.hidden=data.writing_ready;await sync(data,true);state.loaded=true;paint();
  }catch(failure){error(failure);}}
  open();
  return {root,isDirty:()=>state.sequence!==state.saved||Boolean(state.data?.recording||state.data?.active),
    leave:async()=>{if(confirmation)return false;if(state.action)await state.action;if(!await save())return false;
      if(state.data?.recording){notice("Finish or cancel the Ramble recording before leaving. Your draft stays here.",true);return false;}
      if(state.data?.active){notice("Wait for the document operation to finish, or stop finishing. Your draft stays here.",true);return false;}
      return true;},
    dispose:()=>{state.disposed=true;clearTimeout(state.poll);clearTimeout(state.timer);state.reading++;answer(false);}};
};
