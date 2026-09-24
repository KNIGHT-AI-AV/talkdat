"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { data: null, page: "general", draft: new Map(), invalid: new Map(), draftRevision: null, saving: false, closingRequested: false, noticeTimer: 0, guide: {query: "", location: "all", availability: "all"}, themes: {query:"", mode:null}, appearancePanel:"themes", lastPages:{} };
  const navigationGroups = [
    {id:"home", label:"Home", pages:["home"]},
    {id:"dictation", label:"Dictation", pages:["dictation","speech","models","mic-doctor","speech-check"]},
    {id:"formatting", label:"Writing", pages:["formatting","translation","words","ramble","scribe","app-profiles"]},
    {id:"tools", label:"Tools", pages:["tools","history","scratchpad","recovery","stats"]},
    {id:"appearance", label:"Appearance", pages:["appearance","menu-order"]},
    {id:"general", label:"Settings", pages:["general","privacy","reset","account"]},
    {id:"help", label:"Help", pages:["help","setup","model-guide","feedback","language-request"]},
  ];
  // Cells of the generated line-art atlas (icons/line-art-atlas.png, X-598).
  // 2026-09-23: one glyph per meaning. Tools no longer borrows the Words speech
  // bubble, Stats no longer borrows the History clock, and Scratchpad and
  // Scribe stop sharing one cell: notes get the clipboard, a conversation the
  // speech bubble.
  const icons = {general:0, formatting:1, history:2, appearance:3, dictation:4, speech:4, privacy:5, account:6, help:7, paste:8, scratchpad:8, words:9, scribe:9, translation:10, captions:11, update:12, restart:13, power:14, search:15};
  // Drawn masks for the meanings the sixteen atlas cells have no glyph for
  // (X-172 started this with Home). Stats and Tools are drawn at the atlas's
  // own stroke weight and footprint; see shell.css.
  const maskIcons = new Set(["home", "stats", "tools"]);
  function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "text") node.textContent = value;
      else if (key === "class") node.className = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (value !== undefined && value !== null) node.setAttribute(key, String(value));
    }
    for (const child of children) if (child) node.append(child);
    return node;
  }
  function icon(name) {
    if (maskIcons.has(name)) return el("span", {class:"nav-icon nav-icon-"+name, "aria-hidden":"true"});
    const index=icons[name] ?? 0;
    return el("span", {class:"nav-icon", "aria-hidden":"true", style:`--icon-x:${index%4*100/3}%;--icon-y:${Math.floor(index/4)*100/3}%`});
  }
  // The sidebar's footer used to read "Connected" at all times, which told
  // nobody anything (owner's audit, 2026-09-23). It is now hidden while this
  // window can reach the app, and says so plainly when it cannot: no bridge,
  // or an answer the host marks as a lost link ("disconnected").
  function linkLost() {
    document.body.classList.remove("connected");
    $("connection-status").hidden = false;
  }
  function linkRestored() {
    document.body.classList.add("connected");
    $("connection-status").hidden = true;
  }
  async function rpc(method, payload = {}) {
    const bridge = window.pywebview?.api;
    if (!bridge?.request) { linkLost(); throw new Error("Talk DAT is reconnecting. Your draft is still here."); }
    let answer;
    try { answer = await bridge.request(method, payload); }
    catch (failure) { linkLost(); throw failure; }
    if (answer?.error_code === "disconnected") linkLost(); else if (answer) linkRestored();
    if (!answer || answer.ok !== true) { const error = new Error(answer?.error || "This action could not finish. Please try again."); error.code = answer?.error_code; throw error; }
    return answer.result;
  }
  function notice(message, error = false) {
    clearTimeout(state.noticeTimer);
    $("notice").textContent = message; $("notice").hidden = false;
    $("notice").setAttribute("role", error ? "alert" : "status");
    state.noticeTimer = setTimeout(() => { $("notice").hidden = true; }, error ? 8000 : 3500);
  }
  async function action(name, payload = {}, button = null) {
    if (name === "restore_backup" && (state.draft.size || state.invalid.size || activeWorkspace?.isDirty?.())) {
      notice("Save or discard your current changes before restoring a backup.", true); return null;
    }
    if (button) button.disabled = true;
    try {
      const result = await rpc("action", { name, ...payload });
      if (state.page === "menu" && name.startsWith("route:")) await refresh();
      if (result?.message) notice(result.message);
      if (result?.backup_preview) confirmBackup(result.backup_preview);
      if (result?.page) await navigate(result.page);
      if (result?.state) receive(result.state);
      if (result?.models) { state.data.models = result.models; renderModelPanel(); }
      if (result && "smart_formatting" in result) { state.data.smart_formatting = result.smart_formatting; renderSmartFormatting(); }
      if (result?.microphones) { state.data.microphones = result.microphones; renderMicrophones(); }
      return result;
    } catch (error) { notice(error.message, true); return null; }
    finally { if (button) button.disabled = false; }
  }
  function confirmBackup(preview) {
    const labels = {"config.json":"Settings and vocabulary", "pinned.json":"Pinned dictations", "scratchpad-tabs.json":"Notes",
      "scratchpad.md":"Earlier scratchpad note", "history.jsonl":"Text history", "history.db":"Text history",
      "full-transcript-history.txt":"Full transcript archive", "live-transcript-draft.txt":"Last live draft", "recovered-draft.txt":"Recovered draft"};
    const dialog = el("dialog", {"aria-labelledby":"backup-restore-title"});
    const list = el("ul");
    for (const label of new Set(preview.files.map(name=>labels[name]).filter(Boolean))) list.append(el("li",{text:label}));
    const status = el("p", {role:"alert"});
    const cancel = el("button", {text:"Keep current data",autofocus:true});
    const confirm = el("button", {text:"Restore and quit",class:"primary"});
    let restoring=false;
    dialog.append(el("h2",{id:"backup-restore-title",text:"Restore this backup?"}),
      el("p",{text:"This replaces the saved items below. Talk DAT will quit after restoring. Open it again to load your restored data."}),
      list,el("p",{class:"secondary",text:"Recordings and downloaded models stay as they are."}),status,
      el("div",{class:"dialog-actions"},[cancel,confirm]));
    cancel.addEventListener("click",()=>dialog.close());
    dialog.addEventListener("cancel",event=>{if(restoring)event.preventDefault();});
    dialog.addEventListener("close",()=>{rpc("action",{name:"restore_backup_cancel"}).catch(()=>{});dialog.remove();});
    confirm.addEventListener("click",async()=>{
      restoring=true;confirm.disabled=true;cancel.disabled=true;status.textContent="Restoring your saved data…";
      try { const result=await rpc("action",{name:"restore_backup_confirm"});status.textContent=result.message;dialog.close(); }
      catch(error){restoring=false;status.textContent=error.message;confirm.disabled=false;cancel.disabled=false;}
    });
    document.body.append(dialog);dialog.showModal();
  }
  function currentValue(field) { return state.draft.has(field.id) ? state.draft.get(field.id) : field.value; }
  function dirty(field, value) {
    if (state.draftRevision === null) state.draftRevision = state.data?.revision;
    if (JSON.stringify(value) === JSON.stringify(field.value)) state.draft.delete(field.id);
    else state.draft.set(field.id, value);
    updateSaveStrip();
    if (field.id === "stt.provider") { renderPage(); $("field-" + field.id)?.focus(); }
  }
  function updateSaveStrip() {
    if (!state.draft.size && !state.invalid.size) state.draftRevision = null;
    $("save-strip").hidden = state.draft.size === 0 && state.invalid.size === 0;
    $("dirty-status").textContent = state.saving ? "Saving changes…" : state.invalid.size ? "Check the highlighted setting" : "Unsaved changes";
    $("save").disabled = state.saving || state.invalid.size > 0;
    $("save-close").disabled = $("save").disabled; $("discard").disabled = state.saving;
    Promise.resolve(window.pywebview?.api?.draft_changed?.(state.draft.size > 0 || state.invalid.size > 0 || Boolean(activeWorkspace?.isDirty?.()))).catch(() => {});
  }
  function allFields() { return (state.data?.pages || []).flatMap(page => (page.sections || []).flatMap(section => section.fields || [])); }
  async function save(close = false) {
    if (state.saving) return;
    if (state.invalid.size) { notice("Check the highlighted setting before saving.", true); return; }
    state.saving = true; updateSaveStrip();
    const pending = Object.fromEntries(state.draft);
    try {
      const changes = pending;
      if (Object.keys(changes).length) {
        const result = await rpc("save", { revision: state.draftRevision, changes });
        for (const [key, value] of Object.entries(changes)) if (JSON.stringify(state.draft.get(key)) === JSON.stringify(value)) state.draft.delete(key);
        state.draftRevision = state.draft.size ? result.revision : null;
        receive(result);
        if (result.message) notice(result.message, true);
      }
      if (!state.data.message) notice("Changes saved.");
      if (close && !state.draft.size) await rpc("close");
    } catch (error) {
      if (error.code === "settings_conflict") {
        try {
          receive(await rpc("state"));
          const values = $("conflict-values"); values.replaceChildren();
          for (const [key, value] of state.draft) {
            const field = allFields().find(field => field.id === key);
            if (!field) continue;
            const display = value => field.type === "secret" ? "A saved provider key" : String(value ?? "").slice(0, 240);
            values.append(el("section", {class: "section"}, [el("h3", {text: field.label}), el("p", {text: "Latest saved: " + display(field.value)}), el("p", {text: "Your draft: " + display(value)})]));
          }
          $("conflict-dialog").showModal();
        } catch (refreshError) { notice(refreshError.message, true); }
      } else notice(error.message, true);
    }
    finally { state.saving = false; updateSaveStrip(); }
  }
  let activeWorkspace=null,searchActive=false;
  let activeShortcut = null;
  function shortcutControl(field) {
    const value = currentValue(field) || [];
    const isMac = navigator.platform.includes("Mac");
    const names = {ctrl:"Ctrl",cmd:isMac?"Command":"Win",alt:"Alt",shift:"Shift",space:"Space",fn:"Fn / Globe"};
    const readable = chords => chords.map(chord=>chord.map(key=>names[key] || (key.length===1?key.toUpperCase():key.replaceAll('_',' '))).join(" + ")).join(" or ") || "Not assigned";
    const status = el("span", {class:"shortcut-value",text:readable(value),role:"status"});
    const record = el("button", {type:"button",text:value.length?"Record replacement":"Record", "aria-label":"Record " + field.label});
    const alternative = el("button", {type:"button",text:"Add alternative",class:"quiet"}); alternative.disabled=value.length>=8;
    const clear = el("button", {type:"button",text:"Clear",class:"quiet"});
    const mouse = el("select", {"aria-label":field.label + " mouse or controller button"});
    mouse.append(el("option",{value:"",text:"Mouse or controller…"}));
    for (const [key,label] of [["mouse4","Mouse 4"],["mouse5","Mouse 5"],["middle","Middle click"],["pad_a","Controller A"],["pad_b","Controller B"],["pad_lb","Controller LB"],["pad_rb","Controller RB"]]) mouse.append(el("option",{value:key,text:label}));
    const capture = {active:false,starting:false,down:new Map(),widest:[],append:false,arm:"",timer:0,owner:record};
    function finish(chord = null) {
      capture.active=false;capture.starting=false;clearInterval(capture.timer);capture.timer=0;
      if(activeShortcut===finish) activeShortcut=null;
      rpc("action",{name:"shortcut_end"}).catch(()=>{});
      record.textContent=value.length?"Record replacement":"Record"; alternative.textContent="Add alternative";
      status.textContent=readable(value);
      if (chord) { dirty(field,capture.append?[...value,chord]:[chord]); renderPage(); }
    }
    async function begin(append,owner,arm="") {
      if(capture.active||capture.starting)return;
      activeShortcut?.();activeShortcut=finish;capture.append=append;capture.owner=owner;capture.arm=arm;capture.starting=true;capture.down.clear();capture.widest=[];
      try {
        await rpc("action",{name:"shortcut_begin"});
        if(!capture.starting){rpc("action",{name:"shortcut_end"}).catch(()=>{});return;}
        capture.starting=false;capture.active=true;status.textContent="Press keys together, then release. Esc cancels.";owner.textContent="Recording…";
        capture.timer=setInterval(()=>rpc("action",{name:"shortcut_begin"}).catch(error=>{finish();notice(error.message,true);}),4000);
      } catch(error){finish();notice(error.message,true);}
    }
    const canonical = event => {
      const map={Control:"ctrl",Meta:"cmd",Alt:"alt",AltGraph:"alt_gr",Shift:"shift"," ":"space",Escape:"esc",Enter:"enter",Tab:"tab",Backspace:"backspace",Delete:"delete",Home:"home",End:"end",PageUp:"page_up",PageDown:"page_down",ArrowLeft:"left",ArrowRight:"right",ArrowUp:"up",ArrowDown:"down",Insert:"insert"};
      return map[event.key] || (/^F([1-9]|1\d|2[0-4])$/.test(event.key)?event.key.toLowerCase():event.key.length===1?event.key.toLowerCase():null);
    };
    for(const [owner,append] of [[record,false],[alternative,true]]) {
      owner.addEventListener("click",()=>begin(append,owner));
      owner.addEventListener("keydown",event=>{
        if(!capture.active){if(["Enter"," "].includes(event.key)){event.preventDefault();begin(append,owner,event.code);}return;}
        event.preventDefault();event.stopPropagation();
        if(event.code===capture.arm)return;
        if(event.key==="Escape"){finish();return;}
        if(event.key==="Backspace"&&!capture.down.size){finish();dirty(field,[]);renderPage();return;}
        const key=canonical(event);if(!key)return;
        capture.down.set(event.code,key);
        const held=[...new Set(capture.down.values())];if(held.length>capture.widest.length)capture.widest=held;
        status.textContent=readable([held])+" …";
      });
      owner.addEventListener("keyup",event=>{
        if(event.code===capture.arm){capture.arm="";return;}
        if(!capture.active)return;event.preventDefault();event.stopPropagation();capture.down.delete(event.code);
        if(!capture.down.size&&capture.widest.length)finish(capture.widest);
      });
      owner.addEventListener("blur",()=>{if(capture.active||capture.starting)finish();});
    }
    clear.addEventListener("click",()=>{finish();dirty(field,[]);renderPage();});
    // macOS reports Globe through modifier flags, so webviews cannot reliably
    // deliver it to the key recorder. Preserve the native hold-to-talk choice.
    const globe = isMac ? el("button", {type:"button",text:"Use Fn / Globe",class:"quiet",
      onclick:()=>{finish();dirty(field,[["fn"]]);renderPage();}}) : null;
    mouse.addEventListener("change",()=>{if(mouse.value){finish();dirty(field,[[mouse.value]]);renderPage();}});
    return el("div", {class:"shortcut-control", role:"group", "aria-labelledby":"field-"+field.id+"-label", "aria-describedby":"field-"+field.id+"-help"}, [status,el("div", {class:"shortcut-buttons"},[record,alternative,globe,clear]),mouse]);
  }
  function microphoneControl(field) {
    const value=currentValue(field)||"", result=state.data.microphones||{};
    const select=el("select",{id:"field-"+field.id,"aria-labelledby":"field-"+field.id+"-label"});
    select.append(el("option",{value:"",text:"System default"}));
    const devices=[...result.devices||[]];if(value&&!devices.includes(value))devices.unshift(value);
    for(const device of devices)select.append(el("option",{value:device,text:device}));select.value=value;
    select.addEventListener("change",()=>dirty(field,select.value));
    const refresh=el("button",{text:result.status==="loading"?"Finding microphones…":"Refresh microphones",class:"quiet"});refresh.disabled=result.status==="loading";
    refresh.addEventListener("click",()=>action("refresh_microphones",{},refresh));
    return el("div", {id:"microphone-picker",class:"input-field"},[select,refresh,el("span",{class:"description",role:"status",text:result.message||""})]);
  }
  function renderMicrophones() {
    const existing=$("microphone-picker"), field=allFields().find(field=>field.id==="audio.input_device");
    if(existing&&field)existing.replaceWith(microphoneControl(field));
  }
  setInterval(async()=>{
    if(state.page!=="dictation"||state.data?.microphones?.status!=="loading")return;
    try {const latest=await rpc("state");state.data.microphones=latest.microphones;renderMicrophones();}catch(error){notice(error.message,true);}
  },1200);
  function control(field) {
    const id = "field-" + field.id;
    const value = currentValue(field);
    if (field.type === "hotkey") return shortcutControl(field);
    if (field.id === "audio.input_device") return microphoneControl(field);
    if (field.type === "toggle") {
      const button = el("button", { id, class: "switch", type: "button", role: "switch", "aria-checked": Boolean(value), "aria-labelledby": id + "-label", "aria-describedby": id + "-help" });
      button.addEventListener("click", () => { const next = button.getAttribute("aria-checked") !== "true"; button.setAttribute("aria-checked", String(next)); dirty(field, next); });
      return button;
    }
    if(field.id === "translation.glossary") return window.TalkDatGlossary({value:state.invalid.get(field.id)?.value ?? value,el,
      change:updated=>{state.invalid.delete(field.id);dirty(field,updated);},
      invalid:(updated,message)=>{if(state.draftRevision===null)state.draftRevision=state.data?.revision;state.invalid.set(field.id,{value:updated,message});updateSaveStrip();}});
    if (field.type === "choice") {
      const group = el("div", { class: "segmented", role: "group", "aria-labelledby": id + "-label" });
      for (const option of field.options || []) {
        const button = el("button", { type: "button", text: option.label, "aria-pressed": option.value === value });
        button.addEventListener("click", () => { dirty(field, option.value); for (const sibling of group.children) sibling.setAttribute("aria-pressed", String(sibling === button)); });
        group.append(button);
      }
      return group;
    }
    if (field.type === "select") {
      const select = el("select", { id, "aria-labelledby": id + "-label", "aria-describedby": id + "-help" });
      for (const option of field.options || []) select.append(el("option", { value: option.value, text: option.label, title: option.title || option.label }));
      // A closed select has room for about twenty characters. The chosen
      // option's full name rides along as a tooltip, so a long one is never
      // only its first half ("Parakeet TDT 0.6B v3 (reco...", 2026-09-23).
      const titled = () => { select.title = select.selectedOptions[0]?.title || select.selectedOptions[0]?.textContent || ""; };
      select.value = String(value ?? ""); titled(); select.addEventListener("change", () => { titled(); dirty(field, select.value); });
      if (["dictation.sound_on","dictation.sound_off"].includes(field.id)) {
        const preview=el("button",{text:"Preview",class:"quiet","aria-label":"Preview "+field.label.toLowerCase()});
        preview.addEventListener("click",()=>action("sound_preview:"+select.value,{},preview));
        return el("div",{class:"input-field"},[select,preview]);
      }
      return select;
    }
    if (field.type === "action") {
      const button = el("button", { type: "button", text: field.button || "Open" });
      button.addEventListener("click", () => action(field.action, {}, button)); return button;
    }
    if (field.type === "secret") {
      const input = el("input", {id, type: "password", autocomplete: "new-password", spellcheck: "false", maxlength: 4096, "aria-labelledby": id + "-label", "aria-describedby": id + "-help", placeholder: field.saved ? "Saved. Enter a replacement." : "Enter your provider key"});
      input.value = state.draft.get(field.id) || "";
      input.addEventListener("input", () => dirty(field, input.value));
      const clear = el("button", {type: "button", class: "quiet", text: state.draft.get(field.id) === null ? "Keep saved key" : "Remove saved key"});
      clear.hidden = !field.saved;
      clear.addEventListener("click", () => { dirty(field, state.draft.get(field.id) === null ? "" : null); renderPage(); });
      return el("div", {class: "secret-field"}, [input, clear, el("span", {class: "description", text: state.draft.get(field.id) === null ? "The saved key will be removed when you save." : ""})]);
    }
    const input = el(field.type === "textarea" ? "textarea" : "input", {
      id, type: field.type === "number" ? "number" : "text", min: field.min, max: field.max, step: field.step,
      "aria-labelledby": id + "-label", "aria-describedby": id + "-help", autocomplete: "off", spellcheck: field.spellcheck !== false,
    });
    const error = el("span", {id: id + "-error", class: "field-error", role: "status"});
    input.setAttribute("aria-describedby", id + "-help " + id + "-error");
    input.value = state.invalid.get(field.id)?.value ?? value ?? "";
    function showError(message) { input.setAttribute("aria-invalid", String(Boolean(message))); error.textContent = message; error.hidden = !message; }
    showError(state.invalid.get(field.id)?.message || "");
    input.addEventListener("input", () => {
      input.setCustomValidity(field.type === "number" && !Number.isFinite(input.valueAsNumber) ? "Enter a number." : "");
      if (!input.checkValidity()) {
        if (state.draftRevision === null) state.draftRevision = state.data?.revision;
        const message = input.validationMessage;
        state.invalid.set(field.id, {value: input.value, message}); showError(message); updateSaveStrip(); return;
      }
      state.invalid.delete(field.id); showError("");
      dirty(field, field.type === "number" ? input.valueAsNumber : input.value);
    });
    return el("div", {class: "input-field"}, [input, error]);
  }
  function pluginTools() {
    const panel=el("div",{class:"plugin-tools","aria-label":"Installed plugin status"});
    const status=el("p",{role:"status",text:"Reading plugin status..."});
    const issues=el("ul",{class:"plugin-issues"});
    const reload=el("button",{type:"button",text:"Reload plugins"});
    const refresh=el("button",{type:"button",text:"Refresh plugin status",class:"quiet"});
    const folder=el("button",{type:"button",text:"Open plugins folder",class:"quiet"});
    panel.append(status,issues,el("div",{class:"record-actions"},[reload,refresh,folder]));
    let timer=null,pending=false;
    async function update(command="status") {
      if(!panel.isConnected||pending)return;
      clearTimeout(timer);pending=true;reload.disabled=true;refresh.disabled=true;
      try {
        if(command==="reload"&&state.draft.has("plugins.enabled"))throw new Error("Save your plugin choice before reloading.");
        const value=await rpc("workspace",{area:"plugins",command});
        if(!panel.isConnected)return;
        status.textContent=value.message;
        issues.replaceChildren(...(value.errors||[]).map(text=>el("li",{text})));
        issues.hidden=!(value.errors||[]).length;
        reload.disabled=["disabled","loading"].includes(value.phase)||state.draft.has("plugins.enabled");
        if(value.phase==="loading")timer=setTimeout(()=>update(),350);
      } catch(error){status.textContent=error.message;reload.disabled=false;}
      finally{pending=false;refresh.disabled=false;}
    }
    reload.addEventListener("click",()=>update("reload"));
    refresh.addEventListener("click",()=>update());
    folder.addEventListener("click",async()=>{
      folder.disabled=true;
      try{const result=await rpc("workspace",{area:"plugins",command:"folder"});notice(result.message);}
      catch(error){notice(error.message,true);}
      finally{folder.disabled=false;}
    });
    queueMicrotask(()=>update());
    return panel;
  }

  function fieldRow(field) {
    const id = "field-" + field.id;
    const row = el("div", { class: "setting-row" + (field.type === "textarea" ? " wide" : ""), "data-field": field.id });
    row.append(el("div", {}, [
      el("label", { id: id + "-label", for: id, class: "label", text: field.label }),
      el("span", { id: id + "-help", class: "description", text: field.description || "" }),
    ]), el("div", { class: "control" }, [control(field)]));
    if(field.id==="plugins.enabled")row.append(pluginTools());
    return row;
  }
  function renderNavigation() {
    $("navigation").replaceChildren();
    for (const group of navigationGroups) {
      const active = group.pages.includes(state.page);
      if (active) state.lastPages[group.id] = state.page;
      const target = state.lastPages[group.id] || group.pages[0];
      const button = el("button", { type:"button", "data-page":target, "aria-current":active ? "page" : "false" }, [icon(group.id), el("span", {text:group.label})]);
      button.addEventListener("click", () => navigate(target)); $("navigation").append(button);
    }
    const group = navigationGroups.find(group => group.pages.includes(state.page));
    const sections = $("sections"); sections.replaceChildren();
    const choices = (group?.pages || []).map(id => ({id, label:state.data.pages.find(page => page.id === id)?.label || id}));
    if (group?.id === "appearance") choices.splice(0, 1,
      {id:"appearance", panel:"themes", label:"Themes"},
      {id:"appearance", panel:"text", label:"Text and motion"},
      {id:"appearance", panel:"pill", label:"Pill"});
    sections.hidden = choices.length < 2;
    for (const choice of choices) {
      const active = choice.id === state.page && (!choice.panel || choice.panel === state.appearancePanel);
      const button = el("button", {text:choice.label, "data-page":choice.id, "aria-current":active ? "page" : "false"});
      button.addEventListener("click", () => { if (choice.panel) state.appearancePanel = choice.panel; navigate(choice.id); });
      sections.append(button);
    }
  }
  function intro(page) { return el("div", { class: "intro" }, [el("h1", { text: page.label || page.title }), el("p", { text: page.description || "" })]); }
  function renderPage() {
    activeShortcut?.();
    const page = state.data?.pages.find(page => page.id === state.page);
    if (!page) return;
    renderNavigation(); const main = $("page");
    if(activeWorkspace?.root?.isConnected && activeWorkspace.page === state.page) { updateSaveStrip(); return; }
    activeWorkspace?.dispose?.();activeWorkspace=null;
    // Home draws its own greeting, so the stock intro would say it twice.
    main.replaceChildren(...(page.id === "home" ? [] : [intro(page)]));
    if(page.id === "home") activeWorkspace=window.TalkDatHome({container:main,el,request:rpc,notice});
    if(["mic-doctor","speech-check"].includes(page.id)) activeWorkspace=window.TalkDatMicCheck({container:main,el,request:rpc,notice,mode:page.id==="speech-check"?"speech":"mic",changed:updateSaveStrip});
    if(page.id === "stats") activeWorkspace=window.TalkDatStats({container:main,el,request:rpc,notice});
    if(page.id === "scribe") activeWorkspace=window.TalkDatScribe({container:main,el,request:rpc,notice,changed:updateSaveStrip});
    if(page.id === "ramble") activeWorkspace=window.TalkDatRamble({container:main,el,request:rpc,notice,changed:updateSaveStrip});
    if(page.id === "translation") activeWorkspace=window.TalkDatTranslation({container:main,el,request:rpc,notice,changed:updateSaveStrip});
    if(page.id === "formatting" && state.data?.finish_choice) main.append(renderFinishChoice(state.data.finish_choice));
    if(page.id === "formatting") { main.append(el("section", {id:"smart-formatting", class:"section smart-formatting", "aria-label":"Smart formatting"})); renderSmartFormatting(); }
    for (const section of page.sections || []) {
      if (page.id === "words") continue;
      if (page.id === "appearance" && section.label !== ({text:"Text and motion",pill:"Pill details"})[state.appearancePanel]) continue;
      const fields = (section.fields || []).filter(field => !field.hidden && Object.entries(field.when || {}).every(([key, value]) => {
        const match = allFields().find(candidate => candidate.id === key);
        return match && currentValue(match) === value;
      }));
      if (!fields.length) continue;
      const group = el("section", { class: "section", "aria-label": section.label });
      if (section.label) group.append(el("h2", { text: section.label }));
      for (const field of fields.filter(field => !field.advanced)) group.append(fieldRow(field));
      const advanced = fields.filter(field => field.advanced);
      if (advanced.length) {
        const disclosure = el("details", {class: "advanced-settings"}, [el("summary", {text: "Advanced options"})]);
        for (const field of advanced) disclosure.append(fieldRow(field));
        group.append(disclosure);
      }
      if(page.id === "translation") activeWorkspace.defaults.append(group); else main.append(group);
    }
    if (page.id === "appearance") {
      if (state.appearancePanel === "themes") renderThemes(main);
    }
    if (page.id === "menu-order") renderMenuOrder(main);
    if (page.id === "setup") activeWorkspace=window.TalkDatSetup({container:main,el,request:rpc,notice,changed:updateSaveStrip});
    if (page.id === "app-profiles") activeWorkspace=window.TalkDatAppProfiles({container:main,el,request:rpc,notice,changed:updateSaveStrip});
    if (["feedback","language-request"].includes(page.id)) activeWorkspace=window.TalkDatFeedback({container:main,el,request:rpc,notice,changed:updateSaveStrip,kind:page.id==="language-request"?"language":"feature"});
    if (page.id === "words") activeWorkspace=window.TalkDatWords({container:main,el,request:rpc,notice,changed:updateSaveStrip});
    if (page.id === "tools") renderTools(main);
    if (page.id === "history") activeWorkspace=window.TalkDatWorkspaces.history({container:main,el,request:rpc,notice});
    if (page.id === "scratchpad") activeWorkspace=window.TalkDatNotes({container:main,el,request:rpc,notice,changed:updateSaveStrip});
    if (page.id === "reset") activeWorkspace=window.TalkDatReset({container:main,el,request:rpc,notice,changed:updateSaveStrip});
    if (page.id === "privacy") {
      const clear=el("button",{text:"Clear local data"});
      clear.addEventListener("click",()=>navigate("reset"));
      main.append(el("div",{class:"action-list"},[clear]));
    }
    if (page.id === "recovery") activeWorkspace=window.TalkDatRecovery({container:main,el,request:rpc,notice});
    if(activeWorkspace)activeWorkspace.page=page.id;
    if (page.id === "account") renderAccount(main);
    if (page.id === "help") {
      for (const [label, name] of [["Getting started", "getting_started"], ["Model guide", "model_guide"], ["Share an idea", "feedback"], ["Check for updates", "check_updates"], ["Diagnostics", "diagnostics"]]) {
        if (!state.data.actions?.includes(name)) continue;
        const button = el("button", {text: label}); button.addEventListener("click", () => action(name, {}, button)); main.append(el("div", {class: "action-list"}, [button]));
      }
    }
    if (page.id === "menu") renderMenu(main);
    if (page.id === "speech" && state.data.actions?.includes("local_models")) {
      const button = el("button", {text:"Manage local models"});
      button.addEventListener("click", () => navigate("models")); main.append(el("div", {class:"action-list"}, [button]));
    }
    if (page.id === "models") { main.append(el("div", {id:"local-models"})); renderModelPanel(); }
    if (page.id === "model-guide") renderModelGuide(main);
    updateSaveStrip();
  }
  function renderModelGuide(main) {
    main.append(el("p", {class:"secondary", text:"Catalog reviewed " + state.data.model_catalog_date + ". Availability can change. Research candidates are informational and cannot be selected here."}));
    const search = el("input", {id:"model-guide-search", type:"search", maxlength:256, placeholder:"Name, provider or description"});
    const location = el("select", {id:"model-guide-location"});
    const availability = el("select", {id:"model-guide-availability"});
    for (const [value,text] of [["all","Anywhere"],["local","Local"],["cloud","Cloud"]]) location.append(el("option", {value,text}));
    for (const [value,text] of [["all","All models"],["wired","Ready in Talk DAT!"],["adapter_pending","Research candidates"]]) availability.append(el("option", {value,text}));
    search.value=state.guide.query;location.value=state.guide.location;availability.value=state.guide.availability;
    const count=el("p", {class:"secondary", role:"status", "aria-atomic":"true"});
    const results=el("div", {id:"model-guide-results"});
    main.append(el("div", {id:"model-guide-filters", class:"inline-form", role:"search", "aria-label":"Model catalog"}, [
      el("label", {for:search.id}, [el("span", {text:"Search models"}),search]),
      el("label", {for:location.id}, [el("span", {text:"Runs on"}),location]),
      el("label", {for:availability.id}, [el("span", {text:"Availability"}),availability]),
    ]),count,results);
    function filter() {
      state.guide={query:search.value,location:location.value,availability:availability.value};
      const query=search.value.trim().toLocaleLowerCase();
      const models=state.data.model_guide || [];
      const matches=models.filter(model => (location.value==="all" || (location.value==="local" ? model.mode==="local" : model.mode!=="local"))
        && (availability.value==="all" || model.status_id===availability.value)
        && [model.label,model.provider,model.notes].join(" ").toLocaleLowerCase().includes(query));
      count.textContent=matches.length+" of "+models.length+" models";
      results.replaceChildren(...matches.map(model => el("article", {class:"record"}, [el("h2", {text:model.label}), el("p", {class:"secondary", text:model.provider + " · " + model.mode + " · " + model.status}), el("p", {text:model.notes})])));
      if (!matches.length) results.append(el("p", {class:"record", text:"No models match these filters."}));
    }
    search.addEventListener("input",filter);location.addEventListener("change",filter);availability.addEventListener("change",filter);filter();
  }
  const materialCache = new Map(), materialRequests = new Map();
  let materialObserver = null, paletteSequence = 0;
  async function material(theme, size = "preview") {
    const key = theme + ":" + size;
    if (materialCache.has(key)) {
      const uri = materialCache.get(key); materialCache.delete(key); materialCache.set(key,uri); return uri;
    }
    if (materialRequests.has(key)) return materialRequests.get(key);
    const request = rpc("theme_asset", {theme,size}).then(result => {
      if (!/^data:image\/(png|webp);base64,[A-Za-z0-9+/=]+$/.test(result?.uri || "")) throw new Error("Theme material unavailable");
      materialCache.set(key,result.uri);
      while (materialCache.size > 6) materialCache.delete(materialCache.keys().next().value);
      return result.uri;
    }).finally(() => materialRequests.delete(key));
    materialRequests.set(key,request); return request;
  }
  function observeMaterial(image, theme, size = "preview") {
    image.dataset.theme = theme;
    image.dataset.size = size;
    if (!materialObserver) materialObserver = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) {
        materialObserver.unobserve(entry.target);
        material(entry.target.dataset.theme,entry.target.dataset.size).then(uri => { if (entry.target.isConnected) entry.target.src = uri; }).catch(() => {});
      }
    }, {root:$("page"), rootMargin:"120px"});
    materialObserver.observe(image);
  }
  function themeSample(theme, large = false) {
    const sample = el("span", {class:"theme-sample" + (large ? " large" : ""), "aria-hidden":"true"});
    for (const key of ["bg","panel","text","accent","muted","stroke","field"]) sample.style.setProperty("--"+key, theme[key]);
    const art = el("img", {alt:"", decoding:"async"}); observeMaterial(art,theme.name,large ? "full" : "preview");
    const scene = el("span", {class:"theme-scene"}, [
      el("span", {class:"theme-scene-title",text:"Talk DAT!"}),
      el("span", {class:"theme-scene-line"}), el("span", {class:"theme-scene-line short"}),
      el("span", {class:"theme-scene-pulse"}, [el("i"),el("i"),el("i"),el("i"),el("i")]),
    ]);
    sample.append(art, scene); return sample;
  }
  function renderThemes(main) {
    materialObserver?.disconnect();
    const selected = state.draft.get("ui.settings_theme") ?? state.data.theme;
    const current = state.data.themes.find(theme => theme.name === selected) || state.data.palette;
    if (!state.themes.mode) state.themes.mode = current.mode;
    const preview = el("div", {class:"theme-current"}, [themeSample(current,true), el("div", {}, [
      el("h2", {text:current.name}),
      el("p", {class:"secondary",text:state.draft.has("ui.settings_theme") ? "Previewing. Save changes to keep this theme." : "Your current theme"}),
    ])]);
    const search = el("input", {type:"search",id:"theme-search",placeholder:"Find a theme", "aria-label":"Find a theme",value:state.themes.query});
    const modes = el("div", {class:"segmented",role:"group","aria-label":"Theme brightness"});
    for (const mode of ["dark","light"]) {
      const button = el("button", {text:mode === "dark" ? "Dark" : "Light", "aria-pressed":state.themes.mode === mode});
      button.addEventListener("click", () => {state.themes.mode=mode; for(const b of modes.children)b.setAttribute("aria-pressed",String(b===button));draw();}); modes.append(button);
    }
    const count = el("p", {class:"secondary",role:"status"});
    const grid = el("div", {class:"theme-grid",role:"group","aria-label":"Color themes"});
    const draw = () => {
      for (const old of grid.querySelectorAll("img")) materialObserver?.unobserve(old);
      grid.replaceChildren();
      const query = state.themes.query.trim().toLowerCase();
      const matches = state.data.themes.filter(theme => theme.mode === state.themes.mode && (theme.name+" "+(theme.group||"")).toLowerCase().includes(query));
      count.textContent = matches.length + (matches.length === 1 ? " theme" : " themes");
      for (const theme of matches) {
        const button = el("button", {class:"theme-choice","aria-label":theme.name,"aria-pressed":selected === theme.name}, [themeSample(theme),el("span",{class:"theme-name",text:theme.family || theme.name.replace(/ (Dark|Light)$/,"")}),el("small",{text:theme.group || ""})]);
        button.addEventListener("click", () => {
          dirty({id:"ui.settings_theme",value:state.data.theme},theme.name); applyPalette(theme);
          const scroll = main.scrollTop; renderPage(); main.scrollTop=scroll;
          [...document.querySelectorAll(".theme-choice")].find(node=>node.getAttribute("aria-label")===theme.name)?.focus({preventScroll:true});
        }); grid.append(button);
      }
      if (!matches.length) grid.append(el("p",{class:"secondary",text:"No matching theme. Try a color or material, such as jade or stone."}));
    };
    search.addEventListener("input", () => {state.themes.query=search.value;draw();});
    main.append(preview,el("div",{class:"theme-filters"},[search,modes]),count,grid); draw();
  }
  function renderTools(main) {
    for (const tool of state.data.tools || []) {
      const button = el("button", { text: tool.button || "Open" }); button.addEventListener("click", () => action(tool.action, {}, button));
      main.append(el("div", { class: "tool-row" }, [el("div", {}, [el("h3", { text: tool.label }), el("p", { text: tool.description })]), button]));
    }
  }
  function renderModelPanel() {
    const panel = $("local-models"); if (!panel) return;
    panel.replaceChildren();
    const field = allFields().find(field => field.id === "stt.providers.local.model");
    const selected = field ? currentValue(field) : "";
    for (const model of state.data.models || []) {
      const status = model.state === "working" ? model.message : model.message || (model.downloaded ? "Downloaded" : "Not downloaded");
      const buttons = el("div", {class:"action-list"});
      const choose = el("button", {text:selected === model.id ? "Selected" : "Use this model", "aria-pressed":selected === model.id});
      choose.addEventListener("click", () => { if (field) { dirty(field,model.id); renderModelPanel(); } }); buttons.append(choose);
      if (!model.downloaded || model.state === "error") {
        const download = el("button", {text:model.state === "working" ? "Preparing…" : "Download"}); download.disabled = model.state === "working";
        download.addEventListener("click", () => action("model_download:"+model.id,{},download)); buttons.append(download);
      } else if (!model.custom) {
        const remove = el("button", {class:"quiet", text:"Remove download"}); remove.disabled=model.state === "working";
        remove.addEventListener("click", () => confirmModelRemoval(model)); buttons.append(remove);
      }
      panel.append(el("article", {class:"record"}, [el("h2", {text:model.label}), el("p", {class:"secondary",text:model.languages + (model.size_mb ? " · About " + model.size_mb + " MB" : "")}), el("p", {text:model.notes}), el("p", {role:"status",text:status}), buttons]));
    }
  }
  // Settings > Formatting: the local writing model's state, with the one
  // action that state allows. Same machinery as the Getting started step.
  // X-610: the finish picked after the third real dictation, with the
  // person's own words both ways. It used to be a square Tk window.
  function renderFinishChoice(choice) {
    const card = (title, detail, text, key, primary) => el("article", {class:"finish-card"}, [
      el("h3", {text:title}), el("p", {class:"secondary", text:detail}),
      el("div", {class:"finish-text", tabindex:"0", "aria-label":title + " version of your last dictation", text:text || "No words came back for this finish."}),
      el("button", {text:"Use " + title, ...(primary ? {class:"primary"} : {}), onclick:event => action("finish_choice:" + key, {}, event.currentTarget)})]);
    return el("section", {id:"finish-choice", class:"section finish-choice", "aria-label":"Pick your finish"}, [
      el("h2", {text:"Pick your finish"}),
      el("p", {class:"secondary", text:"Your last dictation, finished both ways. Pick the one you want every time. You can switch any time from the Pill menu."}),
      el("div", {class:"finish-cards"}, [
        card("Chill", "Your words, tidied: punctuation, capitals and lists.", choice.chill, "standard", true),
        card("Executive", "Also polished for work: filler gone, grammar fixed.", choice.executive, "executive", false)]),
      el("div", {class:"action-list"}, [el("button", {class:"quiet", text:"Decide later", onclick:event => action("finish_choice:later", {}, event.currentTarget)})])]);
  }
  function renderSmartFormatting() {
    const panel = $("smart-formatting"); if (!panel) return;
    const f = state.data?.smart_formatting; panel.hidden = !f; panel.replaceChildren(); if (!f) return;
    const buttons = el("div", {class:"control action-list"});
    const run = (name, text, primary=false) => { const b = el("button", {text, ...(primary ? {class:"primary"} : {})}); b.addEventListener("click", () => action("smart_formatting:"+name, {}, b)); buttons.append(b); };
    if (f.can_start) run("start", f.state === "failed" ? "Retry" : "Set up", f.recommended);
    if (f.download_page) { run("download_page", "Get Ollama"); run("check", "Check again"); }
    const details = [el("span", {class:"label", text:f.title}), el("span", {class:"description", text:f.explanation})];
    if (f.note) details.push(el("span", {class:"description", text:f.note}));
    details.push(el("span", {class:"description smart-formatting-state", role:"status", "aria-live":"polite", text:f.label + (f.message ? ". " + f.message : "")}));
    if (f.state === "downloading") details.push(el("progress", {max:100, ...(Number.isInteger(f.percent) ? {value:f.percent} : {}), "aria-label":f.label}));
    panel.append(el("h2", {text:f.title}), el("div", {class:"setting-row", "data-field":"smart-formatting"}, [el("div", {}, details), buttons]));
  }
  let formattingPoll = false;
  setInterval(async () => {
    if (formattingPoll || state.page !== "formatting" || !["downloading","checking"].includes(state.data?.smart_formatting?.state)) return;
    formattingPoll = true;
    try { const result = await rpc("action", {name:"smart_formatting:status"}); state.data.smart_formatting = result.smart_formatting; renderSmartFormatting(); }
    catch (error) { notice(error.message, true); }
    finally { formattingPoll = false; }
  }, 1000);
  function confirmModelRemoval(model) {
    const dialog = $("model-remove-dialog");
    $("model-remove-description").textContent = "Remove the downloaded files for " + model.label + "? " + (model.active ? "This is your active local model. It must be downloaded again before the next local dictation. " : "") + "You can install it again with Download.";
    $("model-remove-confirm").onclick = async () => { dialog.close(); await action("model_delete:"+model.id); };
    dialog.showModal();
  }
  $("model-remove-cancel").addEventListener("click", () => $("model-remove-dialog").close());
  let modelPoll = false;
  setInterval(async () => {
    if (modelPoll || state.page !== "models" || !state.data?.models?.some(model => model.state === "working")) return;
    modelPoll = true;
    try { const data=await rpc("state"); state.data.models=data.models; renderModelPanel(); }
    catch (error) { notice(error.message,true); }
    finally { modelPoll=false; }
  },1200);
  function renderAccount(main) {
    const account = state.data.account || {};
    main.append(el("section", { class: "section" }, [el("h2", { text: account.title || "Your account" }), el("p", { class: "secondary", text: account.description || "Open your account to view access and sign-in options." })]));
    const button = el("button", { text: "Manage account" }); button.addEventListener("click", () => action("account", {}, button)); main.append(el("div", { class: "action-list" }, [button]));
  }
  let menuBack = null, menuReflow = null;
  function menuKeys(list) {
    list.addEventListener("keydown", event => {
      const buttons = [...list.querySelectorAll('[role="menuitem"]')].filter(b => !b.hidden && !b.disabled && b.getClientRects().length);
      if (!buttons.length) return;
      let index = buttons.indexOf(document.activeElement);
      if (event.key === "ArrowDown") index = (index + 1) % buttons.length;
      else if (event.key === "ArrowUp") index = (index - 1 + buttons.length) % buttons.length;
      else if (event.key === "Home") index = 0; else if (event.key === "End") index = buttons.length - 1; else return;
      event.preventDefault(); buttons[index]?.focus();
    });
  }
  window.addEventListener("resize", () => menuReflow?.());
  function renderMenuOrder(main) {
    const field = allFields().find(field => field.id === "overlay.menu_order");
    if (!field) return;
    const rows = state.data.menu || [], byId = new Map(rows.map(row => [row.id,row]));
    let order = JSON.parse(currentValue(field) || "[]");
    if (!order.length) order = [...rows].sort((a,b) => a.default_index-b.default_index).map(row => row.id);
    order = [...new Set([...order, ...rows.map(row => row.id)])].filter(id => byId.has(id));
    const daily = order.filter(id => !byId.get(id).fixed), fixed = rows.filter(row => row.fixed);
    for (const [index,id] of daily.entries()) {
      const up = el("button", {text:"Move up", "aria-label":"Move " + byId.get(id).label + " up"}); up.disabled = index === 0;
      const down = el("button", {text:"Move down", "aria-label":"Move " + byId.get(id).label + " down"}); down.disabled = index === daily.length-1;
      const move = delta => { [daily[index],daily[index+delta]] = [daily[index+delta],daily[index]]; dirty(field,JSON.stringify([...daily,...fixed.map(row=>row.id)])); renderPage(); document.querySelector('[aria-label="Move '+byId.get(id).label+(delta<0?' up':' down')+'"]')?.focus(); };
      up.addEventListener("click", () => move(-1)); down.addEventListener("click", () => move(1));
      main.append(el("div", {class:"menu-order-row"}, [el("span", {text:byId.get(id).label}),up,down]));
    }
    main.append(el("p", {class:"secondary",text:"App controls: " + fixed.map(row=>row.label).join(", ")}));
    const reset = el("button", {text:"Use default order"});
    reset.addEventListener("click", () => { dirty(field,"[]"); renderPage(); }); main.append(el("div", {class:"action-list"}, [reset]));
  }
  function renderMenu(main) {
    menuBack = null;
    const iconNames = {settings:"general",paste_last:"paste",history:"history",more_features:"tools",stats:"stats",ramble:"formatting",captions:"captions",translation:"translation",scratchpad:"scratchpad",scribe:"scribe",local_models:"dictation",check_updates:"update",restart_app:"restart",quit_app:"power"};
    // Tools' child rows carry only an action ("menu:captions"), no id. Looking
    // the icon up by `item.id` alone gave Live captions and Translate the
    // generic sliders; the action names the destination just as well.
    const entry = item => {
      const key = item.id || item.action?.replace("menu:","") || "";
      return {...item, icon:iconNames[key] || (Object.prototype.hasOwnProperty.call(icons,key) || maskIcons.has(key) ? key : "general")};
    };
    const show = (title, rows, back = null) => {
      main.replaceChildren(); menuBack = back;
      const heading = el("div", {class:"pill-menu-heading"});
      if (back) { const previous=el("button", {class:"quiet menu-back",text:"‹", "aria-label":"Back to menu"}); previous.addEventListener("click",back); heading.append(previous); }
      heading.append(el("h1", {text:title}));
      const close=el("button", {class:"quiet menu-close",text:"×", "aria-label":"Close menu"}); close.addEventListener("click",()=>rpc("dismiss").catch(e=>notice(e.message,true))); heading.append(close);
      const list=el("div", {class:"menu-items",role:"menu","aria-label":title});
      for (const item of rows) {
        const text=el("span", {class:"menu-label"}, [el("span", {text:item.label})]);
        if (item.description) text.append(el("small",{text:item.description}));
        const button=el("button", {role:"menuitem",class:"menu-row", "data-action":item.action || item.id || "", "aria-label":item.label}, [icon(item.icon || "general"),text]);
        if (item.run) button.append(el("span", {class:"menu-chevron",text:"›","aria-hidden":"true"}));
        button.addEventListener("click",()=>item.run ? item.run() : action(item.action,{},button));
        list.append(button);
      }
      const pager=el("div", {class:"menu-pagination"});
      const prev=el("button", {class:"quiet",text:"Previous"}), next=el("button", {class:"quiet",text:"Next"}), position=el("span", {class:"secondary", "aria-live":"polite"});
      pager.append(prev,position,next);main.append(heading,list,pager); menuKeys(list);
      let page=0, count=1;
      const layout = () => {
        if (!main.isConnected || state.page!=="menu") return;
        const available=main.clientHeight-heading.offsetHeight-pager.offsetHeight-16;
        count=Math.max(1,Math.floor(available/54));
        page=Math.min(page,Math.max(0,Math.ceil(rows.length/count)-1));
        [...list.children].forEach((button,index)=>{button.hidden=index<page*count || index>=(page+1)*count;});
        prev.disabled=page===0;next.disabled=(page+1)*count>=rows.length;
        const multiple=rows.length>count;
        prev.style.visibility=next.style.visibility=multiple?"visible":"hidden";
        position.textContent=multiple ? `${page+1} / ${Math.ceil(rows.length/count)}` : "Esc to close";
      };
      prev.addEventListener("click",()=>{page--;layout();list.querySelector("button:not([hidden])")?.focus();});
      next.addEventListener("click",()=>{page++;layout();list.querySelector("button:not([hidden])")?.focus();});
      menuReflow=layout;layout();requestAnimationFrame(layout);
      list.querySelector("button:not([hidden])")?.focus({preventScroll:true});
    };
    const home = () => {
      const daily=(state.data.menu||[]).filter(item=>!item.fixed).map(item=> {
        const row=entry(item);
        if(item.children) row.run=()=>show(row.label,item.children.map(entry),home);
        return row;
      });
      daily.push({id:"speech-route",label:"Speech",description:state.data.route==="local"?"Local · on this computer":"Your key · connected provider",icon:"dictation",run:()=>show("Speech",[
        {label:"Local speech",description:"Process on this computer",icon:"dictation",action:"route:local"},
        {label:"Use your key",description:"Use your configured provider",icon:"account",action:"route:byok"}],home)},
        {id:"writing-finish",label:"Formatting",description:state.data.intensity==="executive"?"Executive · polished writing":"Chill · natural writing",icon:"formatting",run:()=>show("Formatting",[
          {label:state.data.intensity==="executive"?"Switch to Chill":"Switch to Executive",description:state.data.intensity==="executive"?"Keep your natural speaking style":"Polish and structure your writing",icon:"formatting",action:"menu:toggle_intensity"},
          {label:"Writing settings",description:"Numbers, punctuation and cleanup",icon:"general",action:"menu:formatting"}],home)},
        {id:"application",label:"App controls",description:"Updates, restart, quit and help",icon:"power",run:()=>show("App controls",[
          ...(state.data.menu||[]).filter(item=>item.fixed).map(entry),
          {label:"Arrange menu",description:"Choose your daily order",icon:"appearance",action:"menu_order"},
          {label:"Help",description:"Guides and feature reference",icon:"help",action:"menu:help"}],home)});
      show("Talk DAT!",daily);
    };
    home();
  }
  function applyPalette(palette = {}) {
    for (const key of ["bg", "panel", "surface", "field", "text", "muted", "accent", "button", "select", "stroke", "danger", "ring"]) if (palette[key]) document.documentElement.style.setProperty("--" + key, palette[key]);
    if (palette.on_accent) document.documentElement.style.setProperty("--on-accent", palette.on_accent);
    document.documentElement.style.colorScheme = palette.mode === "light" ? "light" : "dark";
    document.body.classList.toggle("material-art", Boolean(palette.material_art));
    const sequence = ++paletteSequence;
    document.documentElement.style.removeProperty("--theme-material");
    if (palette.name && !state.data?.high_contrast) material(palette.name,"full").then(uri => {
      if (sequence === paletteSequence) document.documentElement.style.setProperty("--theme-material",'url("'+uri+'")');
    }).catch(() => {});
  }
  function receive(data) {
    if (!data || !Array.isArray(data.pages)) return;
    state.data = data;
    linkRestored();
    document.body.classList.toggle("reduce-motion", Boolean(data.reduce_motion));
    document.body.classList.toggle("high-contrast", Boolean(data.high_contrast));
    const fonts = {system: '"Segoe UI", -apple-system, BlinkMacSystemFont, sans-serif', constantia: 'Constantia, Georgia, serif', candara: 'Candara, "Segoe UI", sans-serif', knight: 'Knight, "Segoe UI", sans-serif'};
    document.documentElement.style.setProperty("--ui-font", fonts[data.app_font] || fonts.system);
    applyPalette(data.palette);
    const themeDraft = state.draft.get("ui.settings_theme");
    if (themeDraft) applyPalette(data.themes?.find(theme => theme.name === themeDraft));
    if (!data.pages.some(page => page.id === state.page)) state.page = data.pages[0]?.id;
    if (searchActive && $("search").value.trim()) renderSearch(); else renderPage();
  }
  async function refresh() { try { receive(await rpc("state", { page: state.page })); } catch (error) { notice(error.message, true); } }
  async function navigate(page, field = "") {
    if(activeWorkspace && page!==state.page && !await activeWorkspace.leave())return;
    if(page==="reset" && (state.draft.size || state.invalid.size)){
      notice("Save or discard your settings changes before clearing local data.",true);return;
    }
    state.page = page; $("search").value = "";searchActive=false;searchSequence++;
    if (page === "appearance" && field) {
      const section = state.data?.pages.find(p=>p.id===page)?.sections.find(s=>s.fields.some(f=>f.id===field))?.label;
      state.appearancePanel = section === "Text and motion" ? "text" : section === "Pill details" ? "pill" : "themes";
      if (field === "overlay.menu_order") { page="menu-order"; state.page=page; }
    }
    document.body.classList.toggle("menu-view", page === "menu");
    renderPage();
    await refresh();
    if(state.page!==page||$("search").value.trim())return;
    if(page==="dictation"&&state.data?.microphones?.status==="idle")await action("refresh_microphones");
    $("page").scrollTop = 0;
    if (field) { const row = [...document.querySelectorAll("[data-field]")].find(node => node.dataset.field === field); const disclosure = row?.closest("details"); if (disclosure) disclosure.open = true; row?.scrollIntoView({ block: "center" }); row?.querySelector("button,input,select,textarea")?.focus(); }
    else if (page !== "menu") $("page").focus({ preventScroll: true });
  }
  let searchSequence=0;
  $("search").addEventListener("input", async () => {
    const sequence=++searchSequence;
    const allowed=!activeWorkspace||await activeWorkspace.leave();
    if(sequence!==searchSequence)return;
    if(!allowed) { $("search").value="";return; }
    if($("search").value.trim()) { activeWorkspace?.dispose?.();activeWorkspace=null; }
    renderSearch();
  });
  function renderSearch() {
    const query = $("search").value.trim().toLowerCase(); searchActive=Boolean(query); if (!query) { renderPage(); return; }
    activeShortcut?.();
    const main = $("page"); main.replaceChildren(intro({ title:"Search", description:"Settings, tools and guides in one place." }));
    let count = 0;
    const matches = content => query.split(/\s+/).every(word => content.toLowerCase().includes(word));
    for (const tool of state.data?.tools || []) {
      if (!matches(tool.label+" "+tool.description)) continue;
      const button = el("button", {class:"search-result",text:tool.label}, [el("small",{text:"Tool: "+tool.description})]);
      button.addEventListener("click",()=>action(tool.action,{},button)); main.append(button); count++;
    }
    for (const page of state.data?.pages || []) {
      if (page.id === "menu" || !matches(page.label+" "+page.description+" "+(page.keywords||""))) continue;
      const button=el("button",{class:"search-result",text:page.label},[el("small",{text:page.description})]);
      button.addEventListener("click",()=>navigate(page.id));main.append(button);count++;
    }
    for (const page of state.data?.pages || []) for (const section of page.sections || []) for (const field of section.fields || []) {
      if (page.id === "words") continue;
      const content = `${field.label} ${field.description} ${section.label} ${page.label}`.toLowerCase();
      if (!query.split(/\s+/).every(word => content.includes(word))) continue;
      const button = el("button", { class: "search-result", text: field.label }, [el("small", { text: page.label + ": " + (field.description || section.label) })]);
      button.addEventListener("click", () => navigate(page.id, field.id)); main.append(button); count++;
    }
    if (!count) main.append(el("p", { class: "secondary", text: "No matches. Try “microphone”, “History” or “formatting”." }));
  }
  $("help-button").prepend(icon("help"));
  document.querySelector(".search>span").replaceWith(icon("search"));
  const help = { pinned: false, openTimer: 0, closeTimer: 0, owner: null };
  function showHelp(pin = false) { clearTimeout(help.openTimer); clearTimeout(help.closeTimer); help.pinned = pin || help.pinned; help.owner = $("help-button"); $("help-popover").hidden = false; $("help-button").setAttribute("aria-expanded", "true"); }
  function closeHelp(restore = false) { clearTimeout(help.openTimer); clearTimeout(help.closeTimer); help.pinned = false; $("help-popover").hidden = true; $("help-button").setAttribute("aria-expanded", "false"); if (restore) help.owner?.focus(); }
  $("help-button").addEventListener("pointerenter", () => { clearTimeout(help.closeTimer); help.openTimer = setTimeout(() => showHelp(), 320); });
  $("help-button").addEventListener("pointerleave", () => { clearTimeout(help.openTimer); if (!help.pinned) help.closeTimer = setTimeout(() => closeHelp(), 620); });
  $("help-popover").addEventListener("pointerenter", () => clearTimeout(help.closeTimer));
  $("help-popover").addEventListener("pointerleave", () => { if (!help.pinned) help.closeTimer = setTimeout(() => closeHelp(), 620); });
  $("help-button").addEventListener("click", () => { if (help.pinned && !$("help-popover").hidden) closeHelp(true); else showHelp(true); });
  $("help-close").addEventListener("click", () => closeHelp(true));
  document.addEventListener("pointerdown", event => { if (!$("help-popover").contains(event.target) && !$("help-button").contains(event.target)) closeHelp(); });
  document.addEventListener("keydown", event => { if (event.key === "Escape") { if (!$("help-popover").hidden) { closeHelp(true); event.preventDefault(); } else if (state.page === "menu") { if(menuBack) menuBack();else rpc("close").catch(() => {}); event.preventDefault(); } } });
  $("save").addEventListener("click", () => save());
  $("discard").addEventListener("click", () => { state.draft.clear(); state.invalid.clear(); applyPalette(state.data.palette); renderPage(); });
  function cancelClose() { state.closingRequested = false; rpc("cancel_close").catch(() => {}); }
  $("continue-editing").addEventListener("click", () => { $("close-dialog").close(); cancelClose(); });
  $("close-dialog").addEventListener("cancel", cancelClose);
  $("discard-close").addEventListener("click", async () => {
    state.draft.clear(); state.invalid.clear(); updateSaveStrip(); $("close-dialog").close();
    try { await rpc("close"); } catch (error) { notice(error.message, true); }
  });
  $("save-close").addEventListener("click", async () => { $("close-dialog").close(); await save(true); });
  $("conflict-cancel").addEventListener("click", () => { $("conflict-dialog").close(); cancelClose(); });
  $("conflict-dialog").addEventListener("cancel", cancelClose);
  $("conflict-latest").addEventListener("click", () => { state.draft.clear(); state.invalid.clear(); $("conflict-dialog").close(); receive(state.data); if (state.closingRequested) rpc("close").catch(() => {}); });
  $("conflict-keep").addEventListener("click", () => { state.draftRevision = state.data.revision; $("conflict-dialog").close(); save(state.closingRequested); });
  window.TalkDat = Object.freeze({ receive, navigate, refresh, requestClose: async () => { if(activeWorkspace&&!await activeWorkspace.leave()){cancelClose();return;} state.closingRequested = true; if (state.draft.size || state.invalid.size) { if (!$("close-dialog").open) $("close-dialog").showModal(); } else rpc("close").catch(() => {}); } });
  window.addEventListener("blur", () => { if (state.page === "menu") rpc("dismiss").catch(() => {}); });
  window.addEventListener("pywebviewready", refresh);
  if (window.pywebview?.api) refresh();
})();
