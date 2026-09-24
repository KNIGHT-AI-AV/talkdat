"use strict";
window.TalkDatReset = ({container,el,request,notice,changed=()=>{}}) => {
  const root=el("section",{class:"reset-workspace","aria-label":"Clear local data"});
  container.append(root);
  let state=null,selected=null,stopped=false,poll=0,inFlight=false,dialog=null;
  const call=(command,extra={})=>request("workspace",{area:"reset",command,...extra});
  const locked=()=>inFlight||["erasing","done"].includes(state?.phase);
  async function refresh() {
    try { state=await call("state");if(!stopped)render(); }
    catch(error){if(!stopped)notice(error.message,true);}
  }
  async function act(command,payload={}) {
    if(inFlight)return;
    inFlight=true;setControls(true);
    try { state=await call(command,payload);if(!stopped)render(); }
    catch(error){notice(error.message,true);await refresh();}
    finally {inFlight=false;setControls(false);changed();}
  }
  function setControls(busy) {
    for(const item of root.querySelectorAll("button,input,select"))item.disabled=busy||["erasing","scanning"].includes(state?.phase)||(item.hasAttribute("data-reset-preview")&&!selected?.size);
    if(dialog){
      const phrase=dialog.querySelector("input");
      const confirm=dialog.querySelector("[data-reset-confirm]");
      if(confirm)confirm.disabled=busy||Boolean(state?.preview?.personal&&phrase?.value!=="ERASE");
      const back=dialog.querySelector("[data-reset-back]");if(back)back.disabled=busy;
    }
  }
  function closeDialog() {if(dialog){dialog.close();dialog.remove();dialog=null;}}
  function showPreview() {
    const preview=state.preview;if(!preview||dialog)return;
    const title=el("h2",{id:"reset-review-title",text:"Review what will be cleared"});
    const list=el("ul",{},preview.labels.map(text=>el("li",{text})));
    const files=el("details",{},[el("summary",{text:"Files and folders in this app"}),el("ul",{},
      preview.files.map(text=>el("li",{text})))]);
    const text=el("p",{class:"secondary",text:preview.files.length?
      preview.size+" across the listed files and folders. Settings stored in the app are counted separately.":
      "No selected files are currently stored. The selected settings will still be cleared."});
    const warning=el("p",{text:"This cannot be undone. Talk DAT will pause while erasing and must close afterward."});
    const back=el("button",{"data-reset-back":"",text:"Go back"});
    const confirm=el("button",{"data-reset-confirm":"",class:"primary",text:"Erase selected items"});
    const contents=[title,list,text,files,warning];
    let phrase=null;
    if(preview.account)contents.push(el("p",{class:"secondary",text:"You will be signed out on this computer. Your account itself is not deleted."}));
    if(preview.personal){
      phrase=el("input",{id:"reset-phrase",type:"text",autocomplete:"off",spellcheck:"false",maxlength:5,"aria-describedby":"reset-phrase-help"});
      contents.push(el("label",{for:"reset-phrase",class:"reset-confirm-label",text:"Type ERASE to confirm"}),phrase,
        el("p",{id:"reset-phrase-help",class:"secondary",text:"Personal data, downloaded models and sign-in are always separate choices."}));
      confirm.disabled=true;
      phrase.addEventListener("input",()=>{confirm.disabled=inFlight||phrase.value!=="ERASE";});
    }
    contents.push(el("div",{class:"dialog-actions"},[back,confirm]));
    dialog=el("dialog",{"aria-labelledby":"reset-review-title",class:"reset-review"},contents);
    async function cancel(event){
      if(inFlight){event?.preventDefault();return;}
      event?.preventDefault();closeDialog();await act("cancel");
    }
    dialog.addEventListener("cancel",cancel);back.addEventListener("click",cancel);
    confirm.addEventListener("click",async()=>{
      const token=preview.token,typed=phrase?.value||"";
      await act("confirm",{token,phrase:typed});
      if(state?.phase!=="review")closeDialog();
    });
    document.body.append(dialog);dialog.showModal();
    (phrase||back).focus();
  }
  function render() {
    clearTimeout(poll);
    if(!state||stopped)return;
    if(selected===null)selected=new Set(state.categories.filter(row=>row.checked).map(row=>row.id));
    root.replaceChildren();
    const status=el("p",{class:"reset-status",role:state.error?"alert":"status","aria-live":"polite",text:state.message});
    root.append(status);
    if(state.phase==="erasing"){
      closeDialog();
      root.append(el("p",{class:"secondary",text:"The selected data is being checked again. Keep Talk DAT open until the result appears."}));
    } else if(state.phase==="done"){
      closeDialog();
      const result=state.result||{};
      root.append(el("h2",{text:state.error?"Review the result":"Ready to close"}),
        el("p",{text:(result.removed?.length||0)+" items cleared. "+(result.bytes_freed||0).toLocaleString()+" bytes removed."}));
      if(result.failed?.length)root.append(el("p",{text:"These items could not be cleared:"}),
        el("ul",{},result.failed.map(text=>el("li",{text}))));
      const finish=el("button",{class:"primary",text:"Close Talk DAT"});
      finish.addEventListener("click",()=>act("finish"));root.append(finish);
    } else {
      root.append(el("p",{class:"secondary",text:"Only the listed data on this computer is affected. Copies saved elsewhere, backups and your online account are kept."}));
      const presets=el("select",{id:"reset-preset","aria-label":"Reset starting point"});
      presets.append(el("option",{value:"custom",text:"Choose categories"}));
      for(const item of state.presets)presets.append(el("option",{value:item.id,text:item.label}));
      presets.addEventListener("change",()=>{
        const item=state.presets.find(row=>row.id===presets.value);
        if(item){selected=new Set(item.categories);render();}
      });
      root.append(el("label",{for:"reset-preset",class:"reset-preset-label",text:"Start with a selection"}),presets);
      const choices=el("div",{class:"reset-choices"});
      for(const category of state.categories){
        const input=el("input",{type:"checkbox",id:"reset-category-"+category.id,value:category.id});
        input.checked=selected.has(category.id);
        input.addEventListener("change",()=>{input.checked?selected.add(category.id):selected.delete(category.id);updateCount();});
        const description=el("span",{class:"secondary",text:category.description,id:input.id+"-description"});
        input.setAttribute("aria-describedby",description.id);
        choices.append(el("label",{class:"reset-choice",for:input.id},[input,
          el("span",{},[el("strong",{text:category.label}),description])]));
      }
      const count=el("p",{class:"secondary","data-reset-count":"",role:"status"});
      const preview=el("button",{class:"primary",text:state.phase==="scanning"?"Checking selected data...":"Preview selected items","data-reset-preview":""});
      preview.addEventListener("click",()=>act("preview",{selected:Array.from(selected)}));
      root.append(choices,el("div",{class:"reset-footer"},[count,preview]));
      function updateCount(){count.textContent=selected.size+" categories selected.";preview.disabled=!selected.size||inFlight||state.phase==="scanning";}
      updateCount();
      if(state.phase==="review")showPreview();
    }
    if(["scanning","erasing"].includes(state.phase))poll=setTimeout(refresh,250);
    setControls(inFlight);changed();
  }
  refresh();
  return {root,isDirty:()=>false,leave:async()=>{
    if(locked()){
      if(state?.phase==="done")notice("Close Talk DAT to finish this reset.",true);
      else notice("Wait for the reset result before leaving this page.",true);
      return false;
    }
    closeDialog();await call("cancel");return true;
  },dispose:()=>{stopped=true;clearTimeout(poll);closeDialog();if(!locked())call("cancel").catch(()=>{});}};
};

