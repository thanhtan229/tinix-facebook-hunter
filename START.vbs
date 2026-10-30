' ========================================================
'   TINIX - FACEBOOK HUNTER
'   Silent Background Launcher (START.vbs)
'   Khoi dong he thong chay ngam - Hoan toan khong hien CMD
' ========================================================
Option Explicit

Dim WshShell, FSO, currentDir, batPath, exitCode, interactive

interactive = (WScript.Arguments.Count = 0)

Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

' Lay duong dan thu muc goc chua script nay
currentDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = currentDir

batPath = currentDir & "\START.bat"

If FSO.FileExists(batPath) Then
    ' Chay START.bat o che do an hoan toan (0 = vbHide)
    ' Truyen tham so "silent" de START.bat khong pause khi co loi
    ' Cho START.bat hoan thanh (True) de kiem tra ma trang thai
    exitCode = WshShell.Run("cmd.exe /c """ & batPath & """ silent", 0, True)
    
    If exitCode <> 0 Then
        Notify "Khoi dong Tinix-Facebook-Hunter that bai (Ma loi: " & exitCode & ")!" & vbCrLf & vbCrLf & _
               "Vui long kiem tra file log tai:" & vbCrLf & _
               currentDir & "\logs\server_startup.log", vbCritical, "Tinix - Facebook Hunter", True
    End If
Else
    Notify "Khong tim thay tap tin START.bat tai:" & vbCrLf & currentDir, vbCritical, "Tinix - Facebook Hunter", True
End If

Set WshShell = Nothing
Set FSO = Nothing

' Dialogs only for double-click use. Scripted calls pass "silent" and never block on a MsgBox.
Sub Notify(message, icon, title, failed)
    If interactive Then
        MsgBox message, icon, title
    ElseIf failed Then
        WScript.Quit 1
    End If
End Sub
