"""
FakeDataAssembly: a minimal pure-Python stand-in for vtkDataAssembly.

It replaces the real VTK object in the unit tests and supports the
operations engine/tree.py uses:
  - AddNode / RemoveNode
  - GetChild / GetParent / GetNumberOfChildren / GetChildNodes
  - GetAttributeOrDefault / SetAttribute / GetAttribute
  - GetNodePath / GetNodeName / FindFirstNodeWithName
  - GetFirstNodeByPath
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Node:
    node_id: int
    name: str          # internal name (starts with "_")
    parent_id: int
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)   # list of node_ids


class FakeDataAssembly:
    """A node hierarchy the tests build and inspect directly."""

    def __init__(self, root_name: str = "data"):
        self._nodes: dict[int, _Node] = {}
        self._next_id: int = 0
        # the root node, id 0
        root = _Node(node_id=0, name=root_name, parent_id=-1)
        self._nodes[0] = root
        self._next_id = 1

    # ------------------------------------------------------------------ build

    def AddNode(self, name: str, parent_id: int = 0) -> int:
        node_id = self._next_id
        self._next_id += 1
        node = _Node(node_id=node_id, name=name, parent_id=parent_id)
        self._nodes[node_id] = node
        self._nodes[parent_id].children.append(node_id)
        return node_id

    def RemoveNode(self, node_id: int) -> None:
        if node_id not in self._nodes:
            return
        node = self._nodes[node_id]
        # detach from the parent's children
        parent = self._nodes.get(node.parent_id)
        if parent and node_id in parent.children:
            parent.children.remove(node_id)
        # remove the children recursively
        for child_id in list(node.children):
            self.RemoveNode(child_id)
        del self._nodes[node_id]

    # ---------------------------------------------------------------- attrs

    def SetAttribute(self, node_id: int, key: str, value: Any) -> None:
        self._nodes[node_id].attrs[key] = value

    def GetAttribute(self, node_id: int, key: str, default: Any = None) -> Any:
        return self._nodes[node_id].attrs.get(key, default)

    def GetAttributeOrDefault(self, node_id: int, key: str, default: Any) -> Any:
        return self._nodes[node_id].attrs.get(key, default)

    # ----------------------------------------------------------- navigation

    def GetParent(self, node_id: int) -> int:
        return self._nodes[node_id].parent_id if node_id in self._nodes else -1

    def GetChild(self, parent_id: int, index: int) -> int:
        children = self._nodes[parent_id].children
        return children[index] if index < len(children) else -1

    def GetChildNodes(self, node_id: int) -> list[int]:
        return list(self._nodes[node_id].children) if node_id in self._nodes else []

    def GetNumberOfChildren(self, node_id: int) -> int:
        return len(self._nodes[node_id].children) if node_id in self._nodes else 0

    def GetNodeName(self, node_id: int) -> str:
        return self._nodes[node_id].name if node_id in self._nodes else ""

    def GetNodePath(self, node_id: int) -> str:
        """Return the node's path from the root, e.g. "/data/_grid/_prop"."""
        parts = []
        current = node_id
        while current > 0:
            parts.append(self._nodes[current].name)
            current = self._nodes[current].parent_id
        parts.append(self._nodes[0].name)  # root
        return "/" + "/".join(reversed(parts))

    def FindFirstNodeWithName(self, name: str) -> int:
        for node_id, node in self._nodes.items():
            if node.name == name:
                return node_id
        return -1

    def GetFirstNodeByPath(self, path: str) -> int:
        """Return the id of the node whose GetNodePath() equals `path`, or -1."""
        for node_id in self._nodes:
            if self.GetNodePath(node_id) == path:
                return node_id
        return -1

    # ---------------------------------------------------------------- helpers

    def add_node_with_attrs(self, name: str, parent_id: int, **attrs) -> int:
        """Add a node and set each keyword as one of its attributes."""
        node_id = self.AddNode(name, parent_id)
        for k, v in attrs.items():
            self.SetAttribute(node_id, k, v)
        return node_id
