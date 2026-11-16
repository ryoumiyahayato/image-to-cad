"""Group a proved painted component as one movable CAD block."""


def source_component(doc, space, entities, name, aliases):
    block = doc.blocks.new(name=name)
    for entity in entities:
        space.unlink_entity(entity)
        block.add_entity(entity)
    insert = space.add_blockref(block.name, (0, 0), dxfattribs={"layer": entities[0].dxf.layer})
    appid = "PDF_PATH_ALIASES"
    if appid not in doc.appids:
        doc.appids.new(appid)
    insert.set_xdata(appid, [tag for alias in aliases for tag in (
        (1000, alias["id"]),
        (1000, alias.get("role", "paint_component")),
        (1071, alias["object_index"]),
        (1071, alias.get("subpath", -1)),
        (1071, alias.get("edge", -1)),
    )])
    return insert


def attach_fixed_signing_fragments(doc, space, shared, fragments):
    """Keep generated, zero-origin fragment geometry in the fixed shared block."""
    target = doc.blocks[shared.dxf.name]
    tags = list(shared.get_xdata("SIGNING_SOURCE"))
    for fragment in fragments:
        name = fragment.dxf.name
        block = doc.blocks[name]
        kind = fragment.get_xdata("IMAGE_TO_CAD")[0].value
        source_box = fragment.get_xdata("SIGNING_SOURCE")[1].value
        tags.extend(((1000, "FIXED_MEMBER"), (1000, kind), (1000, source_box)))
        for child in list(block):
            if child.dxftype() == "IMAGE":
                for appid in ("IMAGE_TO_CAD", "SIGNING_SOURCE", "PDF_PATH_ALIASES"):
                    child.set_xdata(appid, fragment.get_xdata(appid))
            block.unlink_entity(child)
            target.add_entity(child)
        space.delete_entity(fragment)
        # These block names were allocated by this write and had one reference.
        doc.blocks.delete_block(name, safe=False)
    shared.set_xdata("SIGNING_SOURCE", tags)
