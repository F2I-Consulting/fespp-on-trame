import os
from pathlib import Path
from tempfile import mkdtemp

# Chemin où enregistrer les fichiers (à adapter)
temp_dir = mkdtemp()

def save_uploaded_files(files):
    """Enregistre les fichiers uploadés sur le serveur"""
    # Créer le dossier s'il n'existe pas
    Path(temp_dir).mkdir(parents=True, exist_ok=True)
    epc_paths = []
    
    for file_info in files:  # file_info est un dictionnaire
        try:
            file_name = file_info["name"]
            
            # Chemin complet du fichier de destination
            file_path = os.path.join(temp_dir, file_name)
            
            if file_name.lower().endswith('.epc'):
                epc_paths.append(file_path)
                
            # Écrire le contenu binaire dans le fichier
            with open(file_path, "wb") as f:
                f.write(file_info["content"])  # Accès via la clé "content"
            
            print(f"Fichier {file_info['name']} enregistré avec succès")
        except Exception as e:
            print(f"Erreur lors de l'enregistrement de {file_info.get('name')}: {str(e)}")
    
    return epc_paths
