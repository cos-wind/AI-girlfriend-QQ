Set shell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
pythonw = shell.ExpandEnvironmentStrings("%SystemRoot%") & "\py.exe"
pythonwFallback = shell.ExpandEnvironmentStrings("%LocalAppData%") & "\Programs\Python\Python311\pythonw.exe"
launcherPath = scriptDir & "\hidden_launcher.py"
command = Chr(34) & pythonwFallback & Chr(34) & " " & Chr(34) & launcherPath & Chr(34)
If CreateObject("Scripting.FileSystemObject").FileExists(pythonw) Then
  command = Chr(34) & pythonw & Chr(34) & " -3 " & Chr(34) & launcherPath & Chr(34)
End If
If Not CreateObject("Scripting.FileSystemObject").FileExists(pythonw) And Not CreateObject("Scripting.FileSystemObject").FileExists(pythonwFallback) Then
  shell.Run "pythonw.exe " & Chr(34) & launcherPath & Chr(34), 0, False
Else
  shell.Run command, 0, False
End If
