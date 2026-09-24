"use strict";
window.TalkDatAppProfiles = ({container,el,request,notice,changed}) => {
  const state={entries:[],revision:null,id:"",original:"",dirty:false,busy:false,disposed:false,generation:0,loaded:false,style:null};
  const root=el("section",{class:"app-profiles-workspace","data-workspace":"app-profiles"});
  const layout=el("div",{class:"app-profiles-layout"});
  const collection=el("section",{class:"app-profiles-collection","aria-label":"Saved app preferences"});
  const search=el("input",{type:"search","aria-label":"Find an app preference",placeholder:"Find an app",maxlength:128});
  const add=el("button",{text:"Add app",class:"primary",disabled:true});
  const refresh=el("button",{text:"Refresh list"});
  const count=el("p",{class:"secondary",role:"status"});
  const list=el("div",{class:"document-list"});
  const editor=el("form",{class:"app-profiles-editor","aria-label":"App preference editor"});
  const title=el("h2",{text:"Choose an app"});
  const status=el("p",{class:"profile-status",role:"status",text:"Add an app or choose one from the list."});
  const match=el("input",{id:"profile-match",type:"text",maxlength:128,placeholder:"Slack, Chrome or another app",autocomplete:"off"});
  const enabled=el("input",{id:"profile-enabled",type:"checkbox"});
  const cleanup=el("select",{id:"profile-cleanup"});
  const tone=el("select",{id:"profile-tone"});
  const language=el("select",{id:"profile-language"});
  const enter=el("select",{id:"profile-enter"});
  const fields=[match,enabled,cleanup,tone,language,enter];
  const save=el("button",{type:"submit",text:"Save app",class:"primary",disabled:true});
  const remove=el("button",{type:"button",text:"Remove",hidden:true});
  const up=el("button",{type:"button",text:"Move up",hidden:true});
  const down=el("button",{type:"button",text:"Move down",hidden:true});
  const summary=el("p",{class:"profile-summary",text:"Preferences apply when you start a dictation in the matching app."});
  let leavePending=null;
  function call(operation,extra={}){return request("workspace",{area:"app-profiles",operation,...extra});}
  function selectOptions(select,values,value){select.replaceChildren();for(const choice of values)select.append(el("option",{value:choice.value,text:choice.label}));
    if(!values.some(choice=>choice.value===value))select.append(el("option",{value,text:`Saved preference: ${value}`}));select.value=value;}
  function record(){return {match:match.value,enabled:enabled.checked,cleanup_level:cleanup.value,tone:tone.value,language:language.value,auto_enter:enter.value===""?null:enter.value==="on"};}
  function sync(){state.dirty=state.loaded&&JSON.stringify(record())!==state.original;fields.forEach(field=>field.disabled=state.busy||!state.loaded);
    save.disabled=!state.dirty||state.busy;remove.disabled=state.busy;up.disabled=state.busy||state.dirty||!state.entries.find(row=>row.id===state.id)?.can_up;
    down.disabled=state.busy||state.dirty||!state.entries.find(row=>row.id===state.id)?.can_down;add.disabled=state.busy||!state.canAdd;refresh.disabled=state.busy;
    const overrides=[cleanup.value&&`Formatting: ${cleanup.selectedOptions[0]?.textContent}`,tone.value&&`Tone: ${tone.selectedOptions[0]?.textContent}`,
      language.value&&`Language: ${language.selectedOptions[0]?.textContent}`,enter.value&&`Spoken Enter: ${enter.value}`].filter(Boolean);
    summary.textContent=!state.loaded?"Preferences apply when you start a dictation in the matching app.":!enabled.checked?"Disabled. Your other preferences and defaults apply.":overrides.length?overrides.join(" · "):"All settings follow your defaults.";
    changed();}
  function fill(value,id,revision){state.loaded=true;state.id=id;state.revision=revision;match.value=value.match;enabled.checked=value.enabled;
    selectOptions(cleanup,[{value:"",label:"Use default"},{value:"none",label:"None"},{value:"light",label:"Light"},{value:"medium",label:"Medium"},{value:"high",label:"High"}],value.cleanup_level);
    selectOptions(tone,state.tones||[{value:"",label:"Use default"}],value.tone);selectOptions(language,state.languages||[{value:"",label:"Use default"}],value.language);
    selectOptions(enter,[{value:"",label:"Use default"},{value:"off",label:"Off"},{value:"on",label:"On"}],value.auto_enter===null?"":value.auto_enter?"on":"off");
    state.original=JSON.stringify(record());title.textContent=id?value.match:"New app preference";remove.hidden=up.hidden=down.hidden=!id;
    status.textContent=id?"Saved preference. Changes apply to your next dictation.":"Enter part of the app name. The first enabled match wins.";status.setAttribute("role","status");sync();renderList();}
  function renderList(){list.replaceChildren();const query=search.value.trim().toLocaleLowerCase();const entries=state.entries.filter(row=>row.record.match.toLocaleLowerCase().includes(query));
    count.textContent=entries.length?`${entries.length} ${entries.length===1?"app":"apps"} · first enabled match wins`:query?"No matching apps.":"Your defaults apply everywhere. Add an app to make an exception.";
    if(state.uneditable)count.textContent+=` ${state.uneditable} older entries are kept unchanged. Keep a backup before recovering them.`;
    for(const row of entries){const button=el("button",{class:"document-entry","aria-pressed":row.id===state.id},[
      el("small",{text:`${row.position < 10?"0":""}${row.position} / ${row.record.enabled?"Enabled":"Disabled"}`}),el("strong",{text:row.record.match}),
      el("span",{text:[row.record.cleanup_level&&`${row.record.cleanup_level} formatting`,row.record.tone,row.record.language,row.record.auto_enter!==null&&`Spoken Enter ${row.record.auto_enter?"on":"off"}`].filter(Boolean).join(" · ")||"Uses your defaults"})]);
      button.onclick=async()=>{if(await leave()){fill(row.record,row.id,state.listRevision);match.focus();}};list.append(button);}}
  async function load(){const generation=++state.generation;
    try{const result=await call("list");if(state.disposed||generation!==state.generation)return false;
      state.entries=result.entries;state.listRevision=result.revision;state.canAdd=result.can_add;state.uneditable=result.uneditable;state.tones=result.tones;state.languages=result.languages;
      renderList();sync();return true;
    }catch(error){if(!state.disposed&&generation===state.generation){count.textContent=error.message;notice(error.message,true);}return false;}}
  async function saveEntry(){if(!state.dirty)return true;if(state.busy)return false;state.busy=true;sync();status.textContent="Saving app preference…";
    try{const result=await call("put",{id:state.id,revision:state.revision,record:record()});if(state.disposed)return false;
      await load();fill(result.record,result.id,result.revision);notice(result.message);return true;
    }catch(error){status.textContent=error.message;status.setAttribute("role","alert");notice(error.message,true);return false;}
    finally{state.busy=false;sync();}}
  editor.onsubmit=event=>{event.preventDefault();saveEntry();};
  fields.forEach(field=>field.addEventListener("input",()=>{sync();status.textContent=state.dirty?"Unsaved changes.":"Saved preference.";status.setAttribute("role","status");}));
  search.addEventListener("input",renderList);
  const leaveDialog=el("dialog",{"aria-labelledby":"app-profile-leave-title"});
  const stay=el("button",{text:"Keep editing",autofocus:true}),discard=el("button",{text:"Discard draft"}),saveLeave=el("button",{text:"Save app",class:"primary"});
  leaveDialog.append(el("h2",{id:"app-profile-leave-title",text:"Keep these app preferences?"}),el("p",{text:"Save the changes before leaving, or discard this draft."}),el("div",{class:"dialog-actions"},[stay,discard,saveLeave]));
  function finishLeave(value){const resolve=leavePending;leavePending=null;if(leaveDialog.open)leaveDialog.close();resolve?.(value);}
  stay.onclick=()=>finishLeave(false);discard.onclick=()=>{state.dirty=false;state.original=JSON.stringify(record());changed();finishLeave(true);};
  saveLeave.onclick=async()=>{saveLeave.disabled=discard.disabled=stay.disabled=true;const result=await saveEntry();saveLeave.disabled=discard.disabled=stay.disabled=false;finishLeave(result);};
  leaveDialog.addEventListener("cancel",event=>{event.preventDefault();if(!state.busy)finishLeave(false);});
  async function leave(){if(state.busy)return false;if(!state.dirty)return true;if(leavePending)return false;return new Promise(resolve=>{leavePending=resolve;leaveDialog.showModal();});}
  add.onclick=async()=>{if(await leave()){fill({match:"",enabled:true,cleanup_level:"",tone:"",language:"",auto_enter:null},"",state.listRevision);match.focus();}};
  refresh.onclick=async()=>{if(!await leave())return;const id=state.id;if(await load()){const row=state.entries.find(row=>row.id===id);
    if(row)fill(row.record,row.id,state.listRevision);else{state.loaded=false;state.id="";state.original="";fields.forEach(field=>field.value="");enabled.checked=false;title.textContent="Choose an app";remove.hidden=up.hidden=down.hidden=true;status.textContent="List refreshed. Choose an app to edit.";sync();}}};
  async function move(direction){if(state.busy||state.dirty)return;state.busy=true;sync();try{const result=await call("move",{id:state.id,revision:state.revision,direction});await load();fill(result.record,result.id,result.revision);notice(result.message);}
    catch(error){status.textContent=error.message;notice(error.message,true);}finally{state.busy=false;sync();}}
  up.onclick=()=>move("up");down.onclick=()=>move("down");
  const deleteDialog=el("dialog",{"aria-labelledby":"app-profile-delete-title"});const deleteText=el("p");const deleteStatus=el("p",{role:"status"});
  const keep=el("button",{text:"Keep preference",autofocus:true}),confirmDelete=el("button",{text:"Remove preference"});
  deleteDialog.append(el("h2",{id:"app-profile-delete-title",text:"Remove this app preference?"}),deleteText,deleteStatus,el("div",{class:"dialog-actions"},[keep,confirmDelete]));
  remove.onclick=()=>{deleteText.textContent=`Remove the saved preference for ${title.textContent}? Other matches and your defaults will apply. Any draft for this entry will also be discarded.`;deleteStatus.textContent="";deleteDialog.showModal();};
  keep.onclick=()=>deleteDialog.close();deleteDialog.addEventListener("cancel",event=>{if(state.busy)event.preventDefault();});
  confirmDelete.onclick=async()=>{if(state.busy)return;state.busy=true;confirmDelete.disabled=keep.disabled=true;sync();try{const result=await call("delete",{id:state.id,revision:state.revision,confirmed:true});
      state.loaded=false;state.id="";state.original="";state.dirty=false;fields.forEach(field=>field.value="");enabled.checked=false;title.textContent="Choose an app";remove.hidden=up.hidden=down.hidden=true;
      status.textContent="Preference removed. Choose another app or add one.";deleteDialog.close();await load();notice(result.message);
    }catch(error){deleteStatus.textContent=error.message;notice(error.message,true);}finally{state.busy=false;confirmDelete.disabled=keep.disabled=false;sync();}};
  const style=el("details",{class:"workspace-options profile-style"});const styleCount=el("p",{class:"secondary",role:"status"});const clearStyle=el("button",{text:"Clear style counts",disabled:true});
  style.append(el("summary",{text:"Learned writing style"}),el("p",{text:"Talk DAT counts habits in saved text, such as contractions and sentence length. Those counts stay on this computer. Manual Fix That rewrites can use a short style instruction with your selected text provider."}),
    el("p",{class:"secondary",text:"This does not automatically change every dictation. A useful style instruction needs at least 20 samples. The count gradually reduces so newer habits can take over."}),styleCount,clearStyle);
  async function loadStyle(){try{const result=await call("style");if(state.disposed)return;state.style=result;
    styleCount.textContent=`${result.votes} weighted samples · ${result.ready?"a style instruction is ready":"still learning"}`;clearStyle.disabled=!result.votes||state.busy;
    }catch(error){styleCount.textContent=error.message;clearStyle.disabled=true;}}
  style.addEventListener("toggle",()=>{if(style.open)loadStyle();});
  const styleDialog=el("dialog",{"aria-labelledby":"app-profile-style-title"});const styleError=el("p",{role:"status"});
  const keepStyle=el("button",{text:"Keep style counts",autofocus:true}),confirmStyle=el("button",{text:"Clear style counts"});
  styleDialog.append(el("h2",{id:"app-profile-style-title",text:"Clear learned style counts?"}),el("p",{text:"This resets the local style counts. Your History and app preferences stay as they are. New saved text can build the counts again."}),styleError,el("div",{class:"dialog-actions"},[keepStyle,confirmStyle]));
  clearStyle.onclick=()=>{styleError.textContent="";styleDialog.showModal();};keepStyle.onclick=()=>styleDialog.close();styleDialog.addEventListener("cancel",event=>{if(state.busy)event.preventDefault();});
  confirmStyle.onclick=async()=>{if(state.busy||!state.style)return;state.busy=true;keepStyle.disabled=confirmStyle.disabled=true;sync();try{const result=await call("reset_style",{revision:state.style.revision,confirmed:true});styleDialog.close();await loadStyle();notice(result.message);}
    catch(error){styleError.textContent=error.message;notice(error.message,true);}finally{state.busy=false;keepStyle.disabled=confirmStyle.disabled=false;sync();clearStyle.disabled=!state.style?.votes;}};
  function field(label,control,hint){return el("div",{class:"profile-field"},[el("label",{for:control.id,text:label}),control,hint?el("small",{text:hint}):null]);}
  const grid=el("div",{class:"profile-field-grid"},[field("Formatting",cleanup),field("Writing tone",tone,"Tone uses your AI formatter when available."),
    field("Language hint",language,"Your speech model must support it. Some local models auto-detect."),field("Spoken Enter command",enter,"Allow the spoken command to press Enter. This does not submit every dictation.")]);
  editor.append(el("header",{class:"profile-editor-heading"},[title,el("label",{class:"profile-enabled",for:"profile-enabled"},[enabled,el("span",{text:"Enabled"})])]),
    field("App name contains",match,"Matches the app name, ignoring capitals. A browser preference applies to all its websites."),grid,summary,status,
    el("div",{class:"profile-editor-actions"},[save,remove,up,down]));
  collection.append(search,el("div",{class:"action-list"},[add,refresh]),count,list);layout.append(collection,editor);
  root.append(el("p",{class:"profile-guide",text:"Keep your defaults for everyday writing. Add an exception for an app, then place specific names above broader ones."}),layout,style,leaveDialog,deleteDialog,styleDialog);
  container.append(root);sync();load().then(ok=>{if(ok&&!state.disposed&&!state.loaded&&state.entries.length){const first=state.entries[0];fill(first.record,first.id,state.listRevision);}});
  return {root,isDirty:()=>state.dirty||state.busy,leave,dispose:()=>{state.disposed=true;state.generation++;finishLeave(false);}};
};
