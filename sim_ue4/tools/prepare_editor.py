"""Execute inside UE4.27 Editor using launch.ps1 -Prepare.

Creates materials and an empty persistent map. Scene geometry is loaded at runtime.
Re-running updates generated materials/map only under this standalone project.
"""
import unreal

assets = unreal.AssetToolsHelpers.get_asset_tools()
editing = unreal.MaterialEditingLibrary


def expression(material, cls, x=0):
    return editing.create_material_expression(material, cls, x, 0)


def material(name, roughness, emissive=False, signal=False):
    path = "/Game/Materials/" + name
    mat = unreal.EditorAssetLibrary.load_asset(path)
    if mat is None:
        mat = assets.create_asset(name, "/Game/Materials", unreal.Material, unreal.MaterialFactoryNew())
    editing.delete_all_material_expressions(mat)
    mat.set_editor_property("two_sided", True)
    if signal:
        color = expression(mat, unreal.MaterialExpressionVectorParameter, -500)
        color.set_editor_property("parameter_name", "Tint")
        color.set_editor_property("default_value", unreal.LinearColor(1,0,0,1))
    else:
        color = expression(mat, unreal.MaterialExpressionVertexColor, -500)
    editing.connect_material_property(color, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rough = expression(mat, unreal.MaterialExpressionConstant, -250)
    rough.set_editor_property("r", roughness)
    editing.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    if emissive or signal:
        intensity = expression(mat, unreal.MaterialExpressionScalarParameter, -500)
        intensity.set_editor_property("parameter_name", "Glow")
        intensity.set_editor_property("default_value", 3.0 if emissive else .02)
        multiply = expression(mat, unreal.MaterialExpressionMultiply, -200)
        editing.connect_material_expressions(color, "", multiply, "A")
        editing.connect_material_expressions(intensity, "", multiply, "B")
        editing.connect_material_property(multiply, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    editing.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)


for name, roughness in (("M_Floor",.38),("M_Gloss",.08),("M_Tape",.65),("M_Props",.7)):
    material(name,roughness)
material("M_Emitter",.4,emissive=True)
material("M_Signal",.3,signal=True)
unreal.EditorAssetLibrary.make_directory("/Game/Maps")
if not unreal.EditorAssetLibrary.does_asset_exist("/Game/Maps/Indoor"):
    if not unreal.EditorLevelLibrary.new_level("/Game/Maps/Indoor"):
        raise RuntimeError("Cannot create Indoor map")
else:
    unreal.EditorLevelLibrary.load_level("/Game/Maps/Indoor")
unreal.EditorLevelLibrary.save_current_level()
unreal.log("RoadScenes preparation complete. Open Indoor and press Play.")
