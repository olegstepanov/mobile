"""3MF exporter with one object per STL part."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from mobile.stl import Triangle, read_binary_stl

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CTYPE_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def _fmt(v: float) -> str:
    txt = f"{v:.6f}".rstrip("0").rstrip(".")
    if txt in {"", "-0"}:
        return "0"
    return txt


def _build_model_xml(part_meshes: list[tuple[str, list[Triangle], float]]) -> bytes:
    ET.register_namespace("", CORE_NS)
    model = ET.Element(f"{{{CORE_NS}}}model", {"unit": "millimeter", "xml:lang": "en-US"})
    resources = ET.SubElement(model, f"{{{CORE_NS}}}resources")
    build = ET.SubElement(model, f"{{{CORE_NS}}}build")

    for object_id, (name, triangles, offset_x) in enumerate(part_meshes, start=1):
        obj = ET.SubElement(
            resources,
            f"{{{CORE_NS}}}object",
            {"id": str(object_id), "type": "model", "name": name},
        )
        mesh = ET.SubElement(obj, f"{{{CORE_NS}}}mesh")
        vertices_el = ET.SubElement(mesh, f"{{{CORE_NS}}}vertices")
        triangles_el = ET.SubElement(mesh, f"{{{CORE_NS}}}triangles")

        vertex_indices: dict[tuple[float, float, float], int] = {}
        tri_indices: list[tuple[int, int, int]] = []

        for v0, v1, v2 in triangles:
            tri = []
            for vx, vy, vz in (v0, v1, v2):
                key = (vx + offset_x, vy, vz)
                idx = vertex_indices.get(key)
                if idx is None:
                    idx = len(vertex_indices)
                    vertex_indices[key] = idx
                    ET.SubElement(
                        vertices_el,
                        f"{{{CORE_NS}}}vertex",
                        {"x": _fmt(key[0]), "y": _fmt(key[1]), "z": _fmt(key[2])},
                    )
                tri.append(idx)
            tri_indices.append((tri[0], tri[1], tri[2]))

        for a, b, c in tri_indices:
            ET.SubElement(
                triangles_el,
                f"{{{CORE_NS}}}triangle",
                {"v1": str(a), "v2": str(b), "v3": str(c)},
            )

        ET.SubElement(build, f"{{{CORE_NS}}}item", {"objectid": str(object_id)})

    return ET.tostring(model, encoding="utf-8", xml_declaration=True)


def _content_types_xml() -> bytes:
    ET.register_namespace("", CTYPE_NS)
    root = ET.Element(
        f"{{{CTYPE_NS}}}Types",
    )
    ET.SubElement(
        root,
        f"{{{CTYPE_NS}}}Default",
        {
            "Extension": "rels",
            "ContentType": "application/vnd.openxmlformats-package.relationships+xml",
        },
    )
    ET.SubElement(
        root,
        f"{{{CTYPE_NS}}}Default",
        {
            "Extension": "model",
            "ContentType": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
        },
    )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _rels_xml() -> bytes:
    ET.register_namespace("", REL_NS)
    root = ET.Element(f"{{{REL_NS}}}Relationships")
    ET.SubElement(
        root,
        f"{{{REL_NS}}}Relationship",
        {
            "Target": "/3D/3dmodel.model",
            "Id": "rel0",
            "Type": "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel",
        },
    )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def export_3mf_files(inputs: list[Path], output: Path, spacing: float = 10.0) -> Path:
    """Write a 3MF package containing one named object per STL input file."""
    part_meshes: list[tuple[str, list[Triangle], float]] = []
    cursor_x = 0.0

    for path in inputs:
        triangles, bounds = read_binary_stl(path)
        offset_x = cursor_x - bounds.min_x
        part_meshes.append((path.stem, triangles, offset_x))
        cursor_x += (bounds.max_x - bounds.min_x) + spacing

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types_xml())
        zf.writestr("_rels/.rels", _rels_xml())
        zf.writestr("3D/3dmodel.model", _build_model_xml(part_meshes))

    return output
