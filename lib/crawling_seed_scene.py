#!/usr/bin/env python3
"""Utilities for extracting a single Workbench scene from a template file."""

from __future__ import annotations

import xml.etree.ElementTree as ET


XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>\n'
LEGACY_PALETTE_BASENAMES = frozenset({"untitled_7082.palette"})


def _legacy_palette_elements(scene: ET.Element) -> list[tuple[ET.Element, ET.Element, str]]:
    matches: list[tuple[ET.Element, ET.Element, str]] = []
    for data_files in scene.iter("ObjectArray"):
        if data_files.get("Name") != "allCaretDataFiles_V2":
            continue
        for element in data_files.findall("./Element"):
            for data_file in element.findall("./Object"):
                if data_file.get("Class") != "CaretDataFile":
                    continue
                for path_node in data_file.iter("Object"):
                    path_value = (path_node.text or "").strip()
                    palette_name = path_value.replace("\\", "/").rsplit("/", 1)[-1].lower()
                    if (
                        path_node.get("Type") == "pathName"
                        and path_node.get("Name") == "dataFileName_V2"
                        and palette_name in LEGACY_PALETTE_BASENAMES
                    ):
                        matches.append((data_files, element, path_value))
    return matches


def _remove_legacy_palette_files(scene: ET.Element) -> list[str]:
    removed: list[str] = []
    arrays_to_reindex: list[ET.Element] = []
    for data_files, element, path_value in _legacy_palette_elements(scene):
        if element not in list(data_files):
            continue
        data_files.remove(element)
        removed.append(path_value)
        if data_files not in arrays_to_reindex:
            arrays_to_reindex.append(data_files)

    for data_files in arrays_to_reindex:
        elements = data_files.findall("./Element")
        for index, element in enumerate(elements):
            element.set("Index", str(index))
        data_files.set("Length", str(len(elements)))
    return removed


def isolate_scene_document(text: str, template_subject: str) -> tuple[str, list[str]]:
    """Keep one named Scene/SceneInfo pair and remove missing legacy palettes."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid Workbench scene XML: {exc}") from exc
    if root.tag != "SceneFile":
        raise ValueError(f"Expected SceneFile root, found {root.tag!r}")

    matching_scenes = [
        scene
        for scene in root.findall("./Scene")
        if scene.findtext("./Name") == template_subject
    ]
    if len(matching_scenes) != 1:
        raise ValueError(
            f"Expected exactly one scene named {template_subject!r}, found {len(matching_scenes)}"
        )
    target_scene = matching_scenes[0]
    if target_scene.get("Type") != "SCENE_TYPE_FULL":
        raise ValueError(
            f"Scene {template_subject!r} is not a full Workbench scene "
            f"(Type={target_scene.get('Type')!r})"
        )
    target_index = target_scene.get("Index")
    if target_index is None or not target_index.isascii() or not target_index.isdecimal():
        raise ValueError(f"Scene {template_subject!r} has invalid top-level Index {target_index!r}")

    scene_info_directory = root.find("./SceneInfoDirectory")
    if scene_info_directory is None:
        raise ValueError("Scene template has no SceneInfoDirectory")
    matching_info = [
        info
        for info in scene_info_directory.findall("./SceneInfo")
        if info.get("Index") == target_index
    ]
    if len(matching_info) != 1:
        raise ValueError(
            f"Expected exactly one SceneInfo for index {target_index!r}, found {len(matching_info)}"
        )
    target_info = matching_info[0]
    if target_info.findtext("./Name") != template_subject:
        raise ValueError(
            f"SceneInfo for index {target_index!r} does not name {template_subject!r}"
        )

    for scene in list(root.findall("./Scene")):
        if scene is not target_scene:
            root.remove(scene)
    for info in list(scene_info_directory.findall("./SceneInfo")):
        if info is not target_info:
            scene_info_directory.remove(info)

    target_scene.set("Index", "0")
    target_info.set("Index", "0")
    removed_palettes = _remove_legacy_palette_files(target_scene)

    serialized = ET.tostring(root, encoding="unicode")
    return XML_DECLARATION + serialized, removed_palettes


def scene_render_resource_values(text: str, subject: str) -> set[str]:
    """Return surface, dconn, and scene paths used by one named scene."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid Workbench scene XML: {exc}") from exc
    matching_scenes = [
        scene
        for scene in root.findall("./Scene")
        if scene.findtext("./Name") == subject
    ]
    if len(matching_scenes) != 1:
        raise ValueError(
            f"Expected exactly one scene named {subject!r}, found {len(matching_scenes)}"
        )
    values: set[str] = set()
    for element in matching_scenes[0].iter("Object"):
        if element.get("Type") != "pathName":
            continue
        value = (element.text or "").strip()
        lower_value = value.lower()
        if value and lower_value.endswith((".surf.gii", ".dconn.nii", ".scene")):
            values.add(value)
    return values


def scene_document_needs_pruning(
    text: str, expected_subject: str | None = None
) -> bool:
    """Return True for multi-scene outputs or legacy standalone palette files."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return True
    scenes = root.findall("./Scene")
    if len(scenes) != 1:
        return True
    scene_info_directory = root.find("./SceneInfoDirectory")
    if scene_info_directory is None:
        return True
    scene_infos = scene_info_directory.findall("./SceneInfo")
    if len(scene_infos) != 1:
        return True
    if scenes[0].get("Index") != "0" or scene_infos[0].get("Index") != "0":
        return True
    if scenes[0].get("Type") != "SCENE_TYPE_FULL":
        return True
    scene_name = scenes[0].findtext("./Name")
    scene_info_name = scene_infos[0].findtext("./Name")
    if scene_name != scene_info_name:
        return True
    if expected_subject is not None and scene_name != expected_subject:
        return True
    return bool(_legacy_palette_elements(scenes[0]))
