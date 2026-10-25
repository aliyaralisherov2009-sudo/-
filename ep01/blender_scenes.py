"""Процедурные 3D-сцены эпизода 01. Запуск: python3 blender_scenes.py [scene ...]
Рендер: Cycles CPU, кадры в renders/<scene>.png
"""
import bpy, math, random, sys, os, time
from mathutils import Vector

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'renders')
os.makedirs(OUT, exist_ok=True)
RES = (2112, 1188)  # запас 15% под движения камеры в монтаже
PREVIEW = os.environ.get('PREVIEW') == '1'
if PREVIEW:
    RES = (552, 310)
    OUT = OUT + '_preview'; os.makedirs(OUT, exist_ok=True)


# ---------------------------------------------------------------- helpers
def reset(samples=48):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    s = bpy.context.scene
    s.render.engine = 'CYCLES'
    s.cycles.device = 'CPU'
    s.cycles.samples = 8 if PREVIEW else max(16, samples // 2)
    s.cycles.use_denoising = True
    s.cycles.max_bounces = 6
    s.render.resolution_x, s.render.resolution_y = RES
    s.render.image_settings.file_format = 'PNG'
    s.view_settings.view_transform = 'AgX'
    try:
        s.view_settings.look = 'AgX - Medium High Contrast'
    except Exception:
        pass
    return s


def world(color=(0.01, 0.012, 0.02), strength=1.0):
    w = bpy.data.worlds.new('W')
    bpy.context.scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes['Background']
    bg.inputs['Color'].default_value = (*color, 1)
    bg.inputs['Strength'].default_value = strength
    return w


def mat(name, color=(0.5, 0.5, 0.5), rough=0.7, emit=None, estr=0.0, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Roughness'].default_value = rough
    p.inputs['Metallic'].default_value = metal
    if emit:
        p.inputs['Emission Color'].default_value = (*emit, 1)
        p.inputs['Emission Strength'].default_value = estr
    return m


def emission_mat(name, color, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    o = nt.nodes.new('ShaderNodeOutputMaterial')
    e = nt.nodes.new('ShaderNodeEmission')
    e.inputs['Color'].default_value = (*color, 1)
    e.inputs['Strength'].default_value = strength
    nt.links.new(e.outputs[0], o.inputs['Surface'])
    return m


def building_mat(name, wall=(0.18, 0.17, 0.16), lit=0.25, glow=(1.0, 0.75, 0.45), estr=6.0, day=False):
    """Фасад с окнами: окна по сетке, случайные горят."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    p = N['Principled BSDF']
    p.inputs['Base Color'].default_value = (*wall, 1)
    p.inputs['Roughness'].default_value = 0.9
    geo = N.new('ShaderNodeNewGeometry')
    sep = N.new('ShaderNodeSeparateXYZ')
    L.new(geo.outputs['Position'], sep.inputs[0])

    def math_node(op, a, b=None, val=None):
        n = N.new('ShaderNodeMath')
        n.operation = op
        if isinstance(a, float) or isinstance(a, int):
            n.inputs[0].default_value = a
        else:
            L.new(a, n.inputs[0])
        if b is not None:
            if isinstance(b, (float, int)):
                n.inputs[1].default_value = b
            else:
                L.new(b, n.inputs[1])
        return n.outputs[0]

    u = math_node('ADD', sep.outputs['X'], sep.outputs['Y'])
    uw = math_node('MULTIPLY', u, 1 / 2.6)
    zw = math_node('MULTIPLY', sep.outputs['Z'], 1 / 3.0)
    fu = math_node('FRACT', uw)
    fz = math_node('FRACT', zw)
    mu1 = math_node('GREATER_THAN', fu, 0.25)
    mu2 = math_node('LESS_THAN', fu, 0.75)
    mz1 = math_node('GREATER_THAN', fz, 0.3)
    mz2 = math_node('LESS_THAN', fz, 0.78)
    zmin = math_node('GREATER_THAN', sep.outputs['Z'], 2.5)
    mask = math_node('MULTIPLY', math_node('MULTIPLY', mu1, mu2), math_node('MULTIPLY', mz1, mz2))
    mask = math_node('MULTIPLY', mask, zmin)
    obj = N.new('ShaderNodeObjectInfo')
    comb = N.new('ShaderNodeCombineXYZ')
    L.new(math_node('FLOOR', uw), comb.inputs[0])
    L.new(math_node('FLOOR', zw), comb.inputs[1])
    L.new(math_node('MULTIPLY', obj.outputs['Random'], 100.0), comb.inputs[2])
    wn = N.new('ShaderNodeTexWhiteNoise')
    wn.noise_dimensions = '3D'
    L.new(comb.outputs[0], wn.inputs['Vector'])
    on = math_node('LESS_THAN', wn.outputs['Value'], lit)
    em = math_node('MULTIPLY', mask, on)
    # цвет окна: тёмное стекло
    mix = N.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    L.new(mask, mix.inputs['Factor'])
    mix.inputs['A'].default_value = (*wall, 1)
    mix.inputs['B'].default_value = (0.02, 0.025, 0.03, 1) if not day else (0.1, 0.12, 0.14, 1)
    L.new(mix.outputs['Result'], p.inputs['Base Color'])
    rough = math_node('SUBTRACT', 0.9, math_node('MULTIPLY', mask, 0.75))
    L.new(rough, p.inputs['Roughness'])
    p.inputs['Emission Color'].default_value = (*glow, 1)
    L.new(math_node('MULTIPLY', em, estr), p.inputs['Emission Strength'])
    return m


def two_tone_wall(name, low=(0.08, 0.16, 0.11), high=(0.45, 0.42, 0.36), split=1.3):
    """Подъездная стена: снизу краска, сверху побелка."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    p = N['Principled BSDF']
    geo = N.new('ShaderNodeNewGeometry')
    sep = N.new('ShaderNodeSeparateXYZ')
    L.new(geo.outputs['Position'], sep.inputs[0])
    md = N.new('ShaderNodeMath'); md.operation = 'WRAP'
    L.new(sep.outputs['Z'], md.inputs[0]); md.inputs[1].default_value = 3.0; md.inputs[2].default_value = 0.0
    gt = N.new('ShaderNodeMath'); gt.operation = 'GREATER_THAN'
    L.new(md.outputs[0], gt.inputs[0]); gt.inputs[1].default_value = split
    noise = N.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value = 3.0
    mix = N.new('ShaderNodeMix'); mix.data_type = 'RGBA'
    L.new(gt.outputs[0], mix.inputs['Factor'])
    mix.inputs['A'].default_value = (*low, 1)
    mix.inputs['B'].default_value = (*high, 1)
    dirt = N.new('ShaderNodeMix'); dirt.data_type = 'RGBA'; dirt.blend_type = 'MULTIPLY'
    dirt.inputs['Factor'].default_value = 0.6
    L.new(mix.outputs['Result'], dirt.inputs['A'])
    L.new(noise.outputs['Color'], dirt.inputs['B'])
    L.new(dirt.outputs['Result'], p.inputs['Base Color'])
    p.inputs['Roughness'].default_value = 0.85
    return m


def box(loc, size, m=None, rot=(0, 0, 0), name='box', bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(location=loc, rotation=rot)
    o = bpy.context.object
    o.name = name
    o.scale = (size[0] / 2, size[1] / 2, size[2] / 2)
    if m:
        o.data.materials.append(m)
    if bevel:
        bpy.ops.object.transform_apply(scale=True)
        b = o.modifiers.new('b', 'BEVEL'); b.width = bevel; b.segments = 2
    return o


def sphere(loc, r, m=None, scale=(1, 1, 1), seg=24):
    bpy.ops.mesh.primitive_uv_sphere_add(location=loc, radius=r, segments=seg, ring_count=seg // 2)
    o = bpy.context.object
    o.scale = scale
    bpy.ops.object.shade_smooth()
    if m:
        o.data.materials.append(m)
    return o


def cyl(loc, r, h, m=None, rot=(0, 0, 0), verts=16):
    bpy.ops.mesh.primitive_cylinder_add(location=loc, radius=r, depth=h, rotation=rot, vertices=verts)
    o = bpy.context.object
    bpy.ops.object.shade_smooth()
    if m:
        o.data.materials.append(m)
    return o


def plane(loc, size, m=None, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_plane_add(location=loc, rotation=rot)
    o = bpy.context.object
    o.scale = (size[0] / 2, size[1] / 2, 1)
    if m:
        o.data.materials.append(m)
    return o


def light(kind, loc, energy, color=(1, 1, 1), size=0.1, rot=(0, 0, 0), spot=None, blend=0.3):
    bpy.ops.object.light_add(type=kind, location=loc, rotation=rot)
    o = bpy.context.object
    o.data.energy = energy
    o.data.color = color
    if kind in ('POINT', 'SPOT'):
        o.data.shadow_soft_size = size
    if kind == 'AREA':
        o.data.size = size
    if kind == 'SUN':
        o.data.angle = size
    if spot:
        o.data.spot_size = spot
        o.data.spot_blend = blend
    return o


def aim(o, target):
    d = Vector(target) - o.location
    o.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


def camera(loc, target, lens=35, fisheye=None):
    bpy.ops.object.camera_add(location=loc)
    c = bpy.context.object
    aim(c, target)
    c.data.lens = lens
    c.data.clip_end = 2000
    if fisheye:
        c.data.type = 'PANO'
        c.data.panorama_type = 'FISHEYE_EQUISOLID'
        c.data.fisheye_lens = fisheye[0]
        c.data.fisheye_fov = math.radians(fisheye[1])
    bpy.context.scene.camera = c
    return c


def person(loc, rz=0.0, h=1.0, m=None, pose='stand', eyes=None, head_up=0.0, skin=None, hair=None):
    """Силуэт человека из примитивов. Лицо смотрит в +Y локально."""
    parts = []
    x, y, z = loc
    sk = skin or m
    lean = {'stand': 0, 'zombie': 0.25, 'woman': 0, 'hunch': 0.4, 'rise': 0.1}[pose]
    # ноги / платье
    if pose == 'woman':
        bpy.ops.mesh.primitive_cone_add(radius1=0.32, radius2=0.17, depth=0.95, location=(0, 0, 0.55), vertices=24)
        o = bpy.context.object; bpy.ops.object.shade_smooth(); o.data.materials.append(m); parts.append(o)
        for sx in (-0.08, 0.08):
            parts.append(cyl((sx, 0, 0.06), 0.045, 0.14, sk))
    else:
        for sx in (-0.1, 0.1):
            parts.append(cyl((sx, 0, 0.44), 0.075, 0.88, m))
    # торс
    t = sphere((0, 0.05 * lean, 1.17), 0.2, m, scale=(1.15, 0.75, 1.75))
    t.rotation_euler = (lean * 0.6, 0, 0)
    parts.append(t)
    # шея и голова
    hz = 1.58 - 0.06 * lean
    hy = 0.18 * lean
    parts.append(cyl((0, hy * 0.7, hz - 0.1), 0.05, 0.12, sk))
    head = sphere((0, hy, hz), 0.115, sk, scale=(0.9, 1.0, 1.15))
    head.rotation_euler = (-head_up, 0, 0)
    parts.append(head)
    if hair:
        hr = sphere((0, hy - 0.03, hz + 0.02), 0.13, hair, scale=(1.0, 1.0, 1.1))
        parts.append(hr)
        hb = sphere((0, hy - 0.08, hz - 0.22), 0.12, hair, scale=(1.15, 0.55, 2.0))
        parts.append(hb)
    if eyes:
        ez = hz + 0.02 + 0.08 * math.sin(head_up)
        for sx in (-0.04, 0.04):
            parts.append(sphere((sx, hy + 0.105, ez), 0.014, eyes, seg=12))
    # руки
    arm_rx = {'stand': 0.05, 'zombie': -1.2, 'woman': 0.05, 'hunch': 0.3, 'rise': 0.4}[pose]
    for sx in (-0.25, 0.25):
        a = cyl((sx, 0, 1.12), 0.05, 0.6, m)
        a.rotation_euler = (arm_rx, 0, 0.1 if sx > 0 else -0.1)
        if pose == 'zombie':
            a.location = (sx * 0.9, 0.28, 1.28)
        parts.append(a)
    bpy.ops.object.empty_add(location=(0, 0, 0))
    root = bpy.context.object
    for p in parts:
        p.parent = root
    root.location = (x, y, z)
    root.rotation_euler = (0, 0, rz)
    root.scale = (h, h, h)
    return root


def face_rz(x, y, tx, ty):
    return math.atan2(-(tx - x), (ty - y))


def car(loc, rz, color, m_glass, wreck=False):
    m = mat('car', color, 0.35, metal=0.6)
    tire = mat('tire', (0.02, 0.02, 0.02), 0.9)
    bpy.ops.object.empty_add(location=(0, 0, 0))
    root = bpy.context.object
    b = box((0, 0, 0.55), (1.8, 4.3, 0.7), m, bevel=0.08); b.parent = root
    c = box((0, -0.2, 1.1), (1.6, 2.2, 0.55), m_glass, bevel=0.1); c.parent = root
    for sx in (-0.85, 0.85):
        for sy in (-1.35, 1.35):
            w = cyl((sx, sy, 0.33), 0.33, 0.25, tire, rot=(0, math.pi / 2, 0)); w.parent = root
    root.location = loc
    root.rotation_euler = (0, 0.06 if wreck else 0, rz)
    return root


def fire(loc, scale=1.0, seed=0):
    rnd = random.Random(seed)
    core = emission_mat('fire_core', (1.0, 0.55, 0.15), 40)
    outer = emission_mat('fire_out', (1.0, 0.25, 0.04), 18)
    for i in range(7):
        r = rnd.uniform(0.25, 0.55) * scale
        o = sphere((loc[0] + rnd.uniform(-0.6, 0.6) * scale, loc[1] + rnd.uniform(-1.2, 1.2) * scale,
                    loc[2] + rnd.uniform(0, 1.2) * scale), r, core if i % 2 else outer,
                   scale=(0.7, 0.7, rnd.uniform(1.4, 2.4)), seg=12)
    light('POINT', (loc[0], loc[1], loc[2] + 1.2 * scale), 4000 * scale, (1.0, 0.45, 0.12), size=1.0)
    # дым — тёмный объём
    sm = bpy.data.materials.new('smoke'); sm.use_nodes = True
    nt = sm.node_tree; nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    vol = nt.nodes.new('ShaderNodeVolumePrincipled')
    vol.inputs['Color'].default_value = (0.05, 0.05, 0.05, 1)
    vol.inputs['Density'].default_value = 0.35
    nt.links.new(vol.outputs[0], out.inputs['Volume'])
    s = sphere((loc[0], loc[1], loc[2] + 5 * scale), 2.2 * scale, sm, scale=(1.0, 1.0, 2.4), seg=16)


def render(name):
    s = bpy.context.scene
    s.render.filepath = os.path.join(OUT, name + '.png')
    t = time.time()
    bpy.ops.render.render(write_still=True)
    print(f'[render] {name} {time.time() - t:.1f}s', flush=True)


# ---------------------------------------------------------------- city
def city_block(rnd, night=False, lit=0.3, day=False, y_range=(-20, 160), sides=(-1, 1), street_w=16):
    walls = [(0.2, 0.19, 0.18), (0.25, 0.22, 0.19), (0.16, 0.17, 0.18), (0.3, 0.28, 0.25)]
    mats = [building_mat(f'b{i}', walls[i], lit=lit, estr=8.0 if night else 1.5, day=day) for i in range(4)]
    for side in sides:
        y = y_range[0]
        while y < y_range[1]:
            wdt = rnd.uniform(10, 20)
            h = rnd.choice([15, 18, 27, 30, 36, 45]) + rnd.uniform(-1, 1)
            dpt = rnd.uniform(10, 16)
            x = side * (street_w / 2 + 3 + dpt / 2)
            box((x, y + wdt / 2, h / 2), (dpt, wdt - 0.6, h), rnd.choice(mats))
            y += wdt
    # фон: дальние кварталы
    for i in range(60):
        x = rnd.uniform(-150, 150)
        y = rnd.uniform(170, 400)
        h = rnd.uniform(20, 80)
        box((x, y, h / 2), (rnd.uniform(12, 25), rnd.uniform(12, 25), h), rnd.choice(mats))


def street_ground(night=False):
    asphalt = mat('asphalt', (0.035, 0.035, 0.04), 0.55 if night else 0.8)
    side = mat('sidewalk', (0.12, 0.12, 0.12), 0.85)
    plane((0, 100, 0), (600, 800), asphalt)
    for sx in (-1, 1):
        box((sx * 9.5, 70, 0.08), (3, 200, 0.16), side)
    line = mat('line', (0.7, 0.7, 0.65), 0.5)
    for i in range(30):
        box((0, i * 6, 0.005), (0.15, 3, 0.01), line)


def scene_skyline():
    s = reset(48)
    world((0.55, 0.62, 0.72), 0.9)
    rnd = random.Random(3)
    plane((0, 0, 0), (2000, 2000), mat('g', (0.08, 0.08, 0.08), 0.9))
    mats = [building_mat(f'b{i}', c, lit=0.05, estr=0.5, day=True) for i, c in enumerate(
        [(0.35, 0.33, 0.3), (0.28, 0.27, 0.26), (0.4, 0.38, 0.34), (0.22, 0.23, 0.25)])]
    for i in range(420):
        x = rnd.uniform(-400, 400)
        y = rnd.uniform(40, 700)
        h = rnd.choice([15, 27, 30, 45, 54, 60]) * rnd.uniform(0.8, 1.6)
        box((x, y, h / 2), (rnd.uniform(14, 30), rnd.uniform(12, 24), h), rnd.choice(mats))
    sun = light('SUN', (0, 0, 10), 3.5, (1.0, 0.82, 0.62), size=0.02, rot=(math.radians(80), 0, math.radians(200)))
    # туман-дымка
    vm = bpy.data.materials.new('haze'); vm.use_nodes = True
    nt = vm.node_tree; nt.nodes.clear()
    o = nt.nodes.new('ShaderNodeOutputMaterial'); v = nt.nodes.new('ShaderNodeVolumePrincipled')
    v.inputs['Color'].default_value = (0.75, 0.78, 0.82, 1); v.inputs['Density'].default_value = 0.0035
    nt.links.new(v.outputs[0], o.inputs['Volume'])
    box((0, 400, 100), (1200, 900, 200), vm)
    camera((0, -40, 70), (10, 300, 25), lens=40)
    render('skyline')


def scene_street(variant):
    night = variant in ('fire',)
    s = reset(64 if night else 48)
    rnd = random.Random(7)
    if night:
        world((0.004, 0.006, 0.012), 1.0)
    else:
        world((0.5, 0.55, 0.62), 1.2)
    city_block(rnd, night=night, lit=0.25 if night else 0.02, day=not night)
    street_ground(night)
    glass = mat('glass', (0.02, 0.02, 0.025), 0.1, metal=0.2)
    dark = mat('cloth', (0.03, 0.03, 0.035), 0.9)
    skin = mat('skin', (0.25, 0.2, 0.18), 0.6)
    colors = [(0.3, 0.02, 0.02), (0.05, 0.05, 0.06), (0.4, 0.4, 0.42), (0.03, 0.08, 0.2), (0.6, 0.55, 0.45)]
    if variant == 'day':
        sun = light('SUN', (0, 0, 10), 2.5, (0.9, 0.92, 1.0), size=0.3,
                    rot=(math.radians(55), 0, math.radians(30)))
        for i in range(10):
            car((rnd.choice([-3.5, 3.5]) + rnd.uniform(-0.3, 0.3), rnd.uniform(5, 110), 0.15),
                rnd.uniform(-0.1, 0.1) + rnd.choice([0, math.pi]), rnd.choice(colors), glass)
        # военный грузовик
        army = mat('army', (0.08, 0.11, 0.06), 0.8)
        box((-3.2, 18, 1.6), (2.5, 7.5, 2.6), army, bevel=0.05)
        box((-3.2, 13.2, 1.3), (2.4, 2.2, 2.0), army, bevel=0.1)
        for sy in (12.8, 16, 20):
            for sx in (-4.3, -2.1):
                cyl((sx, sy, 0.5), 0.5, 0.4, mat('t', (0.02, 0.02, 0.02)), rot=(0, math.pi / 2, 0))
        for i in range(5):
            soldier = mat('sold', (0.07, 0.09, 0.05), 0.85)
            person((rnd.uniform(-6, -1), rnd.uniform(10, 26), 0), rnd.uniform(0, 6.28), 1.0, soldier, 'stand', skin=skin)
        for i in range(25):
            sx = rnd.choice([-1, 1]) * rnd.uniform(8.5, 10.5)
            person((sx, rnd.uniform(4, 80), 0.16), rnd.uniform(0, 6.28), rnd.uniform(0.92, 1.05), dark,
                   rnd.choice(['stand', 'stand', 'hunch']), skin=skin)
        camera((5.5, -6, 1.7), (-1, 30, 3), lens=30)
        render('street_day')
    elif variant == 'bite':
        sun = light('SUN', (0, 0, 10), 2.0, (0.9, 0.92, 1.0), size=0.3,
                    rot=(math.radians(60), 0, math.radians(-40)))
        cop = mat('cop', (0.02, 0.03, 0.08), 0.7)
        person((0.2, 12, 0), face_rz(0.2, 12, -0.3, 12.6), 1.02, cop, 'stand', skin=skin)
        cap = cyl((0.2, 12, 1.73), 0.13, 0.08, cop)
        person((-0.3, 12.6, 0), face_rz(-0.3, 12.6, 0.2, 12), 1.0, dark, 'zombie', skin=skin)
        for i in range(6):
            car((rnd.choice([-4, 4]), rnd.uniform(18, 70), 0.15), rnd.uniform(-0.6, 0.6), rnd.choice(colors), glass)
        for i in range(10):
            sx = rnd.choice([-1, 1]) * rnd.uniform(8.5, 10.5)
            person((sx, rnd.uniform(10, 60), 0.16), face_rz(sx, 0, 0, 12), 1.0, dark, 'stand', skin=skin)
        camera((2.8, 6.0, 1.2), (-0.1, 12.3, 1.3), lens=45)
        render('street_bite')
    elif variant == 'rise':
        world((0.6, 0.62, 0.66), 1.6)
        sun = light('SUN', (0, 0, 10), 1.5, (1, 0.95, 0.9), size=0.2, rot=(math.radians(20), 0, math.radians(180)))
        person((0, 3.0, 0), face_rz(0, 3, 0, 0), 1.0, dark, 'rise', skin=dark, head_up=-0.25)
        blood = mat('blood', (0.12, 0.0, 0.0), 0.2)
        for i in range(6):
            sphere((rnd.uniform(-0.6, 0.6), 3 + rnd.uniform(-0.6, 0.6), 0.002), rnd.uniform(0.1, 0.35), blood,
                   scale=(1, 1, 0.01), seg=16)
        camera((0.1, 0.6, 0.25), (0, 3.0, 1.6), lens=24)
        render('street_rise')
    elif variant == 'fire':
        for i in range(14):
            cx = rnd.choice([-4, -1.5, 2, 4.5]) + rnd.uniform(-0.5, 0.5)
            cy = rnd.uniform(8, 120)
            car((cx, cy, 0.15), rnd.uniform(-0.8, 0.8), rnd.choice(colors), glass, wreck=True)
            if i % 3 == 0:
                fire((cx, cy, 0.8), 1.0, seed=i)
        # сирены
        light('POINT', (-6, 25, 3), 2500, (1, 0.05, 0.05), size=0.3)
        light('POINT', (6, 40, 3), 2500, (0.05, 0.15, 1), size=0.3)
        lamp = emission_mat('lamp', (1, 0.7, 0.4), 30)
        for i in range(8):
            for sx in (-1, 1):
                cyl((sx * 8.3, i * 18 + 5, 3), 0.06, 6, mat('pole', (0.05, 0.05, 0.05)))
                box((sx * 7.8, i * 18 + 5, 6), (1.2, 0.3, 0.12), lamp)
                if i % 2:
                    light('POINT', (sx * 7.8, i * 18 + 5, 5.8), 400, (1, 0.7, 0.4), size=0.4)
        for i in range(45):
            x = rnd.uniform(-8, 8)
            y = rnd.uniform(4, 70)
            person((x, y, 0), rnd.uniform(0, 6.28), rnd.uniform(0.93, 1.06), dark,
                   rnd.choice(['stand', 'zombie', 'hunch']), skin=dark)
        camera((2.5, -8, 2.2), (-0.5, 40, 4), lens=28)
        render('street_fire')


def scene_window(turned):
    s = reset(64)
    rnd = random.Random(11)
    world((0.006, 0.008, 0.016), 1.0)
    city_block(rnd, night=True, lit=0.12, sides=(-1,), y_range=(-60, 160))
    street_ground(True)
    glass = mat('glass', (0.02, 0.02, 0.025), 0.1, metal=0.2)
    colors = [(0.3, 0.02, 0.02), (0.05, 0.05, 0.06), (0.4, 0.4, 0.42), (0.03, 0.08, 0.2), (0.6, 0.55, 0.45)]
    for i in range(22):
        car((rnd.choice([-4, -1.5, 1.5, 4]) + rnd.uniform(-0.4, 0.4), rnd.uniform(-5, 45), 0.15),
            rnd.uniform(-0.5, 0.5) + rnd.choice([0, math.pi]), rnd.choice(colors), glass)
    lamp = emission_mat('lamp', (1, 0.65, 0.35), 25)
    for i in range(-1, 4):
        for sx in (-1, 1):
            cyl((sx * 8.3, i * 18 + 5, 3), 0.06, 6, mat('pole', (0.05, 0.05, 0.05)))
            box((sx * 7.8, i * 18 + 5, 6), (1.2, 0.3, 0.12), lamp)
            light('POINT', (sx * 7.8, i * 18 + 5, 5.6), 900, (1, 0.65, 0.35), size=0.4)
    cam = (14.0, -4.0, 27.0)
    dark = mat('cloth', (0.035, 0.035, 0.04), 0.9)
    skin = mat('skin', (0.2, 0.18, 0.17), 0.7)
    eyes = emission_mat('eyes', (0.85, 0.95, 1.0), 40) if turned else None
    for i in range(55):
        x = rnd.uniform(-7.5, 8.5)
        y = rnd.uniform(4, 24)
        if turned:
            person((x, y, 0), face_rz(x, y, cam[0], cam[1]), 1.15, dark, 'stand', eyes=eyes, head_up=0.9, skin=skin)
        else:
            person((x, y, 0), rnd.uniform(0, 6.28), 1.15, dark, rnd.choice(['zombie', 'hunch', 'stand']), skin=skin)
    camera(cam, (0.0, 13.0, 0.0), lens=35)
    render('window_turned' if turned else 'window_street')


# ---------------------------------------------------------------- interiors
def apartment(door_light=0.0, tv=True, wardrobe=True, moon=0.4):
    """Комната 5x4.2x2.7, входная дверь в стене y=+2.1, центр x=0.6."""
    wallp = mat('wallpaper', (0.28, 0.24, 0.2), 0.9)
    floor = mat('floor', (0.12, 0.07, 0.04), 0.5)
    ceil = mat('ceil', (0.5, 0.5, 0.48), 0.9)
    box((0, 0, -0.05), (5.2, 4.4, 0.1), floor)
    box((0, 0, 2.75), (5.2, 4.4, 0.1), ceil)
    # передняя стена с проёмом под дверь
    dx = 0.6
    box((dx - 0.5 - 1.6, 2.15, 1.35), (3.2, 0.1, 2.7), wallp)
    box((dx + 0.5 + 1.25, 2.15, 1.35), (2.5, 0.1, 2.7), wallp)
    box((dx, 2.15, 2.4), (1.0, 0.1, 0.6), wallp)
    box((-2.6, 0, 1.35), (0.1, 4.4, 2.7), wallp)
    box((2.6, 0, 1.35), (0.1, 4.4, 2.7), wallp)
    box((0, -2.2, 1.35), (5.2, 0.1, 2.7), wallp)
    door = mat('door', (0.16, 0.09, 0.05), 0.45)
    metal = mat('metal', (0.6, 0.55, 0.45), 0.25, metal=1.0)
    box((dx, 2.16, 1.06), (0.9, 0.06, 2.0), door, bevel=0.01, name='door')
    trim = mat('trim', (0.1, 0.06, 0.03), 0.5)
    box((dx - 0.48, 2.08, 1.05), (0.06, 0.04, 2.1), trim)
    box((dx + 0.48, 2.08, 1.05), (0.06, 0.04, 2.1), trim)
    box((dx, 2.08, 2.1), (1.02, 0.04, 0.06), trim)
    cyl((dx, 2.12, 1.55), 0.012, 0.04, metal, rot=(math.pi / 2, 0, 0))  # глазок
    if door_light > 0:
        strip = emission_mat('strip', (1.0, 0.85, 0.6), door_light)
        box((dx, 2.25, 0.004), (0.88, 0.2, 0.008), strip)
        light('AREA', (dx, 2.6, 0.05), door_light * 6, (1.0, 0.85, 0.6), size=0.9, rot=(math.radians(-95), 0, 0))
    if wardrobe:
        wood = mat('wardrobe', (0.22, 0.13, 0.07), 0.55)
        box((dx + 0.75, 1.72, 1.05), (1.1, 0.6, 2.1), wood, bevel=0.01, rot=(0, 0, math.radians(-8)))
    if tv:
        tvm = mat('tvbody', (0.02, 0.02, 0.02), 0.4)
        box((-2.35, 0.2, 0.9), (0.45, 0.9, 0.6), tvm)
        scr = emission_mat('screen', (0.55, 0.7, 1.0), 6)
        box((-2.12, 0.2, 0.92), (0.01, 0.72, 0.46), scr)
        light('AREA', (-2.0, 0.2, 0.92), 160, (0.5, 0.65, 1.0), size=0.6, rot=(0, math.radians(90), 0))
        box((-2.35, 0.2, 0.3), (0.6, 1.0, 0.6), mat('stand', (0.1, 0.06, 0.03), 0.6))
    if moon > 0:
        # окно в левой стене: холодный свет
        light('AREA', (-2.4, -1.4, 1.8), 90 * moon, (0.45, 0.55, 0.9), size=1.0, rot=(0, math.radians(90), 0))
    # мебель для глубины
    sofa = mat('sofa', (0.12, 0.1, 0.09), 0.9)
    box((1.6, -1.6, 0.25), (1.8, 0.9, 0.5), sofa, bevel=0.05)
    box((1.6, -2.0, 0.55), (1.8, 0.2, 0.6), sofa, bevel=0.05)
    return dx


def scene_room(variant):
    s = reset(64)
    world((0.0, 0.0, 0.0), 0)
    if variant == 'door':
        dx = apartment(door_light=0.0, tv=True, wardrobe=True, moon=0.5)
        light('POINT', (0.8, 0.5, 2.5), 8, (1.0, 0.8, 0.6), size=0.3)
        camera((-0.9, -1.6, 1.45), (0.5, 2.1, 1.1), lens=28)
        render('room_door')
    elif variant == 'dark':
        dx = apartment(door_light=6.0, tv=False, wardrobe=True, moon=0.5)
        light('POINT', (-1.0, -1.0, 2.4), 3, (0.6, 0.7, 1.0), size=0.5)
        camera((0.0, -0.6, 1.5), (0.6, 2.1, 1.0), lens=32)
        render('room_dark')
    elif variant == 'flashlight':
        dx = apartment(door_light=3.0, tv=False, wardrobe=True, moon=0.45)
        light('SPOT', (-0.3, -1.2, 1.35), 220, (1.0, 0.95, 0.85), size=0.02, spot=math.radians(28), blend=0.4)
        aim(bpy.context.object, (0.5, 2.1, 1.25))
        bag = mat('bag', (0.06, 0.08, 0.06), 0.8)
        box((-0.6, 0.6, 0.25), (0.4, 0.25, 0.5), bag, bevel=0.08)
        cyl((-0.3, 0.7, 0.13), 0.04, 0.26, mat('bottle', (0.3, 0.45, 0.55), 0.05))
        # объём для луча
        vm = bpy.data.materials.new('dust'); vm.use_nodes = True
        nt = vm.node_tree; nt.nodes.clear()
        o = nt.nodes.new('ShaderNodeOutputMaterial'); v = nt.nodes.new('ShaderNodeVolumePrincipled')
        v.inputs['Density'].default_value = 0.04
        nt.links.new(v.outputs[0], o.inputs['Volume'])
        box((0, 0, 1.35), (5.0, 4.2, 2.6), vm)
        camera((-0.5, -1.9, 1.5), (0.6, 2.1, 1.2), lens=30)
        render('room_flashlight')
    elif variant == 'empty':
        dx = apartment(door_light=0.0, tv=False, wardrobe=True, moon=0.9)
        light('POINT', (0.6, 1.0, 1.0), 3, (1.0, 0.85, 0.6), size=0.3)
        camera((0.5, 1.4, 1.55), (-1.2, -2.0, 1.2), lens=26)
        render('room_empty')


def scene_handle(n=10):
    s = reset(32)
    world((0, 0, 0), 0)
    door = mat('door', (0.16, 0.09, 0.05), 0.45)
    metal = mat('metal', (0.6, 0.55, 0.45), 0.22, metal=1.0)
    box((0, 0, 1.0), (0.9, 0.06, 2.0), door)
    box((0, 0.2, 1.0), (3, 0.05, 3), mat('wall', (0.2, 0.18, 0.15), 0.9))
    plate = box((0.33, -0.035, 0.95), (0.06, 0.012, 0.26), metal, bevel=0.004)
    cyl((0.33, -0.05, 0.95), 0.025, 0.03, metal, rot=(math.pi / 2, 0, 0))
    bpy.ops.object.empty_add(location=(0.33, -0.065, 0.95))
    pivot = bpy.context.object
    lever = box((0.25, -0.075, 0.95), (0.16, 0.022, 0.03), metal, bevel=0.008)
    lever.parent = pivot
    lever.location = (-0.08, -0.01, 0)
    strip = emission_mat('strip', (1, 0.8, 0.55), 4)
    light('AREA', (0, -0.6, 0.02), 6, (1, 0.8, 0.55), size=0.9, rot=(math.radians(90), 0, 0))
    light('SPOT', (-0.4, -1.2, 1.3), 25, (0.9, 0.95, 1.0), size=0.02, spot=math.radians(20))
    aim(bpy.context.object, (0.3, 0, 0.95))
    camera((0.05, -0.75, 1.02), (0.3, 0, 0.94), lens=55)
    for i in range(n):
        ang = -math.radians(38) * (i / (n - 1)) ** 1.5
        pivot.rotation_euler = (0, -ang, 0)
        render(f'handle_{i:02d}')


def scene_corridor(variant):
    """Вид в глазок: коридор/лестничная площадка, fisheye."""
    s = reset(64)
    world((0, 0, 0), 0)
    wall = two_tone_wall('podezd')
    floor = mat('tile', (0.18, 0.12, 0.09), 0.6)
    ceil = mat('ceil', (0.45, 0.45, 0.42), 0.9)
    L = 9.0
    box((0, L / 2, -0.05), (2.4, L + 1, 0.1), floor)
    box((0, L / 2, 2.75), (2.4, L + 1, 0.1), ceil)
    box((-1.25, L / 2, 1.35), (0.1, L + 1, 2.8), wall)
    box((1.25, 3.2, 1.35), (0.1, 6.4, 2.8), wall)  # справа проём к лестнице после y=6.4
    box((1.25, 8.6, 1.35), (0.1, 0.8, 2.8), wall)
    box((0, L, 1.35), (2.4, 0.1, 2.8), wall)
    # двери соседей
    door = mat('door2', (0.12, 0.06, 0.04), 0.5)
    for y in (2.5, 5.0):
        box((-1.18, y, 1.03), (0.05, 0.9, 2.05), door)
    box((1.18, 3.5, 1.03), (0.05, 0.9, 2.05), door)
    # лестница вниз за проёмом
    step = mat('step', (0.2, 0.19, 0.18), 0.8)
    for k in range(10):
        box((2.3, 6.6 + k * 0.28, -0.08 - k * 0.165), (2.0, 0.3, 0.17), step)
    # лампа
    lamp = emission_mat('bulb', (1.0, 0.85, 0.55), 40)
    sphere((0, 3.2, 2.6), 0.06, lamp)
    light('POINT', (0, 3.2, 2.5), 90, (1.0, 0.8, 0.5), size=0.06)
    light('POINT', (1.6, 7.2, 1.0), 12, (0.6, 0.7, 1.0), size=0.3)
    if variant == 'neighbor':
        dress = mat('dress', (0.25, 0.22, 0.2), 0.9)
        skin = mat('pale', (0.55, 0.52, 0.5), 0.5)
        hair = mat('hair', (0.03, 0.025, 0.02), 0.6)
        eyes = mat('eye', (0.9, 0.9, 0.88), 0.15, emit=(0.6, 0.6, 0.6), estr=0.3)
        person((0.05, 0.75, 0), math.pi * 0, 0.98, dress, 'woman', eyes=eyes, skin=skin, hair=hair)
        # тело смотрит на -Y (к двери): лицо в +Y локально → повернуть на 180
        bpy.context.scene.objects[-1].rotation_euler = (0, 0, math.pi)
    elif variant == 'empty':
        blood = mat('blood', (0.15, 0.0, 0.0), 0.25)
        rnd = random.Random(5)
        y = 0.6
        side = 1
        while y < 6.8:
            x = 0.15 * side + (y / 6.8) * 1.0
            sphere((x, y, 0.003), 0.06, blood, scale=(1.0, 2.0, 0.02), seg=12)
            sphere((x, y + 0.11, 0.003), 0.045, blood, scale=(1.0, 1.0, 0.02), seg=12)
            y += 0.55
            side *= -1
        for i in range(5):
            sphere((rnd.uniform(-0.3, 0.3), rnd.uniform(0.3, 0.8), 0.003), rnd.uniform(0.04, 0.15), blood,
                   scale=(1, 1, 0.02), seg=12)
        # телефон на полу у двери (виден снизу кадра)
        ph = box((-0.2, 0.35, 0.006), (0.075, 0.155, 0.01), mat('ph', (0.01, 0.01, 0.01), 0.2))
        ph.rotation_euler = (0, 0, 0.4)
        scr = emission_mat('phscr', (0.7, 0.8, 1.0), 6)
        sc = box((-0.2, 0.35, 0.012), (0.066, 0.14, 0.002), scr)
        sc.rotation_euler = (0, 0, 0.4)
        light('POINT', (-0.2, 0.35, 0.1), 0.3, (0.6, 0.7, 1.0), size=0.05)
    zoom = variant == 'close'
    if variant == 'close':
        dress = mat('dress', (0.25, 0.22, 0.2), 0.9)
        skin = mat('pale', (0.55, 0.52, 0.5), 0.5)
        hair = mat('hair', (0.03, 0.025, 0.02), 0.6)
        eyes = mat('eye', (0.9, 0.9, 0.88), 0.15, emit=(0.6, 0.6, 0.6), estr=0.3)
        r = person((0.05, 0.55, 0), 0, 0.98, dress, 'woman', eyes=eyes, skin=skin, hair=hair)
        r.rotation_euler = (0, 0, math.pi)
        camera((0, -0.05, 1.6), (0.05, 1.0, 1.5), fisheye=(9, 110))
    else:
        camera((0, -0.05, 1.6), (0, 3.0, 1.1), fisheye=(10.5, 170))
    render({'neighbor': 'peep_neighbor', 'empty': 'peep_empty', 'close': 'peep_close'}[variant])


def scene_phone_floor():
    s = reset(64)
    world((0, 0, 0), 0)
    floor = mat('tile', (0.07, 0.05, 0.04), 0.55)
    box((0, 0, -0.05), (4, 4, 0.1), floor)
    box((0, 0.4, 1.0), (4, 0.1, 2.2), two_tone_wall('w'))
    door = mat('door', (0.14, 0.08, 0.04), 0.5)
    box((0, 0.33, 1.03), (0.9, 0.06, 2.06), door)
    blood = mat('blood', (0.15, 0.0, 0.0), 0.25)
    rnd = random.Random(2)
    for i in range(7):
        sphere((rnd.uniform(-0.3, 0.35), rnd.uniform(-0.05, 0.25), 0.002), rnd.uniform(0.01, 0.045), blood, scale=(1, 1, 0.02), seg=12)
    ph = box((0.05, -0.05, 0.006), (0.075, 0.155, 0.01), mat('ph', (0.01, 0.01, 0.01), 0.2), bevel=0.003)
    ph.rotation_euler = (0, 0, 0.35)
    scr = emission_mat('phscr', (0.75, 0.85, 1.0), 2.5)
    sc = box((0.05, -0.05, 0.0115), (0.068, 0.145, 0.001), scr)
    sc.rotation_euler = (0, 0, 0.35)
    light('AREA', (0.05, -0.05, 0.12), 0.08, (0.6, 0.7, 1.0), size=0.1, rot=(0, 0, 0))
    light('AREA', (0, 0.25, 0.02), 0.6, (1, 0.8, 0.5), size=0.9, rot=(math.radians(-90), 0, 0))
    camera((-0.15, -0.45, 0.32), (0.05, -0.03, 0.0), lens=50)
    render('phone_floor')


def scene_stairwell():
    s = reset(64)
    world((0, 0, 0), 0)
    wall = two_tone_wall('podezd', low=(0.06, 0.12, 0.16), high=(0.42, 0.42, 0.38))
    step = mat('step', (0.22, 0.21, 0.2), 0.8)
    rail = mat('rail', (0.05, 0.04, 0.03), 0.5)
    lamp = emission_mat('bulb', (1.0, 0.85, 0.55), 40)
    W, Dp, H, floors = 3.6, 5.6, 3.0, 9
    well = 1.2
    fw = (W - well) / 2
    for x, y, sx, sy in ((-W / 2 - 0.05, 0, 0.1, Dp), (W / 2 + 0.05, 0, 0.1, Dp),
                         (0, Dp / 2 + 0.05, W, 0.1), (0, -Dp / 2 - 0.05, W, 0.1)):
        box((x, y, floors * H / 2), (sx, sy, floors * H + 3), wall)
    box((0, 0, -0.1), (W, Dp, 0.2), step)
    nst = 9
    run = 3.0 / nst
    for f in range(floors):
        z0 = f * H
        box((0, -2.15, z0 - 0.1), (W, 1.3, 0.2), step)
        box((0, 2.15, z0 + 1.5 - 0.1), (W, 1.3, 0.2), step)
        for k in range(nst):
            box((-well / 2 - fw / 2, -1.5 + (k + 0.5) * run, z0 + (k + 1) * 1.5 / nst - 0.08), (fw, run, 0.17), step)
            box((well / 2 + fw / 2, 1.5 - (k + 0.5) * run, z0 + 1.5 + (k + 1) * 1.5 / nst - 0.08), (fw, run, 0.17), step)
        ang = math.atan2(1.5, 3.0)
        r = box((-well / 2, 0, z0 + 0.75 + 0.9), (0.05, 3.35, 0.05), rail); r.rotation_euler = (ang, 0, 0)
        r = box((well / 2, 0, z0 + 2.25 + 0.9), (0.05, 3.35, 0.05), rail); r.rotation_euler = (-ang, 0, 0)
        for k in range(7):
            yy = -1.35 + k * 0.45
            box((-well / 2, yy, z0 + (yy + 1.5) / 2 + 0.45), (0.02, 0.02, 0.9), rail)
            box((well / 2, yy, z0 + 1.5 + (1.5 - yy) / 2 + 0.45), (0.02, 0.02, 0.9), rail)
        sphere((W / 2 - 0.05, -2.2, z0 + 2.4), 0.07, lamp)
        light('POINT', (W / 2 - 0.3, -2.2, z0 + 2.3), 70, (1.0, 0.8, 0.5), size=0.08)
        sphere((-W / 2 + 0.05, 2.2, z0 + 1.5 + 2.2), 0.06, lamp)
        light('POINT', (-W / 2 + 0.3, 2.2, z0 + 1.5 + 2.1), 40, (1.0, 0.8, 0.5), size=0.08)
    dark = mat('cloth', (0.02, 0.02, 0.022), 0.9)
    # фигура поднимается по маршу на 5 этаже
    yy = 0.0
    person((-well / 2 - fw / 2, yy, 4 * H + (yy + 1.5) / 2), 0, 1.0, dark, 'hunch', skin=dark)
    camera((0.25, -0.4, floors * H + 1.0), (0.0, 0.25, 0.0), lens=18)
    render('stairwell')


def scene_selfie(close):
    s = reset(64)
    world((0, 0, 0), 0)
    apartment(door_light=0.8, tv=False, wardrobe=True, moon=0.35)
    skin = mat('skin', (0.22, 0.16, 0.13), 0.55)
    shirt = mat('shirt', (0.06, 0.07, 0.08), 0.9)
    hair = mat('hair', (0.02, 0.015, 0.01), 0.6)
    # герой: лицо к камере (камера = фронталка телефона)
    me = person((0.25, -0.2, 0), face_rz(0.25, -0.2, 0.3, -1.0), 1.0, shirt, 'stand', skin=skin)
    sphere((0.25, -0.17, 1.66), 0.118, hair, scale=(0.95, 1.0, 0.75))
    shadow = mat('shadow', (0.003, 0.003, 0.003), 1.0)
    if close:
        f = person((-0.22, 0.4, 0), face_rz(-0.22, 0.4, 0.3, -0.8), 1.07, shadow, 'hunch', skin=shadow)
    else:
        f = person((-0.55, 1.65, 0), face_rz(-0.55, 1.65, 0.3, -0.8), 1.12, shadow, 'stand', skin=shadow)
    # свет телефона на лицо
    light('AREA', (0.05, -0.75, 1.4), 0.35, (0.75, 0.85, 1.0), size=0.12, rot=(math.radians(90), 0, 0))
    aim(bpy.context.object, (0, -0.2, 1.6))
    light('AREA', (0.0, 0.9, 2.6), 25, (0.45, 0.55, 0.9), size=1.5)
    aim(bpy.context.object, (0.0, 2.1, 1.2))
    camera((0.3, -0.8, 1.52), (-0.25, 1.5, 1.4), lens=24)
    render('selfie_close' if close else 'selfie_far')


SCENES = {
    'skyline': scene_skyline,
    'street_day': lambda: scene_street('day'),
    'street_bite': lambda: scene_street('bite'),
    'street_rise': lambda: scene_street('rise'),
    'street_fire': lambda: scene_street('fire'),
    'window_street': lambda: scene_window(False),
    'window_turned': lambda: scene_window(True),
    'room_door': lambda: scene_room('door'),
    'room_dark': lambda: scene_room('dark'),
    'room_flashlight': lambda: scene_room('flashlight'),
    'room_empty': lambda: scene_room('empty'),
    'handle': scene_handle,
    'peep_neighbor': lambda: scene_corridor('neighbor'),
    'peep_close': lambda: scene_corridor('close'),
    'peep_empty': lambda: scene_corridor('empty'),
    'phone_floor': scene_phone_floor,
    'stairwell': scene_stairwell,
    'selfie_far': lambda: scene_selfie(False),
    'selfie_close': lambda: scene_selfie(True),
}

if __name__ == '__main__':
    names = sys.argv[1:] or list(SCENES)
    for n in names:
        SCENES[n]()
