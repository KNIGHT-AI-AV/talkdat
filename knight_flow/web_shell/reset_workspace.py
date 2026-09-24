"""A one-use, expiring reset preview. Only the engine supplies filesystem paths."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import secrets
import threading
import time

from knight_flow.reset import CATEGORIES, CATEGORY_BY_KEY, PRESETS, PRESET_LABELS, ORDINARY, plan, human_size

def config_revision(config, keys):
    values = {}
    for key in keys:
        node = config
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                node = {"__reset_missing__": True}; break
            node = node[part]
        values[key] = node
    return hashlib.sha256(json.dumps(values,sort_keys=True,ensure_ascii=True,allow_nan=False).encode()).hexdigest()

class ResetWorkspace:
    def __init__(self, config, root, post, busy, execute, finish, *, launch=None, clock=time.monotonic):
        self.config, self.root, self.post, self.busy = config, Path(root), post, busy
        self.execute, self.finish = execute, finish
        self.launch = launch or (lambda work:threading.Thread(target=work,name="TalkDatResetPreview",daemon=True).start())
        self.clock=clock
        self.generation=0;self.phase="choose";self.message="Choose what to clear. Personal data starts unchecked."
        self.error=False;self.pending=None;self.result=None;self.closed=False

    def snapshot(self):
        preview=None
        if self.pending is not None:
            pending=self.pending;intended=pending["plan"]
            preview={"token":pending["token"],"categories":[category.key for category in intended.categories],
                "labels":[category.label for category in intended.categories],
                "files":[path.name for path in intended.files],"bytes":intended.bytes_freed,
                "size":human_size(intended.bytes_freed),"personal":any(category.weight!=ORDINARY for category in intended.categories),
                "account":intended.touches_account}
        return {"phase":self.phase,"message":self.message,"error":self.error,"preview":preview,"result":self.result,
            "categories":[{"id":category.key,"label":category.label,"description":category.consequence,
                           "weight":category.weight,"checked":category.default_checked} for category in CATEGORIES],
            "presets":[{"id":key,"label":PRESET_LABELS[key],"categories":list(value)} for key,value in PRESETS.items()]}

    def handle(self,payload):
        if type(payload) is not dict or type(payload.get("command")) is not str:
            raise ValueError("Choose an available reset action.")
        command=payload["command"]
        shapes={"state":{"command"},"preview":{"command","selected"},"cancel":{"command"},
                "confirm":{"command","token","phrase"},"finish":{"command"}}
        if command not in shapes or set(payload)!=shapes[command]:
            raise ValueError("Choose an available reset action.")
        if command=="state":return self.snapshot()
        if self.phase=="erasing" or (self.phase=="done" and command!="finish"):
            raise ValueError("The reset is already confirmed. Close Talk DAT when it finishes.")
        if command=="finish":
            if self.phase!="done":raise ValueError("Finish or cancel the reset first.")
            self.finish();return self.snapshot()
        if command=="cancel":
            self.generation+=1;self.pending=None;self.phase="choose";self.error=False
            self.message="Nothing was erased.";return self.snapshot()
        if command=="preview":
            selected=payload["selected"]
            if type(selected) is not list or not selected or len(selected)>len(CATEGORIES) or any(type(key)is not str or key not in CATEGORY_BY_KEY for key in selected):
                raise ValueError("Select one or more listed categories.")
            selected=list(dict.fromkeys(selected))
            if self.busy():raise ValueError("Finish recording, downloads and exports before starting a reset.")
            self.generation+=1;generation=self.generation;self.pending=None;self.phase="scanning";self.error=False
            self.message="Checking the selected data. Nothing is being erased."
            keys=tuple(key for category in CATEGORIES if category.key in selected for key in category.config_keys)
            revision=config_revision(self.config,keys)
            def work():
                try:intended=plan(selected,self.root);failure=None
                except ValueError as error:intended=None;failure=str(error)
                except Exception:intended=None;failure="The selected data could not be read. Nothing was erased."
                def complete():
                    if generation!=self.generation or self.closed:return
                    if failure:
                        self.phase="choose";self.error=True;self.message=failure;return
                    if config_revision(self.config,keys)!=revision:
                        self.phase="choose";self.error=True;self.message="The selected settings changed. Preview again.";return
                    self.pending={"plan":intended,"token":secrets.token_hex(16),"revision":revision,"created":self.clock()}
                    self.phase="review";self.message="Review this list before confirming. Talk DAT will need to close afterward."
                self.post(complete)
            try:self.launch(work)
            except Exception:self.phase="choose";self.error=True;self.message="The preview could not start. Try again."
            return self.snapshot()
        if command=="confirm":
            pending=self.pending
            if pending is None or type(payload["token"]) is not str or not secrets.compare_digest(payload["token"],pending["token"]):
                raise ValueError("Preview the selected categories before confirming.")
            if not 0<=self.clock()-pending["created"]<300:
                self.pending=None;self.phase="choose";raise ValueError("The preview expired. Preview again.")
            intended=pending["plan"]
            personal=any(category.weight!=ORDINARY for category in intended.categories)
            if type(payload["phrase"]) is not str or payload["phrase"]!=("ERASE" if personal else ""):
                raise ValueError("Type ERASE exactly to confirm personal data removal.")
            if self.busy():raise ValueError("Finish recording, downloads and exports before starting a reset.")
            if config_revision(self.config,intended.config_keys)!=pending["revision"]:
                self.pending=None;self.phase="choose";raise ValueError("The selected settings changed. Preview again.")
            self.pending=None;self.phase="erasing";self.error=False;self.message="Closing background activity before erasing the selected data."
            def complete(result=None,error=None):
                if error:
                    self.phase="choose";self.error=True;self.message=str(error);return
                self.phase="done";self.result=result;self.error=bool(result.get("failed"))
                self.message=("Some selected items could not be removed." if self.error else "The selected items were cleared.")+" Close Talk DAT, then open it again."
            try:self.execute(intended,pending["revision"],complete)
            except Exception as error:complete(error=error)
            return self.snapshot()

    def close(self):
        self.closed=True
        if self.phase!="erasing":self.generation+=1;self.pending=None

