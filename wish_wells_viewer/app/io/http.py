import requests


def download_file_from_url(url: str, fileHandle):
    with requests.get(url, stream=True, timeout=20) as r:
        r.raise_for_status()

        for chunk in r.iter_content(chunk_size=8192):
            fileHandle.write(chunk)

    fileHandle.flush()
