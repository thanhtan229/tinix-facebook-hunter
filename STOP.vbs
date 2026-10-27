' ========================================================
'   TINIX - FACEBOOK HUNTER
'   Silent Background Stopper (STOP.vbs)
'   Dung tien trinh chay ngam - Hoan toan khong hien CMD
' ========================================================
Option Explicit

Dim WshShell, FSO, currentDir, stopBat, exitCode

Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

' Lay duong dan thu muc goc chua script nay
currentDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = currentDir

stopBat = currentDir & "\STOP.bat"

If FSO.FileExists(stopBat) Then
    exitCode = WshShell.Run("cmd.exe /c """ & stopBat & """ silent", 0, True)
    If exitCode = 0 Then
        MsgBox "Da dung may chu Tinix-Facebook-Hunter thanh cong!", vbInformation, "Tinix - Facebook Hunter"
    Else
        MsgBox "Khong the dung server hoac cong 7866 dang duoc ung dung khac su dung.", vbExclamation, "Tinix - Facebook Hunter"
    End If
Else
    MsgBox "Khong tim thay tap tin STOP.bat tai:" & vbCrLf & currentDir, vbExclamation, "Tinix - Facebook Hunter"
End If

Set WshShell = Nothing
Set FSO = Nothing
