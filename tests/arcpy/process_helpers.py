import subprocess


def stop_process(process: subprocess.Popen, timeout: float = 10) -> None:
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)
