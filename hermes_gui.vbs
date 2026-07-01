Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

Dim envVars
envVars = "set TCL_LIBRARY=" & WshShell.CurrentDirectory & "\python_embedded\tcl\tcl8.6 && " & _
          "set TK_LIBRARY=" & WshShell.CurrentDirectory & "\python_embedded\tcl\tk8.6 && " & _
          "set PYTHONIOENCODING=utf-8 && " & _
          "set PATH=" & WshShell.CurrentDirectory & "\python_embedded;" & WshShell.CurrentDirectory & "\python_embedded\Scripts;%PATH%"

WshShell.Run "cmd /c " & envVars & " && """ & WshShell.CurrentDirectory & "\python_embedded\python.exe"" """ & WshShell.CurrentDirectory & "\gui\app.py""", 0, False
