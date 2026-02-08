' start_rin_service.vbs — Launch rin_service.py silently (no console window)
' Used by Windows Task Scheduler to start the Rin Service at logon.
' VBScript avoids pythonw.exe silent-crash issues by using python.exe
' with a hidden window instead.

Dim WshShell, fso, projectRoot
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Resolve project root from this script's location (scripts/ subfolder)
projectRoot = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))

' Set working directory
WshShell.CurrentDirectory = projectRoot

' Find python.exe
Dim pythonExe
pythonExe = "python.exe"

' Launch hidden (0 = hidden window, False = don't wait)
WshShell.Run """" & pythonExe & """ """ & projectRoot & "\rin_service.py""", 0, False
