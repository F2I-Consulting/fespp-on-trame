import requests
import re
from urllib.parse import urlparse
import contextlib

# return filepath
def download_file_from_url(url: str, tmp_dir)-> str:
    with requests.get(url, stream=True, timeout=20) as r:
        r.raise_for_status()

        # Try to get filename from Content-Disposition header
        file_name = None
        if 'Content-Disposition' in r.headers:
            content_disposition = r.headers['Content-Disposition']
            # Regular expression to find filename* or filename
            fname_match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^";\n]+)["\']?', content_disposition)
            if fname_match:
                file_name = fname_match.group(1).strip()
                # Decode URL-encoded characters if present
                file_name = requests.utils.unquote(file_name)

        # Fallback to URL's last segment if Content-Disposition filename not found
        if not file_name:
            file_name = urlparse(url).path.split("/")[-1]
            if not file_name: # Handle cases where URL ends with /
                file_name = "downloaded_file" # Or generate a unique name
        
        with open(tmp_dir+'/'+file_name, "wb+") as file_handle:
            for chunk in r.iter_content(chunk_size=8192):
                file_handle.write(chunk)
            file_handle.flush()
            return file_handle.name        

    return ""
