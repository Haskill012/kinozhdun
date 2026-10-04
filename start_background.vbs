Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\ВАЙБКОДИНГ\ПРОЕКТЫ\КиноЖдун"
WshShell.Run "D:\ВАЙБКОДИНГ\ПРОЕКТЫ\КиноЖдун\.venv\Scripts\pythonw.exe -m bot", 0, False
