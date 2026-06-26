Set shell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
pythonw = shell.ExpandEnvironmentStrings("%LocalAppData%") & "\Programs\Python\Python311\pythonw.exe"
launcherPath = scriptDir & "\hidden_watcher.py"
If CreateObject("Scripting.FileSystemObject").FileExists(pythonw) Then
  shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & launcherPath & Chr(34), 0, False
Else
  shell.Run "pythonw.exe " & Chr(34) & launcherPath & Chr(34), 0, False
End If
