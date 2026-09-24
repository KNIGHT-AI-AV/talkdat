"use strict";
window.TalkDatTranslation = ({container,el,request,notice,changed}) => {
  const state={revision:0,data:null,sequence:0,saved:0,saving:null,action:null,disposed:false,timer:0,poll:0,outputId:"",outputText:"",acceptedId:"",reading:0,loaded:false};
  const root=el("section",{class:"translation-workspace","data-workspace":"translation"});
  const languages=el("div",{class:"translation-languages"});
  const from=el("select",{"aria-label":"Source language",disabled:true});
  const to=el("select",{"aria-label":"Target language",disabled:true});
  const swap=el("button",{text:"Swap",class:"quiet","aria-label":"Swap languages and use the current result as source",disabled:true});
  languages.append(el("label",{text:"From"},[from]),swap,el("label",{text:"To"},[to]));
  const source=el("textarea",{"aria-label":"Text to translate",placeholder:"Paste a passage, or speak it here.",spellcheck:true,dir:"auto",disabled:true});
  const output=el("textarea",{"aria-label":"Translation result",placeholder:"Your translation will appear here.",readonly:true,spellcheck:false,dir:"auto"});
  const counter=el("small",{class:"secondary",text:"0 / 64,000 characters"});
  const resultLabel=el("small",{class:"secondary",text:"Result"});
  const copy=el("button",{text:"Copy result",disabled:true});
  const status=el("p",{class:"translation-status",role:"status",text:"Opening your translation workspace..."});
  const translate=el("button",{text:"Translate",class:"primary",disabled:true});
  const cancel=el("button",{text:"Cancel translation",hidden:true});
  const speak=el("button",{text:"Speak and translate",disabled:true});
  const clear=el("button",{text:"Clear",class:"quiet",disabled:true});
  const modelStatus=el("small",{class:"secondary",text:"Local translation"});
  const options=el("details",{class:"workspace-options translation-setup"},[el("summary",{text:"Model and passage options"})]);
  const model=el("select",{"aria-label":"Translation model",disabled:true});
  const tone=el("select",{"aria-label":"Tone for this passage",disabled:true});
  for(const value of ["natural","formal","informal","literal"])tone.append(el("option",{value,text:value[0].toUpperCase()+value.slice(1)}));
  const formatting=el("input",{type:"checkbox","aria-label":"Preserve line breaks",disabled:true});
  const check=el("button",{text:"Check readiness",disabled:true});
  const startEngine=el("button",{text:"Start engine",disabled:true});
  const install=el("button",{text:"Install engine",disabled:true});
  const downloadPage=el("button",{text:"Ollama download page",class:"quiet"});
  const download=el("button",{text:"Download selected model",disabled:true});
  const setupDetail=el("p",{class:"secondary"});
  options.append(el("div",{class:"translation-option-grid"},[
    el("label",{text:"Model"},[model]),el("label",{text:"Tone"},[tone]),
    el("label",{class:"translation-check"},[formatting,document.createTextNode("Preserve line breaks")])]),
    setupDetail,el("div",{class:"action-list"},[check,startEngine,install,downloadPage,download]));
  const panels=el("div",{class:"translation-panels"},[
    el("article",{class:"translation-pane"},[el("header",{},[el("h2",{text:"Original"}),counter]),source]),
    el("article",{class:"translation-pane"},[el("header",{},[el("h2",{text:"Translation"}),resultLabel,copy]),output])]);
  const toolbar=el("div",{class:"translation-toolbar"},[translate,cancel,speak,clear,modelStatus]);
  const defaults=el("details",{class:"workspace-options translation-defaults"},[el("summary",{text:"Automatic translation and saved defaults"}),
    el("p",{class:"secondary",text:"These saved settings apply to future sessions and automatic dictation. The choices above apply to this passage."})]);
  const confirmation=el("dialog",{"aria-labelledby":"translation-confirm-title"});
  const confirmTitle=el("h2",{id:"translation-confirm-title"});const confirmText=el("p");
  const keep=el("button",{text:"Keep editing",autofocus:true});const confirm=el("button",{text:"Continue",class:"primary"});
  confirmation.append(confirmTitle,confirmText,el("div",{class:"dialog-actions"},[keep,confirm]));
  let pendingConfirmation=null;
  function finishConfirmation(value){const resolve=pendingConfirmation;pendingConfirmation=null;confirmation.close();resolve?.(value);}
  keep.onclick=()=>finishConfirmation(false);confirm.onclick=()=>finishConfirmation(true);
  confirmation.addEventListener("cancel",event=>{event.preventDefault();finishConfirmation(false);});
  function ask(title,text,label){if(pendingConfirmation)return Promise.resolve(false);confirmTitle.textContent=title;confirmText.textContent=text;confirm.textContent=label;
    return new Promise(resolve=>{pendingConfirmation=resolve;confirmation.showModal();});}
  root.append(languages,toolbar,status,panels,options,el("p",{class:"secondary translation-session-note",text:"Drafts stay in this app session. Completed translations follow your History setting."}),defaults,confirmation);
  container.append(root);
  const call=(operation,extra={})=>request("workspace",{area:"translation",operation,...extra});
  function values(){return {source:from.value,target:to.value,model:model.value,formality:tone.value,preserve_formatting:formatting.checked};}
  function dirty(){state.sequence++;clearTimeout(state.timer);state.timer=setTimeout(()=>save(),300);renderState();changed();}
  for(const field of [from,to,model,tone,formatting])field.addEventListener("change",dirty);
  source.addEventListener("input",dirty);
  function renderState(){
    const data=state.data||{},busy=Boolean(data.active||state.action),recording=Boolean(data.dictating),pending=state.sequence!==state.saved;
    const length=Array.from(source.value).length;
    counter.textContent=`${length.toLocaleString()} / 64,000 characters`;
    const ready=state.loaded&&!state.disposed;
    for(const field of [from,to,model,tone,formatting])field.disabled=!ready||recording||Boolean(busy&&data.kind!=='translate'&&data.kind!=='check');
    source.disabled=!ready;source.readOnly=recording;
    translate.disabled=!ready||busy||recording||!source.value.trim()||length>64000;
    speak.disabled=!ready||busy;speak.textContent=recording?"Finish speaking":"Speak and translate";
    clear.disabled=!ready||(!source.value&&!state.outputId&&!recording);
    swap.disabled=!ready||recording||busy;
    copy.disabled=!state.outputId;
    cancel.hidden=!(busy&&data.kind==='translate');cancel.disabled=Boolean(data.cancelling);
    for(const button of [check,startEngine,install,download])button.disabled=!ready||busy||recording;
    const stale=Boolean(data.result&&(pending||data.result.revision!==state.revision));
    resultLabel.textContent=stale?"Previous result. Translate your changes.":data.result?`${data.result.source} → ${data.result.target}`:"Result";
    copy.textContent=stale?"Copy previous result":"Copy result";
    status.textContent=pending&&!recording?"Keeping your draft...":data.message||"Add a passage, or speak it here.";
    status.setAttribute("role",data.error?"alert":"status");
    status.classList.toggle("error",Boolean(data.error));
    const currentReady=data.ready?.model===model.value?data.ready:null;
    modelStatus.textContent=`Local · ${model.value.split(":")[1]?.toUpperCase()||"4B"} · ${currentReady?.ready?"Ready":busy&&data.kind==='check'?"Checking":"Setup available"}`;
    const choice=[...(model.options||[])].find(option=>option.value===model.value);
    setupDetail.textContent=choice?`${choice.dataset.size} GB download · ${choice.dataset.memory} GB recommended memory. Downloading is optional and starts only when you choose it.`:"Choose a local model.";
  }
  async function read(part,identity){let text="",offset=0;do{const response=await call("read",{part,offset,...identity});text+=response.text;offset=response.next;}while(offset!==null);return text;}
  async function sync(data,{initial=false}={}){
    if(state.disposed)return;
    if(!initial&&data.revision<state.revision)return;
    const sequence=state.sequence,reading=++state.reading;
    state.data=data;
    if(initial||(!state.saving&&state.sequence===state.saved&&data.revision!==state.revision)){
      const text=await read("source",{revision:data.revision});
      if(state.disposed||reading!==state.reading||sequence!==state.sequence)return;
      source.value=text;state.revision=data.revision;
      from.value=data.options.source;to.value=data.options.target;model.value=data.options.model;
      tone.value=data.options.formality;formatting.checked=data.options.preserve_formatting;
    }
    if(data.result&&data.result.id!==state.outputId){
      const text=await read("result",{id:data.result.id});
      if(state.disposed||reading!==state.reading)return;
      state.outputText=text;state.outputId=data.result.id;output.value=text;
    }else if(!data.result){state.outputId="";state.outputText="";output.value="";}
    renderState();changed();schedulePoll();
    if(data.result&&data.result.revision===state.revision&&state.sequence===state.saved&&!state.saving&&state.acceptedId!==data.result.id){
      try{await call("accept_result",{revision:state.revision,id:data.result.id});state.acceptedId=data.result.id;}
      catch(error){status.textContent="Translation is ready, but History could not save it. You can still copy it.";notice(error.message,true);}
    }
  }
  function schedulePoll(){clearTimeout(state.poll);if(state.disposed||!state.data?.active&&!state.data?.dictating&&!state.data?.awaiting_speech)return;
    state.poll=setTimeout(async()=>{try{await sync(await call("status"));}catch(error){notice(error.message,true);schedulePoll();}},500);}
  async function save(){
    clearTimeout(state.timer);
    if(state.saving){await state.saving;return state.sequence===state.saved||save();}
    if(state.sequence===state.saved)return true;
    if(!state.loaded)return false;
    const sequence=state.sequence;
    state.saving=(async()=>{try{
      const response=await call("edit",{revision:state.revision,text:source.value,options:values()});
      state.revision=response.revision;state.saved=sequence;state.data=response;renderState();schedulePoll();return true;
    }catch(error){status.textContent=error.message;status.setAttribute("role","alert");notice(error.message,true);return false;}
    finally{state.saving=null;changed();}})();
    const okay=await state.saving;
    if(okay&&state.sequence!==state.saved)return save();
    return okay;
  }
  function run(operation,extra={}){
    if(state.action)return state.action;
    state.action=(async()=>{
      if(!await save())return;
      try{await sync(await call(operation,{revision:state.revision,...extra}));}
      catch(error){notice(error.message,true);status.textContent=error.message;status.setAttribute("role","alert");}
    })();
    renderState();
    return state.action.finally(()=>{state.action=null;renderState();});
  }
  translate.onclick=()=>run("translate");cancel.onclick=()=>run("cancel");
  check.onclick=()=>run("check");startEngine.onclick=()=>run("start_engine");install.onclick=()=>run("install_engine");
  downloadPage.onclick=async()=>{try{notice((await call("download_page")).message);}catch(error){notice(error.message,true);}};
  speak.onclick=()=>run(state.data?.dictating?"speech_stop":"speech_start");
  copy.onclick=async()=>{try{notice((await call("copy",{id:state.outputId})).message);}catch(error){notice(error.message,true);}};
  clear.onclick=async()=>{if(await ask("Clear this passage?","Clear the source and result in this workspace. Saved History entries stay available.","Clear passage"))await run("clear",{confirmed:true});};
  download.onclick=async()=>{const choice=model.selectedOptions[0];if(await ask("Download this model?",`${choice.textContent} needs about ${choice.dataset.size} GB of storage and ${choice.dataset.memory} GB of memory. The download continues if you leave this page.`,"Download model"))await run("download_model",{confirmed:true});};
  swap.onclick=async()=>{if(!await save())return;
    const previous=from.value==='auto'?state.autoCode:from.value;
    if(state.data?.result?.revision===state.revision){if(Array.from(state.outputText).length>64000){notice("This result is too long to use as one source passage. Copy a shorter part first.",true);return;}source.value=state.outputText;}
    from.value=to.value;to.value=previous;dirty();await save();};
  root.addEventListener("keydown",event=>{if((event.ctrlKey||event.metaKey)&&event.key==='Enter'&&!translate.disabled){event.preventDefault();run("translate");}});
  async function open(){try{
    const data=await call("open");if(state.disposed)return;
    state.autoCode=data.auto_code||"en";
    from.append(el("option",{value:"auto",text:`Follow dictation (${data.auto_language})`}));
    for(const language of data.languages){from.append(el("option",{value:language.value,text:language.label}));to.append(el("option",{value:language.value,text:language.label}));}
    for(const item of data.models)model.append(el("option",{value:item.value,text:item.label,"data-size":item.download_gb,"data-memory":item.recommended_ram_gb}));
    await sync(data,{initial:true});state.loaded=true;renderState();
    if(!data.active&&!data.dictating)await run("check");
  }catch(error){status.textContent=error.message;status.setAttribute("role","alert");notice(error.message,true);}}
  open();
  return {root,defaults,isDirty:()=>state.sequence!==state.saved||Boolean(state.data?.dictating),
    leave:async()=>{if(pendingConfirmation)return false;if(state.action)await state.action;if(!await save())return false;if(state.data?.dictating||state.data?.awaiting_speech){try{await sync(await call("speech_cancel"));}catch(error){notice(error.message,true);return false;}}return true;},
    dispose:()=>{state.disposed=true;clearTimeout(state.poll);clearTimeout(state.timer);state.reading++;finishConfirmation(false);}};
};

window.TalkDatGlossary = ({value,el,change,invalid}) => {
  let entries;try{entries=JSON.parse(value||"[]");if(!Array.isArray(entries))throw Error();}
  catch{return el("p",{class:"secondary",text:"This older glossary cannot be edited here. Its saved entries are kept unchanged."});}
  const root=el("div",{class:"translation-glossary"});const list=el("div");
  const message=el("p",{class:"secondary",role:"status"});const add=el("button",{text:"Add glossary term"});
  function editable(entry){return entry&&typeof entry==='object'&&typeof entry.source==='string'&&typeof entry.target==='string';}
  function update(){const issue=entries.some(entry=>editable(entry)&&(!entry.source.trim()||!entry.target.trim()||entry.source.length>512||entry.target.length>512));
    if(issue){message.textContent="Give each term a source and translation, up to 512 characters each.";invalid(JSON.stringify(entries),message.textContent);}
    else {const older=entries.filter(entry=>!editable(entry)).length;message.textContent=older?`${older} older entries are kept unchanged.`:"Use exact names and preferred translations. The first 100 entries are used.";change(JSON.stringify(entries));}
    add.disabled=entries.length>=100;}
  function draw(){list.replaceChildren();entries.forEach((entry,index)=>{if(!editable(entry))return;
    const source=el("input",{type:"text",value:entry.source,"aria-label":`Glossary source ${index+1}`,placeholder:"Source term",maxlength:512});
    const target=el("input",{type:"text",value:entry.target,"aria-label":`Glossary translation ${index+1}`,placeholder:"Preferred translation",maxlength:512});
    source.value=entry.source;target.value=entry.target;
    const remove=el("button",{text:"Remove",class:"quiet","aria-label":`Remove glossary term ${index+1}`});
    source.oninput=()=>{entry.source=source.value;update();};target.oninput=()=>{entry.target=target.value;update();};
    remove.onclick=()=>{entries.splice(index,1);draw();update();};list.append(el("div",{class:"translation-glossary-row"},[source,target,remove]));});add.disabled=entries.length>=100;}
  add.onclick=()=>{entries.push({source:"",target:""});draw();update();list.lastElementChild?.querySelector("input")?.focus();};
  root.append(list,add,message);message.textContent="Use exact names and preferred translations. The first 100 entries are used.";draw();return root;
};
