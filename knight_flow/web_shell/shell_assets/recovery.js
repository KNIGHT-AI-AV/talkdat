"use strict";
window.TalkDatRecovery=({container,el,request,notice})=>{
  const root=el("section",{"data-workspace":"recovery"});
  const count=el("p",{class:"secondary",role:"status"}),list=el("div",{class:"recovery-list"});
  const refresh=el("button",{text:"Refresh recordings"});
  const history=el("button",{text:"Read History",onclick:()=>window.TalkDat.navigate("history")});
  const call=(operation,extra={})=>request("workspace",{area:"recovery",operation,...extra});
  let generation=0;
  async function load(){
    const current=++generation;
    try{const result=await call("list");if(current!==generation||!root.isConnected)return;
      count.textContent=result.sessions.length?`${result.sessions.length} protected ${result.sessions.length===1?"session":"sessions"} saved on this computer.`:"Your protected recordings will appear here.";
      list.replaceChildren();
      for(const row of result.sessions){
        const stamp=row.created_at?new Date(row.created_at*1000).toLocaleString():"Earlier recording";
        const actions=el("div",{class:"action-list"});
        for(const [operation,label,available] of [["recover","Recover text",row.has_audio],["copy","Copy text",row.has_text],["play","Play recording",row.has_audio]]){
          const button=el("button",{text:label});button.disabled=!available;
          button.addEventListener("click",async()=>{button.disabled=true;try{notice((await call(operation,{id:row.id})).message);}catch(error){notice(error.message,true);}finally{button.disabled=false;}});actions.append(button);
        }
        list.append(el("article",{class:"recovery-entry"},[el("h2",{text:stamp}),el("p",{class:"secondary",text:`${(row.duration_ms/1000).toFixed(1)} seconds, ${row.status.replaceAll('_',' ')}`}),el("p",{class:"recovery-preview",text:row.preview||"No transcript saved yet."}),actions]));
      }
    }catch(error){notice(error.message,true);count.textContent="Recordings could not load.";}
  }
  refresh.addEventListener("click",load);root.append(el("div",{class:"action-list"},[refresh,history]),count,list);container.append(root);load();
  return {root,leave:async()=>true,dispose:()=>generation++};
};
