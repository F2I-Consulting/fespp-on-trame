# -----------------------------------------------------------------------------
# find parent node 
# -----------------------------------------------------------------------------
def find_parent_id(tree, node_id) -> None:
    for item in tree:
        if item.get("id") == node_id:
            return item["parent_id"]
        elif item.get("children"):
            return find_parent_id(item["children"], node_id)
    return None

# -----------------------------------------------------------------------------
# find node by id
# -----------------------------------------------------------------------------
def find_item_node_id(tree, node_id) -> None:
    for item in tree:
        if item.get("id") == node_id:
            return item
    return None

# -----------------------------------------------------------------------------
# find node id -> path
# -----------------------------------------------------------------------------
def node_id_to_path(tree, node_id) -> str:
    for node in tree:
        if node.get("id") == node_id:
            return node.get("path")
        elif node.get("children"):
            path = node_id_to_path(node["children"], node_id)
            if path:
                return path
    return None

# -----------------------------------------------------------------------------
# find node id -> title
# -----------------------------------------------------------------------------
def node_id_to_title(tree, node_id) -> str:
    for node in tree:
        if node.get("id") == node_id:
            return node.get("title")
        elif node.get("children"):
            title = node_id_to_title(node["children"], node_id)
            if title:
                return title
    return None

# -----------------------------------------------------------------------------
# find node id -> type
# -----------------------------------------------------------------------------
def node_id_to_type(tree, node_id) -> str:
    for node in tree:
        if node.get("id") == node_id:
            return node.get("type")
        elif node.get("children"):
            type = node_id_to_type(node["children"], node_id)
            if type:
                return type
    return None

# -----------------------------------------------------------------------------
# find ijkgrid parent node id
# -----------------------------------------------------------------------------
def find_ijkgrid(tree, node_id) -> None:
    if node_id == 0:
        return
    
    node_type = node_id_to_type(tree, node_id)
    if node_type:
        if node_type in [ 'IjkGrid' ]:
            return node_id
        else:
            parent_id = find_parent_id(tree, node_id)
            if parent_id:
                return find_ijkgrid(tree, parent_id)
    return