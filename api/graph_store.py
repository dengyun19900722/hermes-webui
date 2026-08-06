"""GraphStore 接口定义。

所有存储实现（Neo4j / Mock）必须遵循此协议，方法以 dict / list[dict]
进出，不暴露后端特定类型。
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class GraphStore(Protocol):
    """图存储抽象接口。"""

    def health(self) -> dict:
        """健康探测。返回 {"backend": "neo4j"|"mock", "ok": bool, "detail": str, ...}"""
        ...

    def schema(self) -> dict:
        """Schema 概览。返回 {"node_labels": [...], "relationship_types": [...], "stats": {...}}"""
        ...

    def search(self, query: str, label: str | None = None, limit: int = 50) -> dict:
        """按关键字搜索节点。返回 {"results": [...], "query": str, "count": int}"""
        ...

    def list_nodes(self, label: str, limit: int = 200) -> dict:
        """按 label 列出节点。返回 {"results": [...], "count": int}"""
        ...

    def list_all_nodes(self, limit: int = 500) -> dict:
        """一次性列出所有节点（不分 label）。返回 {"results": [...], "count": int}"""
        ...

    def get_node(self, element_id: str) -> dict | None:
        """按 element_id 拿节点。不存在返回 None。"""
        ...

    def get_relationship(self, element_id: str) -> dict | None:
        """按 element_id 拿关系。不存在返回 None。"""
        ...

    def list_relationships(self, element_id: str, direction: str = "both") -> list[dict]:
        """列出节点的所有关系。direction in {"in","out","both"}"""
        ...

    def list_all_relationships(self, limit: int = 500) -> list[dict]:
        """列出所有关系（不分页节点）。用于 Table 视图。"""
        ...

    def topology(self, element_id: str, depth: int = 1, direction: str = "both") -> dict:
        """返回以节点为中心、depth 跳内的子图。

        depth: 1..5 表示固定层数；0 表示"全部"（BFS 直到 frontier 空 或 达 cap）。
        direction: "in" 仅入向（上游/被依赖），"out" 仅出向（下游/依赖），
                   "both" 双向。
        返回 {"nodes": [...], "relationships": [...]}。
        """
        ...

    def create_node(self, labels: list[str], properties: dict) -> dict:
        """创建节点，返回创建的节点 dict（含新 id）。"""
        ...

    def create_relationship(self, type_: str, start_id: str, end_id: str,
                            properties: dict | None = None) -> dict:
        """创建关系，返回创建的关系 dict（含新 id）。"""
        ...

    def update_node(self, element_id: str, properties: dict) -> dict:
        """更新节点 properties（merge / replace）。返回更新后的节点。"""
        ...

    def delete_node(self, element_id: str) -> dict:
        """删除节点（级联删除关系）。返回 {"deleted": True}。"""
        ...

    def delete_relationship(self, element_id: str) -> dict:
        """删除关系。返回 {"deleted": True}。"""
        ...

    def seed_sample(self) -> dict:
        """加载示例图谱。返回 {"nodes_added": int, "relationships_added": int}。"""
        ...
