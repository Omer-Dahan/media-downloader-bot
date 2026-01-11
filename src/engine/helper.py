import functools
import threading
import time


def debounce(wait_seconds):
    """
    Thread-safe debounce decorator for functions that take a message with chat.id and msg.id attributes.
    The function will only be called if it hasn't been called with the same chat.id and msg.id in the last 'wait_seconds'.
    """

    def decorator(func):
        last_called = {}
        lock = threading.Lock()

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal last_called
            now = time.time()

            # Assuming the first argument is the message object with chat.id and msg.id
            bot_msg = args[0]._bot_msg
            key = (bot_msg.chat.id, bot_msg.id)

            with lock:
                if key not in last_called or now - last_called[key] >= wait_seconds:
                    last_called[key] = now
                    return func(*args, **kwargs)

        return wrapper

    return decorator


def sizeof_fmt(num: int, suffix="B"):
    """Format file size in human-readable format."""
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, "Yi", suffix)
