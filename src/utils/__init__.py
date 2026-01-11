import re
from urllib.parse import urlparse


def sizeof_fmt(num: int, suffix="B"):
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, "Yi", suffix)


def timeof_fmt(seconds: int | float):
    periods = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
    result = ""
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f"{int(period_value)}{period_name}"
    return result


def is_youtube(url: str) -> bool:
    try:
        if not url or not isinstance(url, str):
            return False

        parsed = urlparse(url)
        return parsed.netloc.lower() in {'youtube.com', 'www.youtube.com', 'youtu.be', 'music.youtube.com'}

    except Exception:
        return False


def extract_filename(response):
    try:
        content_disposition = response.headers.get("content-disposition")
        if content_disposition:
            filename = re.findall("filename=(.+)", content_disposition)[0]
            return filename
    except (TypeError, IndexError):
        pass  # Handle potential exceptions during extraction

    # Fallback if Content-Disposition header is missing
    filename = response.url.rsplit("/")[-1]
    if not filename:
        from urllib.parse import quote_plus
        filename = quote_plus(response.url)
    return filename


def extract_url_and_name(message_text):
    # Regular expression to match the URL
    url_pattern = r"(https?://[^\s]+)"
    # Regular expression to match the new name after '-n'
    name_pattern = r"-n\s+(.+)$"

    # Find the URL in the message_text
    url_match = re.search(url_pattern, message_text)
    url = url_match.group(0) if url_match else None

    # Find the new name in the message_text
    name_match = re.search(name_pattern, message_text)
    new_name = name_match.group(1) if name_match else None

    return url, new_name

