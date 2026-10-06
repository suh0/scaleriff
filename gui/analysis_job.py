"""중단 가능한 분석 프로세스 — 생성 파일은 작업별 폴더에만 기록한다."""
import os
import traceback


def _isolate_process():
    if os.name != "nt":
        os.setsid()
        return
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                    ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                    ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                    ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                               ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        kernel.CloseHandle(job)
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        kernel.CloseHandle(job)
        raise ctypes.WinError(ctypes.get_last_error())
    # 핸들은 자식에게 상속하지 않는다. 이 프로세스가 종료되면 OS가 닫아
    # ffmpeg/Deno 등 같은 Job에 속한 모든 자식도 함께 종료한다.


def run_analysis(connection, build_fn, source, work_dir):
    try:
        _isolate_process()
        from ingest import audio_source
        audio_source._CACHE_DIR = work_dir

        def progress(pct, msg):
            connection.send(("progress", (int(pct), msg)))

        timeline = build_fn(source, progress)
        connection.send(("ready", timeline.to_dict()))
    except Exception as error:
        connection.send(("failed", f"{error}\n\n{traceback.format_exc()}"))
    finally:
        connection.close()
