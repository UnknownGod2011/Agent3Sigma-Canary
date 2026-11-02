#!/usr/bin/env python3
"""Bounded allowlisted container-to-host export without docker cp extraction."""
from __future__ import annotations
import base64, json, os, re, shutil, subprocess, tempfile
from pathlib import Path

MAX_FILE=32*1024*1024
MAX_TOTAL=64*1024*1024
MAX_FILES=128
MAX_STATE=64*1024
AGENT_ID_RE=re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
NAME_RE=re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,255}\.jsonl\Z")

TRANSCRIPT_SCRIPT=r'''\
import base64,json,os,re,stat,sys
NAME_RE=re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,255}\.jsonl\Z")
MAX_FILE=32*1024*1024
MAX_TOTAL=64*1024*1024
MAX_FILES=128
def open_dir(path):
    if not path.startswith("/"): raise ValueError("absolute path required")
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
    fd=os.open("/",flags)
    try:
        for part in path.split("/")[1:]:
            if not part or part in {".",".."}: raise ValueError("invalid path component")
            nxt=os.open(part,flags,dir_fd=fd); os.close(fd); fd=nxt
        return fd
    except Exception:
        os.close(fd); raise
try: root_fd=open_dir(sys.argv[1])
except FileNotFoundError:
    print(json.dumps({"files":[]})); raise SystemExit(0)
files=[]; total=0
try:
    for name in sorted(os.listdir(root_fd)):
        if not NAME_RE.fullmatch(name): continue
        before=os.stat(name,dir_fd=root_fd,follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1: continue
        if before.st_size<0 or before.st_size>MAX_FILE: raise ValueError("transcript too large")
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=root_fd)
        try:
            opened=os.fstat(fd)
            if (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino): continue
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink!=1: continue
            chunks=[]; remaining=MAX_FILE+1
            while remaining:
                chunk=os.read(fd,min(1024*1024,remaining))
                if not chunk: break
                chunks.append(chunk); remaining-=len(chunk)
            data=b"".join(chunks); after=os.fstat(fd)
            if len(data)>MAX_FILE: raise ValueError("transcript too large")
            if (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=(opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns):
                raise ValueError("transcript changed while exporting")
        finally: os.close(fd)
        total+=len(data)
        if total>MAX_TOTAL: raise ValueError("transcript export too large")
        files.append({"name":name,"mtime_ns":opened.st_mtime_ns,"data":base64.b64encode(data).decode("ascii")})
        if len(files)>MAX_FILES: raise ValueError("too many transcript files")
finally: os.close(root_fd)
print(json.dumps({"files":files},separators=(",",":")))
'''

STATE_SCRIPT=r'''\
import base64,json,os,stat,sys
MAX_STATE=64*1024
def open_dir(path):
    if not path.startswith("/"): raise ValueError("absolute path required")
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
    fd=os.open("/",flags)
    try:
        for part in path.split("/")[1:]:
            if not part or part in {".",".."}: raise ValueError("invalid path component")
            nxt=os.open(part,flags,dir_fd=fd); os.close(fd); fd=nxt
        return fd
    except Exception:
        os.close(fd); raise
try: parent_fd=open_dir(sys.argv[1])
except FileNotFoundError:
    print(json.dumps({"status":"missing"})); raise SystemExit(0)
try:
    try: fd=os.open(sys.argv[2],os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent_fd)
    except FileNotFoundError:
        print(json.dumps({"status":"missing"})); raise SystemExit(0)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>MAX_STATE:
            raise ValueError("state artifact is not a bounded regular file")
        chunks=[]; remaining=MAX_STATE+1
        while remaining:
            chunk=os.read(fd,min(16384,remaining))
            if not chunk: break
            chunks.append(chunk); remaining-=len(chunk)
        data=b"".join(chunks); after=os.fstat(fd)
        if len(data)>MAX_STATE: raise ValueError("state artifact too large")
        if (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns):
            raise ValueError("state artifact changed while exporting")
    finally: os.close(fd)
finally: os.close(parent_fd)
print(json.dumps({"status":"present","data":base64.b64encode(data).decode("ascii")},separators=(",",":")))
'''

def _remove(path:Path)->None:
    if path.is_symlink() or path.is_file(): path.unlink(missing_ok=True)
    elif path.is_dir(): shutil.rmtree(path)

def _run(container_id:str,script:str,*args:str,timeout:int=30):
    return subprocess.run(["docker","exec",container_id,"python3","-c",script,*args],
                          capture_output=True,text=True,check=False,timeout=timeout)

def _payload(result,label:str)->dict:
    if result.returncode!=0:
        raise RuntimeError(f"{label} failed inside container: {(result.stderr or result.stdout).strip()}")
    try: value=json.loads(result.stdout)
    except (TypeError,ValueError) as exc: raise RuntimeError(f"{label} returned invalid JSON") from exc
    if not isinstance(value,dict): raise RuntimeError(f"{label} returned invalid payload")
    return value

def export_transcripts(container_id:str,agent_id:str,workspace:str|Path,transcript_dir:str|Path)->str:
    """Export only regular sessions/*.jsonl files; host controls all destinations."""
    if not container_id: return ""
    if not isinstance(agent_id,str) or not AGENT_ID_RE.fullmatch(agent_id) or agent_id in {".",".."}:
        raise ValueError(f"unsafe agent id: {agent_id!r}")
    root=f"/root/.openclaw/agents/{agent_id}/sessions"
    payload=_payload(_run(container_id,TRANSCRIPT_SCRIPT,root),"transcript export")
    files=payload.get("files")
    if not isinstance(files,list): raise RuntimeError("transcript export missing files")
    normalized=agent_id.replace(":","-").lower()
    if not files and normalized!=agent_id:
        payload=_payload(_run(container_id,TRANSCRIPT_SCRIPT,f"/root/.openclaw/agents/{normalized}/sessions"),
                         "normalized transcript export")
        files=payload.get("files")
        if not isinstance(files,list): raise RuntimeError("normalized transcript export missing files")
    local=Path(f"{workspace}{transcript_dir}/{agent_id}")
    if local.is_symlink(): _remove(local)
    local.mkdir(parents=True,exist_ok=True)
    sessions=local/"sessions"
    _remove(sessions)
    sessions.mkdir(parents=True,exist_ok=True)
    seen=set(); total=0
    for item in files:
        if not isinstance(item,dict) or set(item)!={"name","mtime_ns","data"}:
            raise RuntimeError("invalid transcript record")
        name=item["name"]
        if not isinstance(name,str) or not NAME_RE.fullmatch(name) or name in seen:
            raise RuntimeError(f"unsafe or duplicate transcript name: {name!r}")
        seen.add(name)
        mtime=item["mtime_ns"]
        if not isinstance(mtime,int) or mtime<0: raise RuntimeError("invalid transcript mtime")
        try: data=base64.b64decode(item["data"],validate=True)
        except (TypeError,ValueError) as exc: raise RuntimeError("invalid transcript base64") from exc
        total+=len(data)
        if len(data)>MAX_FILE or total>MAX_TOTAL or len(seen)>MAX_FILES:
            raise RuntimeError("transcript export exceeds limits")
        target=sessions/name
        if target.is_symlink() or target.is_dir(): _remove(target)
        fd,tmp=tempfile.mkstemp(prefix=".transcript-",dir=sessions)
        temporary=Path(tmp)
        try:
            with os.fdopen(fd,"wb") as handle:
                handle.write(data); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary,target); os.utime(target,ns=(mtime,mtime),follow_symlinks=False)
        finally: temporary.unlink(missing_ok=True)
    return str(local)

def read_state_artifact(container_id:str)->bytes|None:
    if not container_id: raise RuntimeError("no active container")
    payload=_payload(_run(container_id,STATE_SCRIPT,"/tmp/agentcanary-desktop",
                          "desktop_baseline_state.json",timeout=10),"desktop state export")
    if payload=={"status":"missing"}: return None
    if set(payload)!={"status","data"} or payload.get("status")!="present":
        raise RuntimeError("invalid state export status")
    try: data=base64.b64decode(payload["data"],validate=True)
    except (TypeError,ValueError) as exc: raise RuntimeError("invalid state export base64") from exc
    if len(data)>MAX_STATE: raise RuntimeError("state artifact exceeds size limit")
    return data

def write_state_artifact(workspace:str|Path,data:bytes|None,filename:str)->bool:
    if (
        not isinstance(filename, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", filename)
    ):
        raise ValueError("unsafe artifact filename")
    root=Path(workspace); root.mkdir(parents=True,exist_ok=True)
    target=root/filename; temporary=root/f".{filename}.copyback"
    _remove(target); _remove(temporary)
    if data is None: return False
    if not isinstance(data,bytes) or len(data)>MAX_STATE: raise ValueError("invalid state artifact bytes")
    try:
        with temporary.open("xb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary,target)
    finally: temporary.unlink(missing_ok=True)
    return True
