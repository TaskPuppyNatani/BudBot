Option Explicit

Dim shell, fso, root, appPath, candidate, python, command, result
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
appPath = fso.BuildPath(root, "control_center.py")

candidate = FindExecutable(shell, "where.exe pyw.exe")
If candidate <> "" Then
    python = FindExecutable(shell, "where.exe py.exe")
    If python <> "" And CanImportTk(shell, Quote(python) & " -3 -c " & Quote("import tkinter")) Then
        command = Quote(candidate) & " -3 " & Quote(appPath)
    Else
        candidate = ""
    End If
End If

If candidate = "" Then
    candidate = FindExecutable(shell, "where.exe pythonw.exe")
    python = FindExecutable(shell, "where.exe python.exe")
    If candidate <> "" And python <> "" Then
        If CanImportTk(shell, Quote(python) & " -c " & Quote("import tkinter")) Then
            command = Quote(candidate) & " " & Quote(appPath)
        Else
            candidate = ""
        End If
    End If
End If

If candidate = "" Then
    MsgBox "Install Python 3 for Windows with Tcl/Tk support, then open Docker Desktop and try again.", vbExclamation, "BudBot Control Center"
    WScript.Quit 1
End If

On Error Resume Next
result = shell.Run(command, 0, False)
If Err.Number <> 0 Then
    MsgBox "Could not start the BudBot Control Center. Install Python 3 for Windows with Tcl/Tk support.", vbCritical, "BudBot Control Center"
    WScript.Quit 1
End If
On Error GoTo 0

Function CanImportTk(shell, command)
    Dim exitCode
    CanImportTk = False
    On Error Resume Next
    exitCode = shell.Run(command, 0, True)
    If Err.Number = 0 Then CanImportTk = (exitCode = 0)
    Err.Clear
    On Error GoTo 0
End Function

Function FindExecutable(shell, command)
    Dim process, text, lines
    FindExecutable = ""
    On Error Resume Next
    Set process = shell.Exec(command)
    If Err.Number = 0 Then
        Do While process.Status = 0
            WScript.Sleep 50
        Loop
        text = Trim(process.StdOut.ReadAll())
        If text <> "" Then
            lines = Split(text, vbCrLf)
            FindExecutable = Trim(lines(0))
        End If
    End If
    Err.Clear
    On Error GoTo 0
End Function

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
