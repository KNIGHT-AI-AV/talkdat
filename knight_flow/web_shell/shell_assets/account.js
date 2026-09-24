"use strict";
// X-612: signing in, in the same design as the rest of Talk DAT!. It was a
// "Manage account" button that opened the square Tk Account window. The
// sign-in itself is the app's own; this page shows its words and asks for an
// email address and the six digits. The page is built once and only its words
// and visibility change, so a half-typed email or code is never lost.
window.TalkDatAccount=({container,el,request,notice})=>{
  const root=el("section",{"data-workspace":"account",class:"account-workspace"});
  const headline=el("h2",{class:"account-headline",text:"Reading your account..."});
  const detail=el("p",{class:"secondary account-detail"});
  const pairing=el("p",{class:"account-code","aria-label":"Sign-in code",hidden:true});
  const statusValue=el("dd",{text:"..."}),emailValue=el("dd",{text:"..."});
  const facts=el("dl",{class:"account-facts"},[el("div",{},[el("dt",{text:"Status"}),statusValue]),
    el("div",{},[el("dt",{text:"Account email"}),emailValue])]);
  const call=(operation,value)=>request("workspace",{area:"account",operation,...(value===undefined?{}:{value})});
  let timer=0,disposed=false,busy=false;
  const email=el("input",{id:"account-email",type:"email",autocomplete:"email",maxlength:"254",placeholder:"you@example.com","aria-label":"Email address"});
  const code=el("input",{id:"account-code-input",type:"text",inputmode:"numeric",autocomplete:"one-time-code",maxlength:"7",placeholder:"123456","aria-label":"Six-digit code"});
  const note=el("p",{class:"account-note",role:"alert"});
  const button=(text,operation,options={})=>el("button",{type:"button",text,class:options.primary?"primary":"",onclick:()=>act(operation,options.value?.())});
  const sendCode=button("Email me a code","email_code",{primary:true,value:()=>email.value});
  const verify=button("Sign in with this code","verify_code",{primary:true,value:()=>code.value});
  const resend=button("Send a new code","email_code",{value:()=>email.value});
  const codeRow=el("div",{class:"account-code-row",hidden:true},[el("label",{for:"account-code-input",text:"Six-digit code"}),code,
    el("div",{class:"action-list"},[verify,resend])]);
  const signinForm=el("section",{class:"account-signin","aria-label":"Sign in or create your account"},[
    el("h3",{text:"Sign in or create your account"}),
    el("p",{class:"secondary",text:"Type your email and we send a six-digit code. The code is the sign-in: no password to make, nothing to verify later."}),
    el("label",{for:"account-email",text:"Email address"}),
    el("div",{class:"account-email-row"},[email,sendCode]),note,codeRow,
    el("button",{type:"button",class:"quiet account-browser",text:"Prefer your browser? Sign in on the website instead",onclick:()=>act("browser_sign_in")})]);
  const cancel=button("Cancel sign-in","cancel");
  const signOut=button("Sign out","sign_out");
  const switchAccount=button("Switch account on the website","browser_sign_in");
  const website=button("Website","website");
  const actions=el("div",{class:"action-list account-actions"},[cancel,signOut,switchAccount,website]);
  email.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();act("email_code",email.value);}});
  code.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();act("verify_code",code.value);}});
  function render(v){
    headline.textContent=v.headline;detail.textContent=v.detail;
    statusValue.textContent=v.signed_in?"Signed in":"Not signed in";emailValue.textContent=v.email||"Not signed in";
    pairing.hidden=!v.code;pairing.textContent=v.code||"";
    signinForm.hidden=v.signed_in;codeRow.hidden=!v.code_box;
    note.textContent=v.note||"";note.hidden=!v.note;
    cancel.hidden=!v.waiting;signOut.hidden=!v.signed_in;switchAccount.hidden=!v.signed_in;
    verify.disabled=busy||v.phase==="verifying";sendCode.disabled=busy||v.waiting||v.phase==="verifying";
    if(v.code_box&&!root.dataset.codeShown){root.dataset.codeShown="1";code.focus();}
    if(!v.code_box)delete root.dataset.codeShown;
    clearTimeout(timer);if(!disposed)timer=setTimeout(()=>poll(),v.poll?700:2000);
  }
  async function poll(){try{const v=await call("status");if(!disposed)render(v);}catch(error){if(!disposed)timer=setTimeout(()=>poll(),2000);}}
  async function act(operation,value){
    if(busy)return;busy=true;
    try{const v=await call(operation,value);if(disposed)return;busy=false;render(v);
      if(operation==="email_code"&&!v.note)notice("Sending your code...");}
    catch(error){busy=false;notice(error.message,true);if(operation==="email_code")email.focus();if(operation==="verify_code")code.focus();}
  }
  root.append(headline,detail,pairing,facts,signinForm,actions,
    el("p",{class:"secondary account-free",text:"Talk DAT! is free. Every feature, the on-device models and your own API keys work without an account. Signing in keeps your preferences in step across your computers."}));
  container.append(root);poll();
  return {root,page:"account",leave:async()=>true,dispose:()=>{disposed=true;clearTimeout(timer);}};
};
