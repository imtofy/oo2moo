"""Verhindert, dass mehrere Instanzen der .exe gleichzeitig laufen - über
einen benannten Windows-Mutex statt einer Lock-Datei, da der Mutex beim
Prozessende automatisch freigegeben wird (auch bei einem Absturz). Eine
Lock-Datei müsste diesen Fall selbst erkennen und aufräumen.
"""
import ctypes

# use_last_error=True ist Pflicht: ctypes' eigene Marshalling-Aufrufe
# zwischen CreateMutexW und einem späteren, separaten GetLastError()-Aufruf
# können den Last-Error-Wert überschreiben, bevor er ausgelesen wird -
# damit würde "schon offen" auch fälschlich gemeldet, wenn gar keine
# zweite Instanz läuft. Mit use_last_error=True sichert ctypes den Wert
# zuverlässig direkt nach dem Aufruf, abrufbar über get_last_error().
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_MUTEX_NAME = "Global\\OlatToMoodleConverter_SingleInstance"
_ERROR_ALREADY_EXISTS = 183

# Muss für die Laufzeit des Prozesses gehalten werden - würde der Handle
# hier nicht referenziert bleiben, könnte er vorzeitig freigegeben werden
# und der Mutex-Schutz liefe ins Leere.
_handle = None


def already_running() -> bool:
    """True, wenn bereits eine andere Instanz denselben Mutex hält."""
    global _handle
    _handle = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    return ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
