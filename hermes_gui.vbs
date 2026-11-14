Set WshShell = CreateObject("WScript.Shell")
Set FileSystem = CreateObject("Scripting.FileSystemObject")
AppDir = FileSystem.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = AppDir
' No window: the launch scripts must never wait for a key press, and open
' START.bat (visible) when setup is needed or a problem must be shown.
WshShell.Environment("PROCESS")("HERMES_PORTABLE_HIDDEN") = "1"
WshShell.Run """" & AppDir & "\hermes_gui.bat""", 0, False
