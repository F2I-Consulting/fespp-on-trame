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
    print("1->", tree)
    for node in tree:
        if node.get("id") == node_id:
            print("2->", node)
            return node.get("type")
        elif node.get("children"):
            print("3->", node["children"])
            type = node_id_to_type(node["children"], node_id)
            if type:
                return type
    return None
