from trame.app import get_server

from fespp_on_trame.app.core.reservoir.fespp_ijkgrid import IjkGrid
from fespp_on_trame.app.core.well.fespp_wellhead import Wellhead
from fespp_on_trame.app.core.common.timeseries import TimeSeries
from fespp_on_trame.app.core.fespp_tree import Tree

server = get_server()
state = server.state

class Selector:
    def __init__(self, ijkgrid: IjkGrid, tree: Tree):
        
        self._ijkgrid = ijkgrid
        self._tree = tree

        self._selection_path_reservoir = []
        self._selection_path_surface = []
        self._selection_path_well = []
        
        self._wellheads = []
        self._timeseries = None

        state.setdefault("first_selection", True)

    def optimize_tree_selection(self, selected_items, tree_data):
        """
        Optimise la sélection récursivement : remonte dans l'arbre tant que 
        toutes les feuilles d'un parent sont sélectionnées
        """
        if not selected_items or not tree_data:
            return selected_items
    
        # Construire le mapping de tous les descendants pour chaque nœud
        node_descendants = {}  # nœud -> tous ses descendants (enfants, petits-enfants, etc.)
        node_leaves = {}       # nœud -> toutes ses feuilles finales

        def build_descendants(items):
            for item in items:
                item_id = item.get('id')
                descendants = set()
                leaves = set()

                if 'children' in item and item['children']:
                    # Récurser sur les enfants
                    build_descendants(item['children'])

                    for child in item['children']:
                        child_id = child.get('id')
                        descendants.add(child_id)
                        # Ajouter tous les descendants du child
                        if child_id in node_descendants:
                            descendants.update(node_descendants[child_id])
                        # Ajouter toutes les feuilles du child
                        if child_id in node_leaves:
                            leaves.update(node_leaves[child_id])
                        else:
                            leaves.add(child_id)  # Le child est lui-même une feuille
                else:
                    # C'est une feuille
                    leaves.add(item_id)

                node_descendants[item_id] = descendants
                node_leaves[item_id] = leaves

        build_descendants(tree_data)

        selected_set = set(selected_items)

        # Trouver le nœud le plus haut qui peut représenter sa sélection complète
        optimized_nodes = []
        processed_descendants = set()

        # Trier les nœuds par profondeur (les plus profonds d'abord -> les plus hauts à la fin)
        # On va traiter du plus haut vers le plus bas
        all_nodes = [(node_id, len(node_descendants[node_id])) for node_id in node_descendants.keys()]
        all_nodes.sort(key=lambda x: x[1])  # Trier par nombre de descendants (les parents en dernier)

        for node_id, _ in reversed(all_nodes):  # Traiter du plus haut vers le plus bas
            # Vérifier si ce nœud n'a pas déjà été traité comme descendant d'un autre
            if node_id in processed_descendants:
                continue
                
            # Vérifier si toutes les feuilles de ce nœud sont sélectionnées
            node_leaves_set = node_leaves.get(node_id, {node_id})
            if node_leaves_set.issubset(selected_set):
                # Toutes les feuilles sont sélectionnées, on peut prendre ce nœud
                optimized_nodes.append(node_id)
                # Marquer tous ses descendants comme traités
                processed_descendants.update(node_descendants.get(node_id, set()))
                processed_descendants.add(node_id)

        # Ajouter les feuilles sélectionnées qui n'ont pas été couvertes par un parent
        for leaf in selected_items:
            if leaf not in processed_descendants:
                optimized_nodes.append(leaf)

        return optimized_nodes
    
    def select_node_surface(self):
        if self._timeseries is not None:
            self._timeseries.delete()
        # Optimiser la sélection avant de l'utiliser
        optimized_selection = self.optimize_tree_selection(
            state.ui_select_node_surface, 
            state.ui_subtree_surface
        )

        # Utiliser la sélection optimisée si fournie, sinon la sélection brute
        list_selected = optimized_selection
        path_selectors = []

        # switch node_id to path
        for node_id in list_selected:
            if self._tree.find_type(node_id) == "TimeSeries":
                print("TimeSeries selected")
                self._timeseries = TimeSeries(self._tree, node_id)
                
            path = self._tree.find_path(node_id)
            if path:
                path_selectors.append(path)

        self._selection_path_surface = path_selectors.copy()
        state.fespp_data_selectors = self._selection_path_reservoir + self._selection_path_surface + self._selection_path_well
        if state.first_selection == True:
            state.first_selection = False
        state.view_update = True

    def select_node_well(self):
        if self._timeseries is not None:
            self._timeseries.delete()
        list_selected = state.ui_select_node_well.copy()
        for wellhead in self._wellheads:
            wellhead.delete()
        self._wellheads = []

        # switch node_id to path
        for node_id in list_selected:
            if self._tree.find_type(node_id) == "Trajectory":
                self._wellheads.append(Wellhead(self._tree, node_id))
                
            elif self._tree.find_type(node_id) == "TimeSeries":
                self._timeseries = TimeSeries(self._tree, node_id)

        # Optimiser la sélection avant de l'utiliser
        optimized_selection = self.optimize_tree_selection(
            state.ui_select_node_well, 
            state.ui_subtree_well
        )

        # Utiliser la sélection optimisée si fournie, sinon la sélection brute
        list_selected = optimized_selection
        path_selectors = []

        # switch node_id to path
        for node_id in list_selected:
            path = self._tree.find_path(node_id)
            if path:
                path_selectors.append(path)

        self._selection_path_well = path_selectors.copy()
        state.fespp_data_selectors = self._selection_path_reservoir + self._selection_path_surface + self._selection_path_well
        if state.first_selection == True:
            state.first_selection = False
        state.view_update = True
        
    def select_node_reservoir(self):
        if self._timeseries is not None:
            self._timeseries.delete()
        list_selected = state.ui_select_node_reservoir.copy()
        for node_id in list_selected:
            if self._tree.find_type(node_id) == "TimeSeries":
                self._timeseries = TimeSeries(self._tree, node_id)

        if self._ijkgrid is not None:
            if len(state.ui_select_node_reservoir) < 1:
                self._ijkgrid.set_node_id(None)
                if self._selection_path_reservoir != []:
                    self._selection_path_reservoir = []
                    state.fespp_data_selectors = self._selection_path_surface + self._selection_path_well
            else:
                self._selection_path_reservoir = [self._tree.find_path(state.ui_select_node_reservoir[0])]
                state.fespp_data_selectors = self._selection_path_reservoir + self._selection_path_surface + self._selection_path_well
        if state.first_selection == True:
            state.first_selection = False
        state.view_update = True


