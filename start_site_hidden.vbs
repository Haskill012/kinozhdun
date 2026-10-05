Option Explicit

Dim shell, folder, python, siteUrl
Set shell = CreateObject("WScript.Shell")
folder = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
python = Chr(34) & folder & "\.venv\Scripts\python.exe" & Chr(34)
siteUrl = "http://127.0.0.1:8099/"

' The web server stays detached from this launcher, so closing the browser does not stop it.
shell.Run python & " -m website", 0, False
WScript.Sleep 1200
shell.Run siteUrl, 1, False
