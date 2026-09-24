"use strict";
window.TalkDatFeedback = ({container,el,request,notice,changed,kind="feature"}) => {
  const state={revision:null,original:"",loaded:false,dirty:false,saving:false,sending:false,busy:false,status:"idle",disposed:false,generation:0,token:"",include:false};
  const root=el("section",{class:"feedback-workspace","data-workspace":"feedback"});
  const form=el("form",{"aria-label":kind==="language"?"Language request":"Product idea"});
  const title=el("input",{id:"feedback-title",type:"text",maxlength:120,autocomplete:"off",placeholder:kind==="language"?"For example, Yoruba (Nigeria)":"What would make Talk DAT better?"});
  const details=el("textarea",{id:"feedback-details",maxlength:16000,rows:6,placeholder:kind==="language"?"Tell us about the language, region and how you would use it.":"What happens now, and what would you like to happen?"});
  const contact=el("input",{id:"feedback-contact",type:"email",maxlength:120,autocomplete:"email",placeholder:"you@example.com"});
  const counter=el("p",{class:"feedback-counter",role:"status"});
  const status=el("p",{class:"feedback-status",role:"status",text:"Loading your kept draft..."});
  const send=el("button",{type:"submit",class:"primary",text:"Send to the team",disabled:true});
  const copy=el("button",{type:"button",text:"Copy message",disabled:true});
  const email=el("button",{type:"button",text:"Open email draft",disabled:true});
  const reload=el("button",{type:"button",text:"Reload kept draft",disabled:true});
  const include=el("input",{type:"checkbox",id:"feedback-include"});
  const preview=el("button",{type:"button",text:"Preview formatting log"});
  const attached=el("p",{class:"secondary",text:"No formatting log selected."});
  const fields=[title,details,contact];let pollTimer=null;
  const call=(operation,extra={})=>request("workspace",{area:"feedback",kind,operation,...extra});
  const record=()=>({title:title.value,details:details.value,contact:contact.value});
  function message(){return [title.value.trim()?(kind==="language"?"Requested language: ":"")+title.value.trim():"",details.value.trim()].filter(Boolean).join("\n\n");}
  function sync(){state.dirty=state.loaded&&JSON.stringify(record())!==state.original;const count=message().length;
    counter.textContent=`${count.toLocaleString()} / 2,000 characters, including ${kind==="language"?"the language name":"the title"}`;
    counter.classList.toggle("error",count>2000);fields.forEach(field=>field.disabled=!state.loaded||state.saving||state.sending);
    send.disabled=!state.loaded||state.saving||state.busy||!count||count>2000||(state.status==="received"&&!state.dirty);
    send.textContent=state.sending?"Sending...":state.status==="received"&&!state.dirty?"Received":"Send to the team";
    copy.disabled=!state.loaded||state.saving||!count;email.disabled=copy.disabled||state.busy||count>2000;
    reload.disabled=!state.loaded||state.saving||state.sending;preview.disabled=!state.loaded||state.saving||state.sending;include.disabled=preview.disabled;
    include.checked=state.include;changed();}
  function show(value){state.revision=value.revision;state.sending=value.sending;state.busy=value.busy;state.status=value.status;
    status.textContent=value.message;status.setAttribute("role",value.status==="unconfirmed"?"alert":"status");sync();}
  function fill(value){state.loaded=true;title.value=value.record.title;details.value=value.record.details;contact.value=value.record.contact;
    state.original=JSON.stringify(record());show(value);}
  async function load(){const generation=++state.generation;try{const value=await call("state");if(state.disposed||generation!==state.generation)return;
      if(!state.loaded||!state.dirty)fill(value);else show(value);if(value.busy)pollTimer=setTimeout(poll,400);
    }catch(error){status.textContent=error.message;status.setAttribute("role","alert");notice(error.message,true);}}
  async function poll(){clearTimeout(pollTimer);try{const value=await call("state");if(state.disposed)return;show(value);if(value.busy)pollTimer=setTimeout(poll,400);}
    catch(error){if(state.disposed)return;status.textContent=error.message;status.setAttribute("role","alert");pollTimer=setTimeout(poll,1200);}}
  async function keepDraft(){if(!state.dirty)return true;if(state.saving||state.sending)return false;state.saving=true;sync();
    try{const value=await call("draft",{revision:state.revision,record:record()});if(state.disposed)return false;fill(value);return true;}
    catch(error){status.textContent=error.message;status.setAttribute("role","alert");notice(error.message,true);return false;}
    finally{state.saving=false;sync();}}
  fields.forEach(field=>field.addEventListener("input",()=>{sync();if(state.dirty){status.textContent="Your message is ready to keep or send.";status.setAttribute("role","status");}}));
  form.onsubmit=async event=>{event.preventDefault();if(!await keepDraft())return;state.saving=true;sync();
    try{const value=await call("send",{revision:state.revision,confirmed:true,include_logs:state.include,log_token:state.include?state.token:""});
      state.include=false;state.token="";attached.textContent="No formatting log selected. Each send needs its own choice.";show(value);if(value.busy)pollTimer=setTimeout(poll,350);
    }catch(error){status.textContent=error.message;status.setAttribute("role","alert");notice(error.message,true);}
    finally{state.saving=false;sync();}};
  copy.onclick=async()=>{try{const result=await call("copy",{record:record()});notice(result.message);}catch(error){notice(error.message,true);}};
  email.onclick=async()=>{if(!await keepDraft())return;try{const result=await call("email",{revision:state.revision});notice(result.message);status.textContent=result.message;}catch(error){notice(error.message,true);}};
  const reloadDialog=el("dialog",{"aria-labelledby":"feedback-reload-title"});const keep=el("button",{text:"Keep editing",autofocus:true}),discard=el("button",{text:"Use kept draft"});
  reloadDialog.append(el("h2",{id:"feedback-reload-title",text:"Reload the kept draft?"}),el("p",{text:"This replaces your current edits with the draft already kept in Talk DAT. Copy your message first if you want both versions."}),el("div",{class:"dialog-actions"},[keep,discard]));
  reload.onclick=()=>{if(state.dirty)reloadDialog.showModal();else load();};keep.onclick=()=>reloadDialog.close();discard.onclick=()=>{state.dirty=false;state.loaded=false;state.include=false;state.token="";reloadDialog.close();load();};
  const logDialog=el("dialog",{class:"feedback-log-dialog","aria-labelledby":"feedback-log-title"});
  const logText=el("textarea",{readonly:true,"aria-label":"Exact formatting log excerpt",rows:12});
  const logStatus=el("p",{class:"secondary",role:"status"});const cancelLog=el("button",{text:"Leave log out",autofocus:true}),useLog=el("button",{text:"Attach this excerpt",class:"primary",disabled:true});
  let previewToken="";
  logDialog.append(el("h2",{id:"feedback-log-title",text:"Review before attaching"}),el("p",{text:"This excerpt can contain your dictated text before and after formatting. Only the text shown here will be attached when you choose Send to the team."}),logText,logStatus,el("div",{class:"dialog-actions"},[cancelLog,useLog]));
  async function openPreview(){state.include=false;state.token="";previewToken="";sync();logText.value="";logStatus.textContent="Loading the recent excerpt...";useLog.disabled=true;logDialog.showModal();
    try{const result=await call("logs");if(state.disposed||!logDialog.open)return;previewToken=result.token;logText.value=result.text;
      logStatus.textContent=result.text?`${result.bytes.toLocaleString()} bytes · this exact excerpt will be used`:'There is no formatting log excerpt to attach.';useLog.disabled=!result.text;
    }catch(error){logStatus.textContent=error.message;}}
  preview.onclick=openPreview;include.onchange=()=>{if(include.checked)openPreview();else{state.include=false;state.token="";attached.textContent="No formatting log selected.";sync();}};
  cancelLog.onclick=()=>logDialog.close();logDialog.addEventListener("close",()=>{if(!state.include)attached.textContent="No formatting log selected.";});
  useLog.onclick=()=>{state.include=true;state.token=previewToken;attached.textContent="The reviewed excerpt will accompany this send.";logDialog.close();sync();};
  function field(label,control){return el("div",{class:"feedback-field"},[el("label",{for:control.id,text:label}),control]);}
  form.append(field(kind==="language"?"Language and region":"Idea title",title),field("Details",details),counter,field("Reply email (optional)",contact),
    el("p",{class:"feedback-draft-note",text:"Your draft stays in Talk DAT while you move between pages. It clears when you quit the app."}),status,
    el("div",{class:"feedback-actions"},[send,copy,email]));
  const aside=el("aside",{class:"feedback-privacy","aria-label":"What is included"},[el("h2",{text:"Your choice to share"}),
    el("p",{text:"Your message, app version and platform are included. A reply address is optional."}),
    el("p",{text:"No files are attached unless you choose a formatting-log excerpt."}),
    el("label",{class:"feedback-log-choice",for:"feedback-include"},[include,el("span",{text:"Include a formatting log"})]),preview,attached,
    el("p",{class:"secondary",text:"An email draft is a separate option. Opening it does not send the message, and it does not attach formatting logs."}),
    el("details",{class:"workspace-options"},[el("summary",{text:"Draft options"}),reload])]);
  root.append(el("div",{class:"feedback-layout"},[form,aside]),reloadDialog,logDialog);container.append(root);sync();load();
  return {root,isDirty:()=>state.dirty||state.saving,leave:async()=>{if(state.saving)return false;return state.sending||await keepDraft();},
    dispose:()=>{state.disposed=true;state.generation++;clearTimeout(pollTimer);}};
};
