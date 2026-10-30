' ========================================================
'   TINIX - FACEBOOK HUNTER
'   Silent Background Stopper (STOP.vbs)
'   Dung tien trinh chay ngam - Hoan toan khong hien CMD
' ========================================================
Option Explicit

Dim WshShell, FSO, currentDir, stopBat, exitCode, interactive

interactive = (WScript.Arguments.Count = 0)

Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

' Lay duong dan thu muc goc chua script nay
currentDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = currentDir

stopBat = currentDir & "\STOP.bat"

If FSO.FileExists(stopBat) Then
    exitCode = WshShell.Run("cmd.exe /c """ & stopBat & """ silent", 0, True)
    If exitCode = 0 Then
        Notify "Da dung may chu Tinix-Facebook-Hunter thanh cong!", vbInformation, "Tinix - Facebook Hunter", False
    Else
        Notify "Khong the dung server hoac cong 7866 dang duoc ung dung khac su dung.", vbExclamation, "Tinix - Facebook Hunter", True
    End If
Else
    Notify "Khong tim thay tap tin STOP.bat tai:" & vbCrLf & currentDir, vbExclamation, "Tinix - Facebook Hunter", True
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
