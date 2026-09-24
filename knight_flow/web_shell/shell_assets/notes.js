"use strict";
window.TalkDatNotes = ({container,el,request,notice,changed}) => {
  const state={note:null,original:null,dirty:false,saving:null,timer:0,loading:0,disposed:false,failed:false};
  const root=el("section",{class:"document-workspace notes-workspace","data-workspace":"scratchpad"});
  const collection=el("div",{class:"document-collection"});
  const list=el("div",{class:"document-list","aria-label":"Notes",role:"group"});
  const search=el("input",{type:"search",placeholder:"Find a note","aria-label":"Search notes"});
  const add=el("button",{text:"New note"});
  const count=el("p",{class:"secondary"});
  const reader=el("article",{class:"document-reader","aria-label":"Note editor"});
  const status=el("p",{class:"note-status secondary",role:"status"});
  const title=el("input",{type:"text",maxlength:64,"aria-label":"Note title",class:"note-title",disabled:true});
  const body=el("textarea",{"aria-label":"Note text",class:"note-editor",spellcheck:"true",disabled:true});
  const saveButton=el("button",{text:"Save"});
  const copy=el("button",{text:"Copy full note",class:"quiet"});
  const saveCopy=el("button",{text:"Save a copy",class:"quiet",hidden:true});
  const remove=el("button",{text:"Delete note",class:"quiet"});
  const back=el("button",{text:"Back to notes",class:"quiet reader-back"});
  const options=el("details",{class:"workspace-options"},[el("summary",{text:"Files and font"})]);
  const importButton=el("button",{text:"Import a note"});
  const font=el("select",{"aria-label":"Note font"});
  const fileActions=el("div",{class:"action-list"},[importButton]);
  for(const [format,label] of [["txt","Export text"],["md","Export Markdown"]]){
    const button=el("button",{text:label});
    button.addEventListener("click",async()=>{if(await leave()){try{const result=await call("export",{id:state.note.id,format});if(result.message)notice(result.message);}catch(error){notice(error.message,true);}}});fileActions.append(button);
  }
  options.append(fileActions,font);
  let notes=[],total=0,searchTimer=0;
  const call=(operation,extra={})=>request("workspace",{area:"scratchpad",operation,...extra});
  function markDirty() {
    if(!state.note)return;
    state.dirty=title.value!==state.original.title||body.value!==state.original.text;
    state.failed=false;saveCopy.hidden=true;
    status.textContent=state.dirty?"Unsaved changes":"Saved on this computer.";
    changed();clearTimeout(state.timer);
    if(state.dirty)state.timer=setTimeout(()=>save(),650);
  }
  async function save(asCopy=false) {
    clearTimeout(state.timer);
    if(state.saving){await state.saving;if(state.dirty&&!state.failed)return save(asCopy);return !state.dirty;}
    if(!state.note||(!state.dirty&&!asCopy))return true;
    const captured={id:state.note.id,revision:state.note.revision,title:title.value,text:body.value};
    let token;
    state.saving=(async()=>{
      saveButton.disabled=true;saveCopy.disabled=true;status.textContent="Saving on this computer…";
      try {
        ({token}=await call("begin_save",{id:captured.id,revision:captured.revision,title:captured.title,as_copy:asCopy}));
        // Offsets count Unicode scalars on both sides of the native boundary.
        const characters=Array.from(captured.text);
        for(let offset=0;offset<characters.length;offset+=16000)
          await call("append_save",{token,offset,text:characters.slice(offset,offset+16000).join("")});
        const result=await call("finish_save",{token});
        if(title.value===captured.title)title.value=result.title;
        state.note=result;state.original={title:result.title,text:captured.text};
        state.dirty=title.value!==result.title||body.value!==captured.text;
        state.failed=false;saveCopy.hidden=true;
        status.textContent=state.dirty?"New changes are waiting to save.":result.message;
        await loadList();changed();
        return !state.dirty;
      }catch(error){
        state.failed=true;saveCopy.hidden=false;
        status.textContent=error.message;notice(error.message,true);changed();
        if(token)await call("cancel_save",{token}).catch(()=>{});
        return false;
      }finally{
        saveButton.disabled=false;saveCopy.disabled=false;
        state.saving=null;
        if(state.dirty&&!state.failed&&!state.disposed)state.timer=setTimeout(()=>save(),650);
      }
    })();
    return state.saving;
  }
  async function leave(){if(await save())return true;body.focus();return false;}
  function renderList(){
    list.replaceChildren();
    for(const note of notes){
      const button=el("button",{class:"document-entry","data-note":note.id,"aria-pressed":state.note?.id===note.id},[
        el("strong",{text:note.title}),el("span",{text:note.preview||"Start a thought here."}),el("small",{text:note.updated_at})]);
      button.addEventListener("click",async()=>{if(await leave())await select(note,true);});list.append(button);
    }
    count.textContent=search.value?`${notes.length} matching ${notes.length===1?"note":"notes"}`:`${total} ${total===1?"note":"notes"} saved here`;
    add.disabled=total>=99;
  }
  let listGeneration=0;
  async function loadList(){const generation=++listGeneration;const result=await call("list",{query:search.value});if(generation!==listGeneration||state.disposed)return result;notes=result.notes;total=result.total;renderList();
    if(result.fonts){font.replaceChildren(...result.fonts.available.map(family=>el("option",{value:family,text:family})));font.value=result.fonts.selected;body.style.fontFamily=JSON.stringify(result.fonts.selected);font.hidden=false;}else font.hidden=true;
    return result;}
  async function select(note,focus=false){
    const generation=++state.loading;
    title.disabled=true;body.disabled=true;
    status.textContent="Opening your note…";
    let text="",offset=0;
    try {
      do {
        const result=await call("read",{id:note.id,revision:note.revision,offset});
        if(generation!==state.loading||state.disposed)return;
        text+=result.text;offset=result.next;
      }while(offset!==null);
      state.note=note;state.original={title:note.title,text};state.dirty=false;state.failed=false;
      title.value=note.title;body.value=text;
      body.readOnly=!note.editable;title.readOnly=!note.editable;
      status.textContent=note.editable?"Saved on this computer.":"This very long note is read-only here. You can still copy or export it in full.";
      saveCopy.hidden=true;root.classList.add("reading");renderList();changed();
    }catch(error){status.textContent=error.message;notice(error.message,true);}
    finally{title.disabled=false;body.disabled=false;if(focus)body.focus({preventScroll:true});}
  }
  title.addEventListener("input",markDirty);body.addEventListener("input",markDirty);
  saveButton.addEventListener("click",()=>save());saveCopy.addEventListener("click",()=>save(true));
  copy.addEventListener("click",async()=>{if(await leave()){try{notice((await call("copy",{id:state.note.id})).message);}catch(error){notice(error.message,true);}}});
  back.addEventListener("click",async()=>{if(await leave()){root.classList.remove("reading");list.querySelector('[aria-pressed="true"]')?.focus();}});
  add.addEventListener("click",async()=>{if(await leave()){try{const note=await call("new");await loadList();await select(note,true);}catch(error){notice(error.message,true);}}});
  search.addEventListener("input",()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadList().catch(error=>notice(error.message,true)),180);});
  font.addEventListener("change",async()=>{try{await call("font",{family:font.value});body.style.fontFamily=JSON.stringify(font.value);}catch(error){notice(error.message,true);}});
  importButton.addEventListener("click",async()=>{if(await leave()){try{const note=await call("import");if(!note.cancelled){search.value="";await loadList();await select(note,true);}}catch(error){notice(error.message,true);}}});
  const dialog=el("dialog",{class:"note-delete-dialog","aria-labelledby":"note-delete-title"});
  const cancel=el("button",{text:"Keep note"});const confirm=el("button",{text:"Delete note"});
  dialog.append(el("h2",{id:"note-delete-title",text:"Delete this note?"}),el("p",{text:"This removes the saved note from this computer. This cannot be undone."}),el("div",{class:"action-list"},[cancel,confirm]));
  cancel.addEventListener("click",()=>dialog.close());
  remove.addEventListener("click",async()=>{if(await leave())dialog.showModal();});
  confirm.addEventListener("click",async()=>{
    confirm.disabled=true;
    try {await call("delete",{id:state.note.id,revision:state.note.revision});dialog.close();const result=await loadList();await select(notes.find(n=>n.id===result.selected)||notes[0]);}
    catch(error){notice(error.message,true);}finally{confirm.disabled=false;}
  });
  body.addEventListener("keydown",event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="s"){event.preventDefault();save();}});
  reader.append(el("header",{class:"document-actions"},[back,copy,saveButton]),title,body,status,
    el("footer",{class:"document-actions"},[saveCopy,remove]),dialog);
  collection.append(search,el("div",{class:"action-list"},[add]),options,count,list);root.append(collection,reader);container.append(root);
  loadList().then(result=>select(notes.find(n=>n.id===result.selected)||notes[0])).catch(error=>{status.textContent=error.message;notice(error.message,true);});
  return {root,isDirty:()=>state.dirty||Boolean(state.saving),save,leave,
    dispose:()=>{state.disposed=true;state.loading++;clearTimeout(state.timer);clearTimeout(searchTimer);}};
};
