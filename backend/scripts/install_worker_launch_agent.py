"""Install/reload the durable worker as a per-user macOS LaunchAgent."""
import os
import plistlib
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BACKEND=ROOT/"backend"
HOME=Path.home()
label="com.labprocessrag.worker"
agents=HOME/"Library"/"LaunchAgents"
agents.mkdir(parents=True,exist_ok=True)
(ROOT/"data"/"logs").mkdir(parents=True,exist_ok=True)
plist=agents/f"{label}.plist"
payload={
    "Label":label,"ProgramArguments":[str(BACKEND/".venv"/"bin"/"python"),"-m","app.worker"],
    "WorkingDirectory":str(BACKEND),"RunAtLoad":True,"KeepAlive":True,
    "EnvironmentVariables":{"PATH":"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
    "StandardOutPath":str(ROOT/"data"/"logs"/f"{label}.log"),
    "StandardErrorPath":str(ROOT/"data"/"logs"/f"{label}.error.log"),
}
with plist.open("wb") as stream:plistlib.dump(payload,stream)
domain=f"gui/{os.getuid()}"
service=f"{domain}/{label}"
check=subprocess.run(["launchctl","print",service],capture_output=True,text=True)
if check.returncode==0:
    subprocess.run(["launchctl","kickstart","-k",service],check=True)
else:
    subprocess.run(["launchctl","bootstrap",domain,str(plist)],check=True)
print(f"Installed and started {service} using {plist}")
