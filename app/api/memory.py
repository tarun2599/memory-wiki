"""Unix-style REST endpoints for the memory file tree."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas import CatResponse, GrepResponse, LsResponse
from app.services.memory_store import MemoryStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/memory", tags=["memory"])


def _get_store() -> MemoryStore:
    return MemoryStore()


@router.get("/ls", response_model=LsResponse)
async def list_directory(
    path: str = Query("/", description="Directory path to list (unix-style, e.g. /entities/people)"),
) -> LsResponse:
    """
    List contents of a directory in the memory file tree.
    Equivalent to `ls` on a unix filesystem.
    """
    normalized = path.strip("/")
    try:
        return _get_store().ls(normalized)
    except Exception as exc:
        logger.exception("ls failed for path %s", path)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/cat", response_model=CatResponse)
async def read_file(
    path: str = Query(..., description="File path to read (e.g. /entities/people/john-smith.md)"),
) -> CatResponse:
    """
    Read the contents of a memory file.
    Equivalent to `cat` on a unix filesystem.
    """
    if not path or path.strip("/") == "":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path is required. Cannot cat a directory.",
        )
    try:
        return _get_store().cat(path)
    except IsADirectoryError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{path}' is a directory. Use /memory/ls instead.",
        )
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File not found: {path}")
    except Exception as exc:
        logger.exception("cat failed for path %s", path)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/grep", response_model=GrepResponse)
async def search_memories(
    pattern: str = Query(..., description="Regex pattern to search for"),
    path: str = Query("/", description="Directory to search within (recursive)"),
    ignore_case: bool = Query(False, description="Case-insensitive search"),
    context: int = Query(0, ge=0, le=5, description="Lines of context before/after each match"),
    max_results: int = Query(100, ge=1, le=1000, description="Maximum number of matches to return"),
) -> GrepResponse:
    """
    Search memory files for a regex pattern.
    Equivalent to `grep -r` on a unix filesystem.
    """
    try:
        return _get_store().grep(
            pattern=pattern,
            path=path,
            ignore_case=ignore_case,
            context=context,
            max_results=max_results,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("grep failed for pattern %s", pattern)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/tree")
async def memory_tree(
    path: str = Query("/", description="Root path for tree view"),
    depth: int = Query(2, ge=1, le=5, description="Maximum depth to traverse"),
) -> dict:
    """Bonus endpoint: return a nested tree structure for visualization."""

    def build_tree(store: MemoryStore, current_path: str, current_depth: int) -> dict:
        listing = store.ls(current_path)
        node: dict = {"path": "/" + current_path if current_path else "/", "children": []}
        for entry in listing.entries:
            child: dict = {"name": entry.name, "type": entry.type, "path": "/" + entry.path}
            if entry.type == "directory" and current_depth < depth:
                child["children"] = build_tree(store, entry.path, current_depth + 1)["children"]
            node["children"].append(child)
        return node

    store = _get_store()
    return build_tree(store, path.strip("/"), 1)
