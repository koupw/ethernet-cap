Set ws = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
dir = fs.GetParentFolderName(WScript.ScriptFullName)
ws.Run """" & dir & "\venv\Scripts\pythonw.exe"" """ & dir & "\gui\launcher.py""", 0, False
