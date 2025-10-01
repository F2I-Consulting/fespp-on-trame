import requests
import re
import shutil
from urllib.parse import urlparse
from pathlib import Path
import tempfile

def download_file_from_url(url: str, tmp_dir: str) -> str:
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()

        # Récupération du nom de fichier
        file_name = None
        if 'Content-Disposition' in r.headers:
            content_disposition = r.headers['Content-Disposition']
            fname_match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^";\n]+)["\']?', content_disposition)
            if fname_match:
                file_name = fname_match.group(1).strip()
                file_name = requests.utils.unquote(file_name)

        if not file_name:
            file_name = urlparse(url).path.split("/")[-1]
            if not file_name:
                file_name = "downloaded_file"

        # Chemin complet du fichier
        file_path = Path(tmp_dir) / file_name
        
        # Écriture avec copie directe du flux
        with open(file_path, 'wb') as f:
            shutil.copyfileobj(r.raw, f)
        
        return str(file_path)