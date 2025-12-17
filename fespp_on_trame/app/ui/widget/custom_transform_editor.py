from dataclasses import dataclass, field
from paraview import simple
from trame.app import get_server

# 1. Importer la classe de base que vous allez surcharger
from ptc import TransformEditor 

# --- Copie/Définition des dépendances internes ---

@dataclass
class Transform:
    # La définition minimale requise pour la fonction utilitaire
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    ui_visibility: bool = True # Pas strictement nécessaire pour _convert_transform_to_list, mais utile pour la cohérence

def _convert_transform_to_list(transform: Transform) -> list[float]:
    """
    Fonction utilitaire copiée pour convertir la dataclass Transform en une liste [x, y, z]
    comme attendu par ParaView.
    """
    return [transform.x, transform.y, transform.z] if transform else []

# --- Surcharge de la Classe TransformEditor ---

class GlobalTransformEditor(TransformEditor):
    
    # Nous incluons le code de apply_global_scale que nous avions défini.

    def apply_changes(self):
        """
        Surcharge la méthode apply_changes pour appliquer d'abord l'échelle globalement,
        puis appeler la logique originale du parent (qui gère les autres transformations et le Render).
        """
        
        # 1. Logique d'application globale de l'échelle
        # Nous pouvons maintenant appeler _convert_transform_to_list car elle est définie ici.
        self.apply_global_scale(
            _convert_transform_to_list(self.typed_state.data.scale)
        )
        
        # 2. Appel de la méthode originale (pour appliquer translation/origin/orientation
        # à la source active, et appeler ResetCamera/view_update)
        super().apply_changes()

    def apply_global_scale(self, scale):
        """Applique la nouvelle échelle (scale) à TOUTES les sources visibles."""
        view = simple.GetActiveViewOrCreate("RenderView")
        if view is None:
            return

        for source_id, source in simple.GetSources().items():
            display_properties = simple.GetDisplayProperties(source, view=view)

            if display_properties and display_properties.Visibility == 1:
                try:
                    # 'scale' est déjà la liste [x, y, z]
                    display_properties.Scale = scale
                    display_properties.DataAxesGrid.Scale = scale
                    display_properties.PolarAxes.Scale = scale
                except AttributeError:
                    continue
