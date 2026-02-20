bl_info = {
    "name": "AR Scene Builder (Online Model + Cinematic Camera + Tail)",
    "blender": (4, 5, 0),
    "category": "3D View",
    "author": "User + ChatGPT",
    "version": (4, 7),
    "location": "View3D > Sidebar > AR Tools",
    "description": "Создаёт AR сцену с моделью онлайн, кинематографической камерой, фиолетовым куполом и хвостом.",
}

import bpy
import os
import math
import tempfile
import zipfile
import requests
from mathutils import Vector

# ---------------------------
# Sketchfab API Token
# ---------------------------
SKETCHFAB_TOKEN = ""

# ---------------------------
# Свойства сцены
# ---------------------------
def register_props():
    bpy.types.Scene.ar_video_path = bpy.props.StringProperty(
        name="Video Path",
        subtype='FILE_PATH',
        description="Видео для заднего фона"
    )
    bpy.types.Scene.ar_hdri_path = bpy.props.StringProperty(
        name="HDRI Path",
        subtype='FILE_PATH',
        description="HDRI окружение"
    )
    bpy.types.Scene.ar_prompt = bpy.props.StringProperty(
        name="Поиск модели",
        description="Введите запрос для поиска модели на Sketchfab",
        default="robot"
    )
    bpy.types.Scene.ar_model_rot = bpy.props.FloatVectorProperty(
        name="Доп. поворот (°)",
        subtype='EULER',
        default=(0.0, 0.0, 0.0)
    )

def unregister_props():
    del bpy.types.Scene.ar_video_path
    del bpy.types.Scene.ar_hdri_path
    del bpy.types.Scene.ar_prompt
    del bpy.types.Scene.ar_model_rot

# ---------------------------
# Очистка сцены
# ---------------------------
def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for data_group in (bpy.data.materials, bpy.data.images, bpy.data.textures):
        for item in list(data_group):
            try:
                data_group.remove(item, do_unlink=True)
            except:
                pass

# ---------------------------
# Sketchfab загрузка модели
# ---------------------------
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

    for root, _, files in os.walk(tmp_dir):
        for f in files:
            if f.endswith((".glb", ".gltf")):
                return os.path.join(root, f)
    raise RuntimeError("Файл модели не найден в архиве")

# ---------------------------
# Границы меша
# ---------------------------
def mesh_world_bounds(obj):
    coords = [obj.matrix_world @ v.co for v in obj.data.vertices]
    if not coords:
        return None
    min_v = Vector((min(c.x for c in coords), min(c.y for c in coords), min(c.z for c in coords)))
    max_v = Vector((max(c.x for c in coords), max(c.y for c in coords), max(c.z for c in coords)))
    center = (min_v + max_v) / 2.0
    extents = max_v - min_v
    return min_v, max_v, center, extents

# ---------------------------
# Импорт модели
# ---------------------------
def import_model(filepath, plane, rotation=(0,0,0)):
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

    base_rot = (math.radians(-90),0,0)
    user_rot = tuple(math.radians(a) for a in rotation)
    root.rotation_euler = (base_rot[0]+user_rot[0], base_rot[1]+user_rot[1], base_rot[2]+user_rot[2])

    bpy.context.view_layer.update()

    # Масштабирование по высоте
    mb = mesh_world_bounds(joined)
    if mb:
        min_v, max_v, _, _ = mb
        model_height = max_v.z - min_v.z if max_v.z > min_v.z else 1.0
        target_height = plane.dimensions.y * 0.2
        scale_factor = target_height / model_height
        root.scale = (scale_factor,)*3

    bpy.context.view_layer.update()

    coords_after = [joined.matrix_world @ v.co for v in joined.data.vertices]
    min_z_after = min((c.z for c in coords_after), default=0.0)
    root.location.z -= min_z_after
    root.location.y = -plane.dimensions.y*0.5
    return root

# ---------------------------
# Видео-плоскость
# ---------------------------
def create_video_plane(video_path, width=27.0, height=20.0, location=(0,0,0)):
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

# ---------------------------
# Освещение
# ---------------------------
def setup_lighting(root):
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 250
    positions = [(3,-3,3),(-3,3,2),(0,0,4)]
    energies = [1000,800,600]
    rotations = [(math.radians(60),0,math.radians(45)),(math.radians(60),0,math.radians(-135)),(math.radians(90),0,0)]
    lights=[]
    for i,pos in enumerate(positions):
        bpy.ops.object.light_add(type='AREA',location=pos)
        light = bpy.context.active_object
        light.data.energy=energies[i]
        light.data.size=6.0
        light.rotation_euler=rotations[i]
        lights.append(light)
    for light in lights:
        base=light.data.energy
        for f in range(scene.frame_start, scene.frame_end+1):
            t=f/10.0
            light.data.energy=base*(0.3+1.2*abs(math.sin(t*3.14*2.5)))
            light.data.keyframe_insert(data_path="energy", frame=f)

# ---------------------------
# HDRI
# ---------------------------
def setup_hdri(hdri_path):
    if not hdri_path or not os.path.exists(hdri_path):
        return
    world=bpy.context.scene.world
    world.use_nodes=True
    nodes=world.node_tree.nodes
    links=world.node_tree.links
    env=nodes.new("ShaderNodeTexEnvironment")
    env.image=bpy.data.images.load(hdri_path)
    bg=nodes.get("Background")
    if bg:
        links.new(env.outputs["Color"], bg.inputs["Color"])

# ---------------------------
# Камера на модели
# ---------------------------
def add_camera_fit_scene(root, plane):
    import math
    from mathutils import Vector

    scene = bpy.context.scene
    total_frames = scene.frame_end

    # Берём границы модели
    if root.children:
        model_geom = root.children[0]
        mb = mesh_world_bounds(model_geom)
        center = mb[2]  # центр модели
        extents = mb[3]  # размеры модели
    else:
        center = root.location
        extents = root.dimensions

    # Настройки широкого объектива
    cam_lens = 15  # мм
    sensor_width = 20  # мм
    sensor_height = 15  # мм

    # Рассчитываем необходимое расстояние, чтобы модель полностью помещалась с запасом
    model_height = extents.z * 1.1
    model_width = max(extents.x, extents.y) * 1.1

    fov_h = 2 * math.atan(sensor_width / (2 * cam_lens))
    fov_v = 2 * math.atan(sensor_height / (2 * cam_lens))

    distance_h = model_width / (2 * math.tan(fov_h / 2))
    distance_v = model_height / (2 * math.tan(fov_v / 2))

    distance = max(distance_h, distance_v) * 1.1  # +10% запас

    # Камера строго параллельна модели, на уровне центра
    base_z = center.z + model_height / 2
    bpy.ops.object.camera_add(location=(center.x, center.y - distance, base_z))
    cam = bpy.context.active_object
    cam.name = "AR_Camera"
    cam.data.lens = cam_lens
    cam.data.clip_start = 0.1

    # Направляем камеру на центр модели (параллельно)
    track = cam.constraints.new(type='TRACK_TO')
    track.target = root
    track.track_axis = 'TRACK_NEGATIVE_Z'
    track.up_axis = 'UP_Y'

    # Камера остаётся на месте первые кадры, потом плавно вращается
    for f in range(1, total_frames + 1):
        t = f / total_frames
        if t < 0.1:  # первые 10% времени статично
            x = center.x
            y = center.y - distance
        else:  # плавное вращение вокруг модели
            angle = 2 * math.pi * (t - 0.1) / 0.9
            x = center.x + distance * 0.15 * math.sin(angle)
            y = center.y - distance * math.cos(angle)
        z = base_z
        cam.location = Vector((x, y, z))
        cam.keyframe_insert(data_path="location", frame=f)

    scene.camera = cam
    return cam


# ---------------------------
# Купол
# ---------------------------
def add_foggy_dome(root, plane):
    if root.children:
        geom=root.children[0]
        mb=mesh_world_bounds(geom)
        center=mb[2] if mb else root.location
    else:
        center=root.location
    radius=max(plane.dimensions.x, plane.dimensions.y)*1.5
    bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=radius, location=center)
    dome=bpy.context.active_object
    dome.name="AR_Fog_Dome"
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.flip_normals()
    bpy.ops.object.mode_set(mode='OBJECT')
    mat=bpy.data.materials.new(name="Fog_Dome_Mat")
    mat.use_nodes=True
    nodes=mat.node_tree.nodes
    links=mat.node_tree.links
    nodes.clear()
    output=nodes.new("ShaderNodeOutputMaterial")
    emission=nodes.new("ShaderNodeEmission")
    gradient=nodes.new("ShaderNodeTexGradient")
    coord=nodes.new("ShaderNodeTexCoord")
    ramp=nodes.new("ShaderNodeValToRGB")
    transparent=nodes.new("ShaderNodeBsdfTransparent")
    mix=nodes.new("ShaderNodeMixShader")
    gradient.gradient_type='SPHERICAL'
    ramp.color_ramp.elements[0].position=0.1
    ramp.color_ramp.elements[0].color=(0.8,0.1,1.0,1.0)
    ramp.color_ramp.elements[1].position=1.0
    ramp.color_ramp.elements[1].color=(0.0,0.0,0.0,0.0)
    links.new(coord.outputs["Object"], gradient.inputs["Vector"])
    links.new(gradient.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], emission.inputs["Color"])
    emission.inputs["Strength"].default_value=1.5
    links.new(emission.outputs["Emission"], mix.inputs[2])
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    mix.inputs["Fac"].default_value=0.5
    links.new(mix.outputs["Shader"], output.inputs["Surface"])
    dome.data.materials.append(mat)
    dome.display_type='SOLID'
    dome.show_in_front=True
    return dome

# ---------------------------
# Хвост за моделью
# ---------------------------
def add_trailing_tail(root, segments=30, length_factor=0.5):
    if not root.children:
        return None
    geom = root.children[0]

    bpy.ops.curve.primitive_bezier_curve_add()
    curve = bpy.context.active_object
    curve.name = "AR_Tail"
    curve.data.dimensions = '3D'

    spline = curve.data.splines[0]

    # Устанавливаем нужное количество точек
    spline.bezier_points.add(segments - 1)  # первая точка уже есть

    for i, bp in enumerate(spline.bezier_points):
        offset = Vector((0, -i * length_factor, 0))
        bp.co = root.location + offset
        bp.handle_left_type = bp.handle_right_type = 'AUTO'

    curve.data.bevel_depth = 0.02
    curve.data.bevel_resolution = 3
    return curve

# ---------------------------
# Основной оператор
# ---------------------------
class AR_OT_BuildScene(bpy.types.Operator):
    bl_idname="ar.build_scene"
    bl_label="Создать AR сцену"
    bl_options={'REGISTER','UNDO'}

    def execute(self, context):
        video=context.scene.ar_video_path
        hdri=context.scene.ar_hdri_path
        prompt=context.scene.ar_prompt
        rot=tuple(context.scene.ar_model_rot)

        if not video or not os.path.isfile(bpy.path.abspath(video)):
            self.report({'ERROR'},"Выбери корректный видеофайл!")
            return {'CANCELLED'}

        clear_scene()
        plane=create_video_plane(video)
        model_path=download_model_from_sketchfab(prompt)
        root=import_model(model_path, plane, rotation=rot)
        setup_lighting(root)
        setup_hdri(hdri)
        cam = add_camera_fit_scene(root, plane)
        add_foggy_dome(root, plane)
        add_trailing_tail(root)

        self.report({'INFO'},"AR сцена создана!")
        return {'FINISHED'}

# ---------------------------
# Панель
# ---------------------------
class AR_PT_ScenePanel(bpy.types.Panel):
    bl_label="AR Scene Builder"
    bl_idname="AR_PT_scene_builder"
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category="AR Tools"

    def draw(self, context):
        layout=self.layout
        layout.prop(context.scene,"ar_video_path")
        layout.prop(context.scene,"ar_hdri_path")
        layout.prop(context.scene,"ar_prompt")
        layout.prop(context.scene,"ar_model_rot")
        layout.operator(AR_OT_BuildScene.bl_idname)

# ---------------------------
# Регистрация
# ---------------------------
classes=[AR_OT_BuildScene, AR_PT_ScenePanel]

def register():
    for c in classes:
        bpy.utils.register_class(c)
    register_props()

def unregister():
    for c in classes:
        bpy.utils.unregister_class(c)
    unregister_props()

if __name__=="__main__":
    register()
