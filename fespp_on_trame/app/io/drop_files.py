import os
import gc
from pathlib import Path
from tempfile import mkdtemp
import base64

from trame.app import get_server

server = get_server()
state = server.state

# Configuration
temp_dir = mkdtemp()
CHUNK_SIZE = 32 * 1024 * 1024  # 32MB chunks

def setup_for_large_files():
    os.environ['PYTHONUNBUFFERED'] = '1'
    
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        new_soft = 8 * 1024**3  # 8GB
        if hard == resource.RLIM_INFINITY or hard > new_soft:
            resource.setrlimit(resource.RLIMIT_AS, (new_soft, hard))
    except Exception as e:
        print(f"ERROR change mem limit: {e}")
    
    gc.set_threshold(50, 5, 5)
    gc.enable()

def save_uploaded_files(files):
    Path(temp_dir).mkdir(parents=True, exist_ok=True)
    epc_paths = []
    
    for i, file_info in enumerate(files):
        file_path = None
        try:
            file_name = file_info.get("name", f"file_{i}")
            print(f"start: {file_name}")
            
            content = file_info.get("content")
            if not content:
                print(f"File {file_name} no content")
                continue
            
            file_path = os.path.join(temp_dir, file_name)
            
            # Vérifier si c'est un gros fichier base64
            if isinstance(content, str) and len(content) > 100 * 1024 * 1024:  # >100MB
                print("large file detected, use flux mode...")
                file_path = save_large_base64_stream(content, file_path)
            else:
                # Méthode standard pour petits fichiers
                with open(file_path, "wb") as f:
                    if isinstance(content, bytes):
                        f.write(content)
                    elif isinstance(content, str):
                        if content.startswith('data:'):
                            # Extraire le base64
                            base64_data = content.split('base64,')[1] if 'base64,' in content else content
                            f.write(base64.b64decode(base64_data))
                        else:
                            f.write(content.encode())
            
            if file_path and os.path.exists(file_path) and file_name.lower().endswith('.epc'):
                epc_paths.append(file_path)
                print(f"✓ {file_name} saved ({os.path.getsize(file_path)/(1024**3):.2f}GB)")
            # Nettoyage agressif
            del content
            gc.collect()
            
        except Exception as e:
            print(f"✗ Error {file_name}: {str(e)}")
            import traceback
            traceback.print_exc()
            # Nettoyer le fichier partiel en cas d'erreur
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            continue
    return epc_paths

def save_large_base64_stream(base64_content, file_path, chunk_size=4 * 1024 * 1024):
    try:
        with open(file_path, "wb") as f:
            total_length = len(base64_content)
            decoded_size_estimate = (total_length * 3) // 4  # Estimation taille décodée
            
            print(f"file size: {decoded_size_estimate/(1024**3):.2f}GB")
            
            # Décoder par petits chunks pour éviter la mémoire
            for i in range(0, total_length, chunk_size):
                end = min(i + chunk_size, total_length)
                chunk = base64_content[i:end]
                
                # S'assurer que la chunk est de longueur multiple de 4 pour base64
                remainder = len(chunk) % 4
                if remainder != 0:
                    chunk += '=' * (4 - remainder)
                
                try:
                    decoded = base64.b64decode(chunk)
                    f.write(decoded)
                except Exception as e:
                    print(f"Error chunk decode {i}-{end}: {e}")
                    continue
                
                # Progress reporting
                if i % (chunk_size * 100) == 0:
                    f.flush()
                    progress = (i / total_length) * 100
                    print(f"Progress: {progress:.1f}%")
            
            f.flush()
            os.fsync(f.fileno())
        
        return file_path
        
    except Exception as e:
        print(f"Error on save_large_base64_stream: {e}")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        return None

# Configuration initiale
setup_for_large_files()