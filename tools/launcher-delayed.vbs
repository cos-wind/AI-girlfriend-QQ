Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' 等待 10 秒，确保系统环境完全加载
WScript.Sleep 10000

pythonw = shell.ExpandEnvironmentStrings("%LocalAppData%") & "\Programs\Python\Python311\pythonw.exe"
launcherPath = scriptDir & "\hidden_watcher.py"

If fso.FileExists(pythonw) Then
    shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & launcherPath & Chr(34), 0, False
Else
    ' 尝试 project .venv 中的 pythonw.exe
    venvPythonw = fso.BuildPath(fso.GetParentFolderName(scriptDir), ".venv\Scripts\pythonw.exe")
    If fso.FileExists(venvPythonw) Then
        shell.Run Chr(34) & venvPythonw & Chr(34) & " " & Chr(34) & launcherPath & Chr(34), 0, False
    Else
        ' 最后尝试系统路径中的 pythonw.exe
        shell.Run "pythonw.exe " & Chr(34) & launcherPath & Chr(34), 0, False
    End If
End If
