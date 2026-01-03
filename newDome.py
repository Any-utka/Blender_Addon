bl_info = {
    "name": "AR Scene Builder (Online Model + Cinematic Camera)",
    "blender": (4, 5, 0),
    "category": "3D View",
    "author": "User + ChatGPT",
    "version": (5, 1),
    "location": "View3D > Sidebar > AR Tools",
    "description": "Создаёт AR сцену с моделью онлайн и кинематографической камерой. Камеру можно анимировать и менять тип облёта без пересоздания сцены.",
}

import bpy
import os
import math
import tempfile
import zipfile
import requests
from mathutils import Vector

SKETCHFAB_TOKEN = "18b726d5e4dc4102a4cfff48a87929bc"

# --------------------------- Проперти сцены ---------------------------
def register_props():
    bpy.types.Scene.ar_video_path = bpy.props.StringProperty(
        name="Video Path", subtype='FILE_PATH', description="Видео для заднего фона"
    )
    bpy.types.Scene.ar_hdri_path = bpy.props.StringProperty(
        name="HDRI Path", subtype='FILE_PATH', description="HDRI окружение"
    )
    bpy.types.Scene.ar_prompt = bpy.props.StringProperty(
        name="Поиск модели", description="Введите запрос для поиска модели на Sketchfab", default="robot"
    )
    bpy.types.Scene.ar_camera_anim_type = bpy.props.EnumProperty(
        name="Тип облёта камеры",
        items=[
            ('CINEMATIC', "CINEMATIC ORBIT", "Классический кинематографичный облёт"),
            ('FIGURE8', "FIGURE-8 ORBIT", "Орбита в форме восьмёрки"),
            ('VERT_HELIX', "VERTICAL HELIX", "Вертикальная спираль вокруг модели"),
            ('TRIANGLE', "TRIANGLE ORBIT", "Треугольный облёт вокруг модели")
        ],
        default='CINEMATIC'
    )


def unregister_props():
    del bpy.types.Scene.ar_video_path
    del bpy.types.Scene.ar_hdri_path
    del bpy.types.Scene.ar_prompt
    del bpy.types.Scene.ar_camera_anim_type

# --------------------------- Утилиты ---------------------------
def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for data_group in (bpy.data.materials, bpy.data.images, bpy.data.textures):
        for item in list(data_group):
            try:
                data_group.remove(item, do_unlink=True)
            except:
                pass

def precise_bounds(obj):
    bb_world = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    min_bb = Vector((min(v.x for v in bb_world), min(v.y for v in bb_world), min(v.z for v in bb_world)))
    max_bb = Vector((max(v.x for v in bb_world), max(v.y for v in bb_world), max(v.z for v in bb_world)))
    center = (min_bb + max_bb) / 2
    size = max_bb - min_bb
    return min_bb, max_bb, center, size

# --------------------------- Импорт / plane / hdri ---------------------------
def download_model_from_sketchfab(prompt):
    url = f"https://api.sketchfab.com/v3/search?type=models&q={prompt}&downloadable=true"
    headers = {"Authorization": f"Token {SKETCHFAB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        raise RuntimeError("Ошибка API Sketchfab")
    results = r.json().get('results', [])
    if not results:
        raise RuntimeError("Моделей не найдено по запросу")
    model_uid = results[0]['uid']
    name = results[0]['name']
    print(f"Загрузка модели: {name}")

    download_url = f"https://api.sketchfab.com/v3/models/{model_uid}/download"
    r = requests.get(download_url, headers=headers)
    if r.status_code != 200:
        raise RuntimeError("Ошибка получения ссылки на скачивание")
    gltf_url = r.json().get('gltf', {}).get('url')
    if not gltf_url:
        raise RuntimeError("GLTF недоступен для этой модели")

    tmp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(tmp_dir, "model.zip")
    r = requests.get(gltf_url, stream=True)
    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(tmp_dir)

    for root_dir, _, files in os.walk(tmp_dir):
        for f in files:
            if f.endswith((".glb", ".gltf")):
                return os.path.join(root_dir, f)
    raise RuntimeError("Файл модели не найден в архиве")

def import_model(filepath, plane):
    bpy.ops.import_scene.gltf(filepath=filepath)
    imported = [o for o in bpy.context.selected_objects if o.type == 'MESH']
    if not imported:
        raise RuntimeError("Импортированная модель не содержит мешей")

    bpy.ops.object.select_all(action='DESELECT')
    for o in imported:
        o.select_set(True)
    bpy.context.view_layer.objects.active = imported[0]
    bpy.ops.object.join()
    joined = bpy.context.active_object
    joined.name = "AR_Model_Geom"

    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0,0,0))
    root = bpy.context.active_object
    root.name = "AR_Model"
    joined.parent = root
    joined.matrix_parent_inverse = root.matrix_world.inverted()

    root.rotation_euler = (math.radians(-90), 0, 0)
    bpy.context.view_layer.update()

    mb = precise_bounds(joined)
    target_height = plane.dimensions.y * 0.2
    scale_factor = target_height / mb[3].z if mb[3].z > 0 else 1.0
    root.scale = (scale_factor,)*3
    bpy.context.view_layer.update()

    mb2 = precise_bounds(joined)
    min_z_after = mb2[0].z
    root.location.z -= min_z_after
    root.location.y = -plane.dimensions.y * 0.5
    return root

def create_video_plane(video_path, width=35.0, height=20.0, location=(0,0,0)):
    bpy.ops.mesh.primitive_plane_add(size=1, location=location, rotation=(1.5708,0,0))
    plane = bpy.context.active_object
    plane.name = "AR_Background"
    plane.scale.x = width/2
    plane.scale.y = height/2

    mat = bpy.data.materials.new(name="Video_Mat")
    mat.use_nodes=True
    plane.data.materials.append(mat)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    tex = nodes.new("ShaderNodeTexImage")

    img = bpy.data.images.load(bpy.path.abspath(video_path))
    img.source='MOVIE'
    tex.image=img
    tex.image_user.use_auto_refresh=True
    tex.image_user.frame_start=1
    links.new(tex.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])

    if bpy.context.scene.frame_end < img.frame_duration:
        bpy.context.scene.frame_end = img.frame_duration
    return plane

def setup_lighting(root):
    scene = bpy.context.scene
    geom = root.children[0] if root.children else root
    mb = precise_bounds(geom)
    center = mb[2]
    size = max(mb[3].x, mb[3].y, mb[3].z)

    # ---------- Key Light ----------
    bpy.ops.object.light_add(type='AREA', location=(center.x + size, center.y + size, center.z + size*1.5))
    key = bpy.context.active_object
    key.name = "Key_Light"
    key.data.energy = 800
    key.data.size = size
    key.data.use_shadow = True
    key.data.shadow_soft_size = size * 0.5

    # ---------- Rim Light (Optional) ----------
    bpy.ops.object.light_add(type='AREA', location=(center.x - size, center.y - size, center.z + size))
    rim = bpy.context.active_object
    rim.name = "Rim_Light"
    rim.data.energy = 400
    rim.data.size = size
    rim.data.use_shadow = True
    rim.data.shadow_soft_size = size * 0.5

    # ---------- HDRI ----------
    if bpy.context.scene.ar_hdri_path:
        hdri_path = bpy.path.abspath(bpy.context.scene.ar_hdri_path)
        if os.path.exists(hdri_path):
            world = bpy.context.scene.world
            world.use_nodes = True
            nodes = world.node_tree.nodes
            links = world.node_tree.links
            nodes.clear()
            output = nodes.new("ShaderNodeOutputWorld")
            bg = nodes.new("ShaderNodeBackground")
            env = nodes.new("ShaderNodeTexEnvironment")
            env.image = bpy.data.images.load(hdri_path)
            links.new(env.outputs["Color"], bg.inputs["Color"])
            links.new(bg.outputs["Background"], output.inputs["Surface"])


# --------------------------- Камера / контроллер / анимации ---------------------------
def ensure_camera_and_controller(root):
    """Создаёт (или возвращает) объекты AR_Camera и Camera_Controller и TrackTo constraint."""
    geom = root.children[0] if root.children else root
    mb = precise_bounds(geom)
    center = mb[2]
    extents = mb[3]

    # Контроллер
    ctrl = bpy.data.objects.get("Camera_Controller")
    if ctrl is None:
        bpy.ops.object.empty_add(type='PLAIN_AXES', location=center)
        ctrl = bpy.context.active_object
        ctrl.name = "Camera_Controller"
    else:
        ctrl.location = center 

    # Камера
    cam = bpy.data.objects.get("AR_Camera")
    if cam is None:
        bpy.ops.object.camera_add(location=(center.x, center.y - extents.y*3, center.z))
        cam = bpy.context.active_object
        cam.name = "AR_Camera"
        cam.data.lens = 45
        cam.data.clip_start = 0.1
        cam.data.show_passepartout = True
        cam.data.passepartout_alpha = 0.95
        cam.parent = ctrl
        track = cam.constraints.new(type='TRACK_TO')
        track.target = root
        track.track_axis = 'TRACK_NEGATIVE_Z'
        track.up_axis = 'UP_Y'
    else:
        cam.parent = ctrl
        # ensure there's a Track To constraint targeting root
        has_track = any((c.type == 'TRACK_TO' and c.target == root) for c in cam.constraints)
        if not has_track:
            track = cam.constraints.new(type='TRACK_TO')
            track.target = root
            track.track_axis = 'TRACK_NEGATIVE_Z'
            track.up_axis = 'UP_Y'

    return cam, ctrl

def clear_controller_keyframes(ctrl):
    """Удаляет анимационные данные контроллера (чтобы перестроить новые ключи)."""
    if ctrl is None:
        return
    if ctrl.animation_data:
        # удаляем fcurves аккуратно
        ctrl.animation_data_clear()

def apply_camera_animation(root, anim_type='CINEMATIC', frames=250):
    """Записывает ключи для Controller по выбранной формуле без пересоздания сцены."""
    cam, ctrl = ensure_camera_and_controller(root)
    geom = root.children[0] if root.children else root
    mb = precise_bounds(geom)
    center = mb[2]
    extents = mb[3]

    clear_controller_keyframes(ctrl)

    frames = max(1, frames)
    radius = max(extents.x, extents.y) * 2.5

    for f in range(1, frames + 1):
        t = (f - 1) / frames
        angle = 2 * math.pi * t

        # -----------------------------
        # 1) CINEMATIC ORBIT
        # -----------------------------
        if anim_type == 'CINEMATIC':
            # круг с лёгким высотным колебанием (как в исходном варианте)
            theta = 2 * math.pi * t + math.pi
            phi = math.sin(2 * math.pi * t) * math.radians(20)
            x = center.x + radius * math.cos(phi) * math.sin(theta)
            y = center.y + radius * math.cos(phi) * math.cos(theta)
            z = center.z + radius * math.sin(phi)
            ctrl.location = Vector((x, y, z))

        # -----------------------------
        # 2) FIGURE-8 ORBIT
        # -----------------------------
        elif anim_type == 'FIGURE8':
            a = radius * 0.9
            x = center.x + a * math.sin(angle)
            y = center.y + a * 0.5 * math.sin(2 * angle)
            z = center.z + math.sin(angle * 0.5) * (extents.z * 0.15)
            ctrl.location = Vector((x, y, z))

        # -----------------------------
        # 3) VERTICAL HELIX
        # -----------------------------
        elif anim_type == 'VERT_HELIX':
            spiral_h = extents.z * 1.5
            x = center.x + radius * math.cos(angle)
            y = center.y + radius * math.sin(angle)
            z = center.z + spiral_h * math.sin(angle * 2) * 0.5
            ctrl.location = Vector((x, y, z))

        # -----------------------------
        # 4) TRIANGLE ORBIT
        # -----------------------------
        elif anim_type == 'TRIANGLE':
            # TRIANGLE ORBIT — равносторонний треугольник
            # Делим круг на 3 сектора
            sector = t * 3.0
            frac = sector % 1.0
            part = int(sector)

            # Три точки треугольника
            A = Vector((center.x + radius, center.y, center.z))
            B = Vector((center.x - radius/2, center.y + radius*0.866, center.z))
            C = Vector((center.x - radius/2, center.y - radius*0.866, center.z))

            if part == 0:
                pos = A.lerp(B, frac)
            elif part == 1:
                pos = B.lerp(C, frac)
            else:
                pos = C.lerp(A, frac)

            ctrl.location = pos

        ctrl.keyframe_insert(data_path="location", frame=f)

    bpy.context.scene.camera = cam
    return cam, ctrl

# --------------------------- Операторы ---------------------------
class AR_OT_BuildScene(bpy.types.Operator):
    bl_idname = "ar.build_scene"
    bl_label = "Создать AR сцену"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        video = scene.ar_video_path
        hdri = scene.ar_hdri_path
        prompt = scene.ar_prompt
        anim_type = scene.ar_camera_anim_type

        if not video or not os.path.isfile(bpy.path.abspath(video)):
            self.report({'ERROR'}, "Выбери корректный видеофайл!")
            return {'CANCELLED'}

        clear_scene()
        plane = create_video_plane(video)
        model_path = download_model_from_sketchfab(prompt)
        root = import_model(model_path, plane)

        setup_lighting(root)
        apply_camera_animation(root, anim_type='CINEMATIC', frames=scene.frame_end)

        self.report({'INFO'}, "AR сцена создана!")
        return {'FINISHED'}

class AR_OT_ApplyCameraAnimation(bpy.types.Operator):
    bl_idname = "ar.apply_camera_animation"
    bl_label = "Применить анимацию камеры"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        anim_type = scene.ar_camera_anim_type
        root = bpy.data.objects.get("AR_Model")
        if root is None:
            self.report({'ERROR'}, "Сначала создай AR сцену (кнопка Create).")
            return {'CANCELLED'}
        apply_camera_animation(root, anim_type=anim_type, frames=scene.frame_end)
        self.report({'INFO'}, f"Анимация камеры применена: {anim_type}")
        return {'FINISHED'}

# --------------------------- Панель ---------------------------
class AR_PT_ScenePanel(bpy.types.Panel):
    bl_label = "AR Tools"
    bl_idname = "AR_PT_scene_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'AR Tools'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, "ar_video_path")
        layout.prop(scene, "ar_hdri_path")
        layout.prop(scene, "ar_prompt")
        row = layout.row(align=True)
        row.operator("ar.build_scene", text="Create AR Scene")
        layout.separator()
        layout.prop(scene, "ar_camera_anim_type")
        layout.operator("ar.apply_camera_animation", text="Применить анимацию камеры")

# --------------------------- Регистрация ---------------------------
classes = [AR_OT_BuildScene, AR_OT_ApplyCameraAnimation, AR_PT_ScenePanel]

def register():
    for c in classes:
        bpy.utils.register_class(c)
    register_props()

def unregister():
    for c in classes:
        bpy.utils.unregister_class(c)
    unregister_props()

if __name__ == "__main__":
    register()