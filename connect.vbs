Set objFSO = CreateObject("Scripting.FileSystemObject")

Dim shouldRun
Dim username
Dim wshShell, command, output, sessionId
Set wshShell = CreateObject("WScript.Shell")
Dim iniFilePath
iniFilePath = "connect.env"

shouldRun = False
username = ReadIniValue("username")
connectcmd = ReadIniValue("connectcmd")

'Do
If objFSO.FileExists("timeout.tmp") or not objFSO.FileExists("ping.tmp") Then
    shouldRun = True
ElseIf objFSO.FileExists("ping.tmp") Then
    Set objFile = objFSO.OpenTextFile("ping.tmp", 1)
    pingTime = objFile.ReadLine
    objFile.Close

    currentTime = Time()

    Dim h, m, s
    h = Hour(currentTime)
    m = Minute(currentTime)
    s = Second(currentTime)

    Dim pingH, pingM, pingS
    pingH = CInt(Split(pingTime, ":")(0))
    pingM = CInt(Split(pingTime, ":")(1))
    pingS = CInt(Split(pingTime, ":")(2))

    timeDiff = (h * 3600 + m * 60 + s) - (pingH * 3600 + pingM * 60 + pingS)

    If timeDiff >= 600 Then
        shouldRun = True
    End If
End If

If shouldRun Then
    Set objShell = CreateObject("WScript.Shell")

    Set objWMI = GetObject("winmgmts:\\.\root\cimv2")
    Set colProcesses = objWMI.ExecQuery("Select * from Win32_Process Where Name = 'mstsc.exe'")

    For Each objProcess In colProcesses
        objProcess.Terminate
    Next

    WScript.Sleep 1000
    logoff(username)

    objShell.Run connectcmd
    'Do While Not objShell.AppActivate("SecureCRT and SecureFX Bundle")
    '    WScript.Sleep 500
    'Loop

    'WScript.Sleep 1000

    'objShell.SendKeys "{TAB}"
    'WScript.Sleep 200

    'objShell.SendKeys "{TAB}"
    'WScript.Sleep 200

    'objShell.SendKeys "{ENTER}"
End If
'    WScript.Sleep 60000
'Loop

Function logoff(key)
    command = "query user " & key
    output = wshShell.Exec(command).StdOut.ReadAll()

    If InStr(output, key) > 0 Then

        Dim lines, line
        lines = Split(output, vbCrLf)
        For Each line In lines
            If InStr(line, key) > 0 Then

                Set objRegEx = CreateObject("VBScript.RegExp")
                With objRegEx
                    .Global = True
                    .MultiLine = True
                    .Pattern = "\s+"
                    line = objRegEx.Replace(line, "|")
                End With
                Set objRegEx = Nothing
                sessionId = Trim(Split(line, "|")(2))
            End If
        Next

        If sessionId <> "" Then
            command = "logoff " & sessionId
            wshShell.Exec(command)
        End If
    End If
End Function

Function ReadIniValue(key)
    Dim fso, file, line, keyValue
    Set fso = CreateObject("Scripting.FileSystemObject")

    ' Проверка существования файла
    If Not fso.FileExists(iniFilePath) Then
        WScript.Echo "INI файл не найден: " & iniFilePath
        WScript.Quit
    End If

    ' Открыть файл для чтения
    Set file = fso.OpenTextFile(iniFilePath, 1)

    ' Чтение файла построчно
    Do Until file.AtEndOfStream
        line = Trim(file.ReadLine)

        ' Если строка пустая или начинается с комментария, пропускаем её
        If line = "" Or Left(line, 1) = ";" Then
            Continue
        End If

        ' Разделить строку на ключ и значение
        keyValue = Split(line, "=")
        If UBound(keyValue) = 1 Then
            If Trim(keyValue(0)) = key Then
                ReadIniValue = Trim(keyValue(1)) ' Возвращаем значение
                file.Close
                Exit Function
            End If
        End If
    Loop

    file.Close
    ReadIniValue = "" ' Возвращаем пустое значение, если не нашли ключ
End Function