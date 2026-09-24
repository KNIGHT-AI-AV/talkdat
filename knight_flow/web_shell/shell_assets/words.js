"use strict";
window.TalkDatWords = ({container,el,request,notice,changed}) => {
  const modes={vocabulary:{label:"Words",add:"Add word",first:"Word or phrase",second:"Sounds like (optional)",hint:"One spoken spelling per line. Leave blank if you are not sure."},
    replacements:{label:"Replacements",add:"Add replacement",first:"Heard as",second:"Replace with",hint:"Leave Replace with empty to remove the phrase."},
    snippets:{label:"Snippets",add:"Add snippet",first:"Spoken trigger",second:"Saved text",hint:"Say a distinctive phrase to insert this saved text."}};
  const state={collection:"vocabulary",query:"",offset:0,next:null,revision:null,id:"",original:"",dirty:false,saving:false,deleting:false,disposed:false,generation:0,reading:0};
  const root=el("section",{class:"words-workspace","data-workspace":"words"});
  const switcher=el("div",{class:"segmented",role:"group","aria-label":"Word collections"});
  const panels=el("div",{class:"document-workspace"});
  const collection=el("div",{class:"document-collection"});
  const reader=el("article",{class:"document-reader","aria-label":"Vocabulary editor"});
  const search=el("input",{type:"search","aria-label":"Search saved words",placeholder:"Find a word, trigger or phrase",maxlength:256});
  const add=el("button",{text:"Add word",class:"primary",disabled:true});
  const refresh=el("button",{text:"Refresh list",class:"quiet"});
  const list=el("div",{class:"document-list","aria-label":"Saved entries"});
  const count=el("p",{class:"secondary",role:"status"});
  const older=el("button",{text:"Next",class:"quiet",disabled:true});
  const newer=el("button",{text:"Previous",class:"quiet",disabled:true});
  const back=el("button",{text:"Back to list",class:"quiet reader-back"});
  const title=el("h2",{text:"Your words, remembered"});
  const firstLabel=el("label",{for:"word-first",text:modes.vocabulary.first});
  const first=el("input",{id:"word-first",type:"text",maxlength:512,autocomplete:"off",disabled:true});
  const secondLabel=el("label",{for:"word-second",text:modes.vocabulary.second});
  const second=el("textarea",{id:"word-second",rows:5,maxlength:32000,disabled:true});
  const hint=el("p",{class:"secondary",text:modes.vocabulary.hint});
  const enabled=el("input",{type:"checkbox",id:"word-enabled"});enabled.checked=true;
  const enabledRow=el("label",{for:"word-enabled",class:"word-enable",hidden:true},[enabled,document.createTextNode("Enable this snippet")]);
  const status=el("p",{class:"note-status",role:"status",text:"Choose an entry or add one."});
  const saveButton=el("button",{text:"Save entry",class:"primary",disabled:true});
  const remove=el("button",{text:"Delete entry",class:"quiet",hidden:true});
  let searchTimer=0, leavePending=null, loaded=false, practiceTimer=0, practising=false, utilityBusy=false, saveTask=null;
  const call=(operation,extra={})=>request("workspace",{area:"words",operation,collection:state.collection,...extra});
  const utility=(operation,extra={})=>request("workspace",{area:"words",operation,...extra});
  function record(){return state.collection==="vocabulary"?{text:first.value,sounds_like:second.value.split("\n").map(s=>s.trim()).filter(Boolean)}:
    state.collection==="replacements"?{from:first.value,to:second.value}:{trigger:first.value,text:second.value,enabled:enabled.checked};}
  function updateDirty(){state.dirty=JSON.stringify(record())!==state.original;saveButton.disabled=!loaded||state.saving||!state.dirty;
    status.setAttribute("role","status");status.textContent=state.dirty?"Unsaved entry. Save when you are ready.":"Saved on this computer.";
    practiceButton.disabled=!state.id||state.dirty;changed();}
  function fill(value,id,revision){state.id=id;state.revision=revision;first.value=value.text||"";
    if(state.collection==="vocabulary")second.value=(value.sounds_like||[]).join("\n");
    else if(state.collection==="replacements"){first.value=value.from||"";second.value=value.to||"";}
    else {first.value=value.trigger||"";second.value=value.text||"";enabled.checked=value.enabled!==false;}
    state.original=JSON.stringify(record());state.dirty=false;loaded=true;first.disabled=state.saving;second.disabled=state.saving;saveButton.disabled=true;remove.hidden=!id;
    status.textContent=id?"Saved on this computer.":"Add the words you want Talk DAT to use.";title.textContent=id?"Edit "+(state.collection==="vocabulary"?"word":state.collection==="snippets"?"snippet":"replacement"):modes[state.collection].add;
    status.setAttribute("role","status");practiceButton.hidden=state.collection!=="vocabulary";practiceButton.disabled=!id;
    panels.classList.add("reading");changed();}
  async function load(){const generation=++state.generation;
    count.textContent="Loading your saved entries...";
    try {const result=await call("list",{query:state.query,offset:state.offset});
      if(state.disposed||generation!==state.generation)return;
      state.listRevision=result.revision;state.next=result.next;newer.disabled=state.offset===0;older.disabled=result.next===null;add.disabled=false;
      list.replaceChildren();count.textContent=result.total?`${result.offset+1} to ${result.offset+result.entries.length} of ${result.total}`:"No matching entries. Add one to get started.";
      if(result.uneditable)count.textContent+=` ${result.uneditable} older entries are kept unchanged; export your pack to review them.`;
      for(const row of result.entries){const button=el("button",{class:"document-entry","aria-pressed":row.id===state.id},[
        el("strong",{text:row.label}),el("span",{text:row.detail|| (row.learned?"Learned spelling":"Saved spelling")}),
        row.enabled===false?el("small",{text:"Disabled"}):null]);
        button.addEventListener("click",async()=>{if(await leave())await open(row.id,result.revision);});list.append(button);}
    }catch(error){if(!state.disposed&&generation===state.generation){count.textContent=error.message;notice(error.message,true);}}
  }
  async function open(id,revision){const reading=++state.reading;first.disabled=true;second.disabled=true;saveButton.disabled=true;
    try {const result=await call("read",{id,revision});if(state.disposed||reading!==state.reading)return;fill(result.record,result.id,result.revision);first.focus();}
    catch(error){status.textContent=error.message;notice(error.message,true);if(loaded){first.disabled=false;second.disabled=false;updateDirty();}}}
  function save(){if(saveTask)return saveTask;if(!state.dirty)return Promise.resolve(true);
    state.saving=true;first.disabled=true;second.disabled=true;enabled.disabled=true;saveButton.disabled=true;remove.disabled=true;status.textContent="Saving entry...";changed();
    saveTask=(async()=>{try{const result=await call("put",{id:state.id,revision:state.revision,record:record()});
      fill(result.record,result.id,result.revision);await load();await optionsState();notice(result.message);return true;
    }catch(error){status.textContent=error.message;status.setAttribute("role","alert");notice(error.message,true);return false;}
    finally{state.saving=false;saveTask=null;first.disabled=false;second.disabled=false;enabled.disabled=false;remove.disabled=false;saveButton.disabled=!state.dirty;changed();}})();return saveTask;}
  const leaveDialog=el("dialog",{"aria-labelledby":"word-leave-title"});
  const stay=el("button",{text:"Keep editing",autofocus:true}),discard=el("button",{text:"Discard draft"}),saveLeave=el("button",{text:"Save entry",class:"primary"});
  leaveDialog.append(el("h2",{id:"word-leave-title",text:"Keep this entry?"}),el("p",{text:"Save the changes before leaving this entry, or discard this draft."}),el("div",{class:"dialog-actions"},[stay,discard,saveLeave]));
  function finishLeave(value){const pending=leavePending;leavePending=null;leaveDialog.close();pending?.(value);}
  stay.onclick=()=>finishLeave(false);discard.onclick=()=>{state.dirty=false;changed();finishLeave(true);};
  saveLeave.onclick=async()=>{saveLeave.disabled=true;const success=await save();saveLeave.disabled=false;finishLeave(success);};
  leaveDialog.addEventListener("cancel",event=>{event.preventDefault();finishLeave(false);});
  async function leave(){if(saveTask&&!await saveTask)return false;if(state.deleting||practising||utilityBusy)return false;if(!state.dirty)return true;if(leavePending)return false;
    return new Promise(resolve=>{leavePending=resolve;leaveDialog.showModal();});}
  function newEntry(){state.reading++;const value=state.collection==="vocabulary"?{text:"",sounds_like:[]}:state.collection==="replacements"?{from:"",to:""}:{trigger:"",text:"",enabled:true};fill(value,"",state.listRevision);first.focus();}
  for(const [key,mode] of Object.entries(modes)){const button=el("button",{text:mode.label,"aria-pressed":key===state.collection});
    button.onclick=async()=>{if(key===state.collection||!await leave())return;state.collection=key;state.query="";state.offset=0;search.value="";state.id="";loaded=false;
      state.reading++;first.value="";second.value="";first.disabled=true;second.disabled=true;remove.hidden=true;saveButton.disabled=true;
      title.textContent="Choose a saved entry";status.textContent="Choose an entry or add one.";practiceButton.hidden=key!=="vocabulary";practiceButton.disabled=true;
      firstLabel.textContent=mode.first;secondLabel.textContent=mode.second;hint.textContent=mode.hint;enabledRow.hidden=key!=="snippets";add.textContent=mode.add;search.setAttribute("aria-label","Search saved "+mode.label.toLowerCase());
      for(const other of switcher.children)other.setAttribute("aria-pressed",String(other===button));
      panels.classList.remove("reading");await load();};switcher.append(button);}
  add.onclick=async()=>{if(await leave())newEntry();};refresh.onclick=async()=>{await load();await optionsState();
    if(!loaded)return;
    if(!state.id){state.revision=state.listRevision;return;}
    try{const latest=await call("read",{id:state.id,revision:state.listRevision});
      if(JSON.stringify(latest.record)===state.original){state.revision=latest.revision;if(state.dirty)status.textContent="List refreshed. Your draft is ready to save.";}}
    catch(error){if(state.dirty){status.textContent="This saved entry changed elsewhere. Your draft is kept here. Copy any text you need before selecting the latest entry.";notice(status.textContent,true);}}};
  first.addEventListener("input",updateDirty);second.addEventListener("input",updateDirty);enabled.addEventListener("change",updateDirty);
  saveButton.onclick=()=>save();back.onclick=async()=>{if(await leave())panels.classList.remove("reading");};
  search.addEventListener("input",()=>{state.query=search.value;state.offset=0;clearTimeout(searchTimer);searchTimer=setTimeout(load,180);});
  older.onclick=()=>{if(state.next!==null){state.offset=state.next;load();}};newer.onclick=()=>{state.offset=Math.max(0,state.offset-40);load();};
  const deleteDialog=el("dialog",{"aria-labelledby":"word-delete-title"});const keep=el("button",{text:"Keep entry",autofocus:true}),confirm=el("button",{text:"Delete entry"});
  deleteDialog.append(el("h2",{id:"word-delete-title",text:"Delete this saved entry?"}),el("p",{text:"This removes the saved spelling, replacement or snippet. Existing dictations stay as they are."}),el("div",{class:"dialog-actions"},[keep,confirm]));
  keep.onclick=()=>deleteDialog.close();remove.onclick=async()=>{if(await leave())deleteDialog.showModal();};
  deleteDialog.addEventListener("cancel",event=>{if(state.deleting)event.preventDefault();});
  confirm.onclick=async()=>{state.deleting=true;confirm.disabled=true;keep.disabled=true;try{await call("delete",{id:state.id,revision:state.revision,confirmed:true});deleteDialog.close();state.id="";await load();newEntry();notice("Entry deleted.");}catch(error){status.textContent=error.message;notice(error.message,true);deleteDialog.close();}finally{state.deleting=false;confirm.disabled=false;keep.disabled=false;}};
  reader.addEventListener("keydown",event=>{if((event.metaKey||event.ctrlKey)&&event.key==="Enter"){event.preventDefault();save();}});
  const options=el("details",{class:"workspace-options words-options"},[el("summary",{text:"Learning, suggestions and vocabulary packs"})]);
  const learning=el("select",{id:"word-learning","aria-label":"Learn from copied words",disabled:true});
  for(const [value,label] of [["off","Off"],["offer","Ask before adding"],["auto-on-second","Learn distinctive spellings; ask about other words"]])learning.append(el("option",{value,text:label}));
  const learningHint=el("p",{class:"secondary",text:"When enabled, Talk DAT checks words you copy after dictation. Ask before adding always asks first. The automatic option can learn distinctive spellings immediately; repeated ordinary words are offered for your approval. This runs on this computer."});
  const suggestionButton=el("button",{text:"Suggest from history"}),importButton=el("button",{text:"Import pack..."}),exportButton=el("button",{text:"Export pack..."});
  const suggestions=el("div",{class:"word-suggestions",role:"group","aria-label":"Suggested words"});
  const packRow=el("div",{class:"action-list","aria-label":"Industry vocabulary"});
  async function optionsState(){try{const result=await utility("options");if(state.disposed)return;learning.value=result.mode;learning.disabled=false;learning.dataset.revision=result.revision;
    if(!packRow.children.length)for(const pack of result.packs){const button=el("button",{text:pack.label,class:"quiet"});button.onclick=()=>previewPack(pack.id);packRow.append(button);}}
    catch(error){notice(error.message,true);}}
  learning.onchange=async()=>{if(!await leave()){await optionsState();return;}utilityBusy=true;learning.disabled=true;
    try{const result=await utility("learning",{mode:learning.value,revision:learning.dataset.revision});state.revision=result.revision;notice("Learning preference saved.");await load();}
    catch(error){notice(error.message,true);}finally{utilityBusy=false;await optionsState();}};
  suggestionButton.onclick=async()=>{suggestionButton.disabled=true;try{const result=await utility("suggestions");suggestions.replaceChildren();
    if(!result.words.length)suggestions.append(el("p",{class:"secondary",text:"No new suggestions yet. Names used repeatedly in saved history appear here."}));
    else{suggestions.append(el("p",{class:"secondary",text:"Choose a suggestion to review it. Nothing is added until you save."}));for(const word of result.words){const button=el("button",{text:word,class:"quiet"});button.onclick=async()=>{if(!await leave())return;
      const tab=[...switcher.children].find(button=>button.textContent==="Words");if(state.collection!=="vocabulary")await tab.onclick();
      newEntry();first.value=word;updateDirty();first.focus();};suggestions.append(button);}}}
    catch(error){notice(error.message,true);}finally{suggestionButton.disabled=false;}};
  const packDialog=el("dialog",{"aria-labelledby":"word-pack-title"});const packDetail=el("p"),packError=el("p",{role:"alert"});
  const packCancel=el("button",{text:"Keep current vocabulary",autofocus:true}),packApply=el("button",{text:"Add these entries",class:"primary"});let packToken="";
  packDialog.append(el("h2",{id:"word-pack-title",text:"Add this vocabulary pack?"}),packDetail,el("p",{text:"Existing entries stay unchanged. Duplicate spellings, replacement phrases and snippet triggers are skipped."}),packError,el("div",{class:"dialog-actions"},[packCancel,packApply]));
  packCancel.onclick=()=>packDialog.close();packDialog.addEventListener("cancel",event=>{if(utilityBusy)event.preventDefault();});
  packDialog.addEventListener("close",()=>{packToken="";utility("pack_cancel").catch(()=>{});});
  async function previewPack(source){if(!await leave())return;utilityBusy=true;try{const result=await utility("pack_preview",{source});if(result.cancelled)return;
    packToken=result.token;packDetail.textContent=`${result.counts.words} words, ${result.counts.replacements} replacements and ${result.counts.snippets} snippets will be added.`;packError.textContent="";packDialog.showModal();}
    catch(error){notice(error.message,true);}finally{utilityBusy=false;}}
  importButton.onclick=()=>previewPack("file");exportButton.onclick=async()=>{if(!await leave())return;utilityBusy=true;exportButton.disabled=true;
    try{const result=await utility("export");notice(result.message);}catch(error){notice(error.message,true);}finally{utilityBusy=false;exportButton.disabled=false;}};
  packApply.onclick=async()=>{utilityBusy=true;packApply.disabled=true;packCancel.disabled=true;try{const result=await utility("pack_apply",{token:packToken,confirmed:true});packDialog.close();state.id="";state.offset=0;await load();newEntry();await optionsState();notice(result.message);}
    catch(error){packError.textContent=error.message;}finally{utilityBusy=false;packApply.disabled=false;packCancel.disabled=false;}};
  options.append(el("label",{for:"word-learning",text:"Learn from copied words"}),learning,learningHint,
    el("div",{class:"action-list"},[suggestionButton,importButton,exportButton]),suggestions,el("p",{class:"secondary",text:"Industry packs"}),packRow);
  const practiceButton=el("button",{text:"Record pronunciation",class:"quiet",disabled:true});
  const practiceDialog=el("dialog",{"aria-labelledby":"word-practice-title"});const practiceStatus=el("p",{role:"status"});
  const stopPractice=el("button",{text:"Cancel practice",autofocus:true});
  practiceDialog.append(el("h2",{id:"word-practice-title",text:"Say it three times"}),el("p",{text:"Use your selected microphone. Each take lasts 2½ seconds, with a short pause between takes. Recordings stay on this computer and the local speech model learns how it hears your word."}),practiceStatus,stopPractice);
  async function checkPractice(){clearTimeout(practiceTimer);try{const result=await utility("practice_status");if(state.disposed)return;practiceStatus.textContent=result.message;practising=result.active;changed();
    if(result.active)practiceTimer=setTimeout(checkPractice,350);else{stopPractice.textContent="Done";stopPractice.disabled=false;await load();await optionsState();const selected=[...list.children].find(button=>button.querySelector("strong")?.textContent===first.value);if(selected)await selected.click();}}
    catch(error){practiceStatus.textContent=error.message;stopPractice.disabled=false;}}
  practiceButton.onclick=async()=>{if(state.dirty||!state.id)return;practising=true;changed();practiceStatus.textContent="Preparing...";stopPractice.textContent="Cancel practice";stopPractice.disabled=false;practiceDialog.showModal();
    try{await utility("practice_start",{id:state.id,revision:state.revision});await checkPractice();}
    catch(error){practising=false;practiceStatus.textContent=error.message;stopPractice.textContent="Done";changed();}};
  stopPractice.onclick=async()=>{if(!practising){practiceDialog.close();return;}stopPractice.disabled=true;try{await utility("practice_cancel");practiceStatus.textContent="Stopping practice...";await checkPractice();}catch(error){practiceStatus.textContent=error.message;stopPractice.disabled=false;}};
  practiceDialog.addEventListener("cancel",event=>{if(practising){event.preventDefault();stopPractice.click();}});
  reader.append(el("header",{class:"document-actions"},[back,title]),firstLabel,first,secondLabel,second,hint,enabledRow,status,el("div",{class:"action-list words-editor-actions"},[saveButton,remove,practiceButton]));
  collection.append(search,el("div",{class:"action-list"},[add,refresh]),count,list,el("div",{class:"document-pager"},[newer,older]));
  panels.append(collection,reader);root.append(switcher,options,panels,leaveDialog,deleteDialog,packDialog,practiceDialog);container.append(root);load();optionsState();
  return {root,isDirty:()=>state.dirty||state.saving||state.deleting||practising||utilityBusy,leave,dispose:()=>{state.disposed=true;state.generation++;state.reading++;clearTimeout(searchTimer);clearTimeout(practiceTimer);if(practising)utility("practice_cancel").catch(()=>{});finishLeave(false);}};
};
