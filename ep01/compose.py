"""Монтаж эпизода 01: кадры Blender + графика PIL → видео (без звука).
python3 compose.py [--preview] [--from T --to T]
"""
import json, math, os, sys, subprocess, random
from functools import lru_cache
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
REN = os.environ.get('REN', os.path.join(HERE, 'renders'))
BUILD = os.path.join(HERE, 'build')
os.makedirs(BUILD, exist_ok=True)
FPS = 24
W, H = 1920, 1080
SW, SH = 2112, 1188  # размер исходников
FONT_B = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
FONT_R = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FONT_T = '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'
FONT_M = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'

TL = json.load(open(os.path.join(HERE, 'timeline.json'), encoding='utf-8'))
UNITS = TL['units']
AUDIO_DUR = TL['duration']
END_CARD = 5.0
TOTAL = AUDIO_DUR + END_CARD


def font(path, size):
    return ImageFont.truetype(path, size)


# ------------------------------------------------------------------ раскадровка
# (префикс фразы, параметры кадра). Кадр длится от начала фразы до начала следующей.
# img: имя рендера или спецкадр (tv:N, phone:VAR, handle, black)
# z: зум (начало, конец); c: центр кадра (x,y) 0..1 начало/конец
# fx: эффекты; g: грейд; gain: яркость
SHOTS = [
    ('Я думал, что конец', dict(img='skyline', z=(1.0, 1.1), c=((.5, .5), (.52, .47)), g='cold', fi=1.2)),
    ('Или ядерного', dict(img='skyline', z=(1.12, 1.2), c=((.55, .45), (.55, .45)), g='cold', fx={'nuke': 0.35})),
    ('Но всё началось', dict(img='skyline', z=(1.25, 1.15), c=((.4, .55), (.45, .5)), g='morning')),
    ('Сначала перестали', dict(img='phone:nosignal', z=(1.0, 1.06), g='none', fx={'glitch': 0.12})),
    ('Потом на улицах', dict(img='street_day', z=(1.0, 1.08), c=((.45, .5), (.5, .5)), g='day')),
    ('А через несколько', dict(img='street_day', z=(1.2, 1.35), c=((.55, .55), (.62, .55)), g='day',
                              fx={'handheld': 9, 'redpulse': 0.18})),
    ('Я видел, как мужчина', dict(img='street_bite', z=(1.0, 1.25), c=((.5, .5), (.45, .45)), g='day', gain=1.5,
                                 fx={'handheld': 4})),
    ('Полицейский выстрелил', dict(img='street_bite', z=(1.35, 1.4), c=((.45, .42), (.45, .42)), g='day', gain=1.5,
                                   fx={'flashes': [1.15, 1.55, 1.95], 'hits': [1.15, 1.55, 1.95]})),
    ('Он всё равно', dict(img='street_rise', z=(1.0, 1.15), c=((.5, .62), (.5, .45)), g='cold', fx={'handheld': 3})),
    ('В тот момент', dict(img='street_rise', z=(1.18, 1.0), c=((.5, .45), (.5, .5)), g='bleak', fo=1.0)),
    # ГОРОД УМИРАЕТ
    ('К вечеру', dict(img='street_fire', z=(1.0, 1.1), c=((.5, .5), (.5, .5)), g='fire', gain=0.72, fi=0.6,
                      fx={'siren': 0.08, 'firefl': 0.08})),
    ('Машины горели', dict(img='street_fire', z=(1.45, 1.6), c=((.7, .62), (.72, .6)), g='fire', gain=0.72,
                           fx={'firefl': 0.15, 'handheld': 3})),
    ('Люди ломились', dict(img='street_fire', z=(1.5, 1.5), c=((.3, .6), (.4, .58)), g='fire', gain=0.72,
                           fx={'firefl': 0.1, 'siren': 0.1, 'handheld': 5})),
    ('Сирены звучали', dict(img='street_fire', z=(1.2, 1.3), c=((.5, .5), (.5, .45)), g='fire', gain=0.72,
                            fx={'siren': 0.3, 'firefl': 0.1})),
    ('Я бежал домой', dict(img='street_fire', z=(1.1, 1.5), c=((.5, .55), (.5, .5)), g='fire', gain=0.72,
                           fx={'handheld': 16, 'siren': 0.12, 'whip': 1})),
    ('Когда добрался', dict(img='room_door', z=(1.0, 1.1), c=((.5, .5), (.55, .5)), g='interior', gain=1.6,
                            fx={'handheld': 3})),
    ('На телевизоре', dict(img='tv:0', z=(1.0, 1.04), g='none', fx={'tv': 1})),
    ('«Не выходите', dict(img='tv:1', z=(1.0, 1.04), g='none', fx={'tv': 1}, nosub=1)),
    ('Не приближайтесь', dict(img='tv:2', z=(1.04, 1.08), g='none', fx={'tv': 1}, nosub=1)),
    ('Если вас укусили', dict(img='tv:3', z=(1.08, 1.12), g='none', fx={'tv': 1, 'glitch': 0.35}, nosub=1)),
    ('Трансляция оборвалась', dict(img='tv:static', z=(1.0, 1.0), g='none', fx={'static': 1, 'glitch': 0.6}, fo=0.3)),
    ('А потом в дверь', dict(img='room_dark', z=(1.0, 1.15), c=((.6, .68), (.6, .68)), g='interior', gain=4.2,
                             fx={'hits': [0.9, 1.3, 1.7], 'hitamp': 6})),
    ('Это была моя соседка', dict(img='peep_neighbor', z=(1.0, 1.05), g='peep', fx={'flicker': 0.08})),
    ('Она плакала', dict(img='peep_neighbor', z=(1.05, 1.2), c=((.5, .5), (.5, .42)), g='peep', fx={'flicker': 0.1})),
    ('Я уже потянулся', dict(img='handle_00', z=(1.0, 1.12), g='interior', gain=1.4, fx={'handheld': 2})),
    ('Она не моргала', dict(img='peep_close', z=(1.1, 1.6), c=((.5, .45), (.5, .36)), g='peep',
                            fx={'flicker': 0.05, 'stinger': 1})),
    # ПЕРВАЯ НОЧЬ
    ('Я отступил от двери', dict(img='room_door', z=(1.3, 1.0), g='interior', gain=1.5, fx={'handheld': 4})),
    ('Соседка перестала', dict(img='peep_close', z=(1.4, 1.45), c=((.5, .38), (.5, .38)), g='peep',
                               fx={'flicker': 0.12})),
    ('— Я знаю, что ты там, — сказала', dict(img='peep_close', z=(1.5, 1.8), c=((.5, .37), (.5, .34)), g='peep',
                                             fx={'flicker': 0.12, 'glitch': 0.08})),
    ('Её голос', dict(img='room_dark', c=((.6, .68), (.6, .68)), z=(1.0, 1.05), g='interior', gain=4.2)),
    ('Но потом она ударилась', dict(img='room_dark', z=(1.08, 1.15), c=((.6, .68), (.6, .68)), g='interior',
                                    gain=4.2, fx={'hits': [1.9], 'hitamp': 14})),
    ('Один раз', dict(img='room_dark', z=(1.2, 1.2), c=((.6, .68), (.6, .68)), g='interior', gain=4.2,
                      fx={'hits': [0.05], 'hitamp': 18})),
    ('Второй', dict(img='room_dark', z=(1.3, 1.3), c=((.6, .68), (.6, .68)), g='interior', gain=4.2,
                    fx={'hits': [0.05], 'hitamp': 22})),
    ('На третий раз', dict(img='room_dark', z=(1.4, 1.45), c=((.6, .68), (.6, .68)), g='interior', gain=4.2,
                           fx={'hits': [0.6], 'hitamp': 30, 'redhit': [0.6]})),
    ('Она начала смеяться', dict(img='peep_close', z=(1.7, 1.9), c=((.5, .35), (.5, .35)), g='peep',
                                 fx={'glitch': 0.5, 'flicker': 0.2})),
    ('Я закрыл рот', dict(img='room_dark', c=((.6, .68), (.6, .68)), z=(1.1, 1.0), g='interior', gain=3.0, fx={'pulse': 0.25})),
    ('Через несколько секунд', dict(img='room_dark', c=((.6, .68), (.6, .68)), z=(1.0, 1.0), g='interior', gain=3.4)),
    ('Я посмотрел в глазок', dict(img='peep_empty', z=(1.0, 1.0), g='peep', fx={'iris': 1})),
    ('Коридор был пуст', dict(img='peep_empty', z=(1.0, 1.06), g='peep', fx={'flicker': 0.06})),
    ('Но на полу', dict(img='peep_empty', z=(1.1, 1.5), c=((.5, .6), (.5, .5)), g='peep', fx={'flicker': 0.06})),
    ('И ещё кое-что', dict(img='peep_empty', z=(1.3, 2.0), c=((.5, .7), (.5, .9)), g='peep')),
    ('Моя соседка оставила', dict(img='phone_floor', z=(1.0, 1.15), c=((.5, .5), (.55, .5)), g='interior', gain=1.5)),
    ('На экране появилось новое', dict(img='phone_floor', z=(1.2, 1.5), c=((.58, .55), (.6, .55)), g='interior',
                                       gain=1.5, fx={'buzz': [0.4]})),
    ('«НЕ ВЫХОДИ', dict(img='phone:msg1', pre='phone:clean', z=(1.0, 1.08), g='none', fx={'buzz': [0.0], 'pop': 1}, nosub=1)),
    ('Отправитель был', dict(img='phone:msg1s', pre='phone:msg1', z=(1.08, 1.14), g='none', fx={'pop': 1})),
    # НЕВОЗМОЖНОЕ СООБЩЕНИЕ
    ('Я не понимал', dict(img='phone:msg1s', z=(1.0, 1.05), g='none')),
    ('Сеть не работала', dict(img='phone:msg1s', z=(1.3, 1.45), c=((.5, .12), (.5, .1)), g='none',
                              fx={'glitch': 0.1})),
    ('Я подошёл к окну', dict(img='window_street', z=(1.0, 1.08), g='night', gain=1.3, fi=0.4)),
    ('Улица была забита', dict(img='window_street', z=(1.1, 1.25), c=((.45, .55), (.55, .5)), g='night', gain=1.3)),
    ('Между ними бродили', dict(img='window_street', z=(1.4, 1.6), c=((.5, .5), (.48, .48)), g='night', gain=1.3,
                                fx={'handheld': 2})),
    ('И вдруг все', dict(img='window_street', z=(1.6, 1.6), c=((.48, .48), (.48, .48)), g='night', gain=1.3,
                         fx={'stinger': 1})),
    ('Будто услышали', dict(img='window_street', z=(1.0, 1.0), g='night', gain=1.2, fx={'flicker': 0.05})),
    ('Затем каждый', dict(img='window_turned', z=(1.0, 1.35), c=((.5, .5), (.47, .5)), g='night', gain=1.3,
                          fx={'glitch': 0.04})),
    ('Я отшатнулся', dict(img='window_turned', z=(1.6, 1.0), c=((.47, .5), (.5, .5)), g='night', gain=1.3,
                          fx={'handheld': 18, 'whip': 1})),
    ('Телефон завибрировал', dict(img='phone:msg1s', z=(1.0, 1.04), g='none', fx={'buzz': [0.1, 0.7]})),
    ('Второе сообщение', dict(img='phone:msg1s', z=(1.04, 1.08), g='none')),
    ('«ОНИ ЗНАЮТ', dict(img='phone:msg2', pre='phone:msg1s', z=(1.0, 1.08), g='none', fx={'pop': 1, 'buzz': [0.0]}, nosub=1)),
    ('В этот момент в подъезде', dict(img='room_dark', c=((.6, .68), (.6, .68)), z=(1.0, 1.1), g='interior', gain=3.8, fx={'lighton': 0.6})),
    ('Кто-то начал', dict(img='stairwell', z=(1.0, 1.1), g='stair', gain=1.2, fx={'flicker': 0.05})),
    ('Медленно.', dict(img='stairwell', z=(1.15, 1.25), c=((.45, .55), (.45, .55)), g='stair', gain=1.2)),
    ('Шаг за шагом', dict(img='stairwell', z=(1.3, 1.45), c=((.45, .55), (.45, .55)), g='stair', gain=1.2)),
    ('Но я жил на девятом', dict(img='stairwell', z=(1.0, 1.0), g='stair', gain=1.1, fx={'whip': 1, 'stinger': 1}, fo=0.25)),
    # ОН ПОДНИМАЕТСЯ
    ('Я схватил рюкзак', dict(img='room_flashlight', z=(1.0, 1.1), c=((.5, .55), (.48, .5)), g='interior', gain=1.6,
                              fx={'handheld': 8})),
    ('Запасного выхода', dict(img='room_empty', z=(1.0, 1.08), g='interior', gain=1.5)),
    ('Только окно', dict(img='room_door', z=(1.0, 1.05), g='interior', gain=1.4)),
    ('Шаги остановились', dict(img='stairwell', z=(1.25, 1.3), g='stair', gain=0.8)),
    ('Я поднял фонарик', dict(img='room_flashlight', z=(1.15, 1.3), c=((.5, .5), (.5, .5)), g='interior', gain=1.6,
                              fx={'handheld': 5})),
    ('Тишина.', dict(img='room_flashlight', z=(1.3, 1.32), g='interior', gain=1.6, fx={'handheld': 1.5})),
    ('Потом раздался голос', dict(img='room_flashlight', z=(1.32, 1.4), g='interior', gain=1.6, fx={'handheld': 2})),
    ('— Эй.', dict(img='handle_00', z=(1.0, 1.05), g='interior', gain=1.4)),
    ('Открой.', dict(img='handle_00', z=(1.1, 1.15), g='interior', gain=1.4)),
    ('Я знаю, что ты там.', dict(img='room_flashlight', z=(1.4, 1.5), g='interior', gain=1.6, fx={'handheld': 2})),
    ('Я замер.', dict(img='room_dark', c=((.6, .68), (.6, .68)), z=(1.0, 1.02), g='interior', gain=3.4, fx={'pulse': 0.2})),
    ('Это был мой голос', dict(img='room_flashlight', z=(1.0, 1.5), g='interior', gain=1.6, fx={'stinger': 1, 'glitch': 0.06})),
    ('Точно такой же', dict(img='room_flashlight', z=(1.5, 1.6), g='interior', gain=1.6, fx={'glitch': 0.1})),
    ('За дверью кто-то', dict(img='handle_00', z=(1.15, 1.25), g='interior', gain=1.4, fx={'pulse': 0.15})),
    ('— Пожалуйста', dict(img='room_flashlight', z=(1.2, 1.25), g='interior', gain=1.5, fx={'handheld': 3})),
    ('они идут за мной', dict(img='room_flashlight', z=(1.25, 1.3), g='interior', gain=1.5, fx={'handheld': 3})),
    ('Я отступил ещё', dict(img='room_door', z=(1.25, 1.0), g='interior', gain=1.4, fx={'handheld': 4})),
    ('Потому что в этот момент', dict(img='selfie_far', z=(1.0, 1.06), g='selfie', gain=1.8,
                                      fx={'camui': 1, 'glitch': 0.08, 'buzz': [0.2]})),
    ('На экране я увидел', dict(img='selfie_far', z=(1.06, 1.12), g='selfie', gain=1.8, fx={'camui': 1})),
    ('И фигуру', dict(img='selfie_far', z=(1.15, 1.6), c=((.45, .5), (.3, .4)), g='selfie', gain=1.9,
                      fx={'camui': 1, 'stinger': 1})),
    # КЛИФФХЭНГЕР
    ('Я резко обернулся', dict(img='room_empty', z=(1.1, 1.0), g='interior', gain=1.6, fx={'whip': 1, 'handheld': 10})),
    ('Никого', dict(img='room_empty', z=(1.0, 1.04), g='interior', gain=1.5, fx={'handheld': 3})),
    ('Но когда снова', dict(img='selfie_close', z=(1.0, 1.25), c=((.5, .5), (.38, .45)), g='selfie', gain=1.9,
                            fx={'camui': 1, 'glitch': 0.12, 'stinger': 1.6})),
    ('Я бросил телефон', dict(img='room_door', z=(1.0, 1.3), g='interior', gain=1.5, fx={'handheld': 18, 'whip': 1})),
    ('Мне нужно было', dict(img='room_door', z=(1.3, 1.4), g='interior', gain=1.5, fx={'handheld': 12})),
    ('Немедленно', dict(img='room_door', z=(1.4, 1.5), g='interior', gain=1.5, fx={'handheld': 14})),
    ('И тут на экране', dict(img='phone_floor', z=(1.0, 1.3), c=((.55, .52), (.6, .55)), g='interior', gain=1.5,
                             fx={'buzz': [2.0]})),
    ('«НЕ ДОВЕРЯЙ', dict(img='phone:msg3', pre='phone:msg2', z=(1.0, 1.1), g='none',
                         fx={'pop': 1, 'glitch': 0.35, 'buzz': [0.0]}, nosub=1)),
    ('Я замер.', dict(img='black', fx={'pulse': 0.0})),
    ('Из темноты', dict(img='room_empty', z=(1.0, 1.1), g='interior', gain=0.9, fx={'pulse': 0.15})),
    ('— Наконец-то', dict(img='selfie_close', z=(1.3, 1.5), c=((.38, .45), (.36, .42)), g='selfie', gain=1.6,
                          fx={'camui': 1, 'glitch': 0.4})),
    ('Ручка входной', dict(img='handle', z=(1.0, 1.08), g='interior', gain=1.4)),
    ('А затем я услышал', dict(img='room_dark', c=((.6, .68), (.6, .68)), z=(1.0, 1.25), g='interior', gain=2.1, fx={'pulse': 0.3})),
    ('— Мы уже внутри', dict(img='selfie_close', z=(1.6, 1.9), c=((.36, .42), (.36, .42)), g='selfie', gain=1.6,
                             fx={'glitch': 0.7, 'redhit': [0.0], 'hits': [0.0], 'hitamp': 20})),
    ('Экран погас', dict(img='phone:msg3', z=(1.1, 1.1), g='none', fx={'crt_off': 0.15})),
]

# Найти раскадровку по префиксам
def build_shots():
    shots = []
    si = 0
    for k, u in enumerate(UNITS):
        assert si < len(SHOTS), f'нет кадра для фразы {k}: {u["text"]}'
        pref, spec = SHOTS[si]
        assert u['text'].startswith(pref), f'фраза {k} "{u["text"]}" ≠ "{pref}"'
        t0 = 0.0 if k == 0 else u['start'] - 0.04
        t1 = UNITS[k + 1]['start'] - 0.04 if k + 1 < len(UNITS) else AUDIO_DUR
        shots.append(dict(spec, t0=t0, t1=t1, k=k))
        si += 1
    assert si == len(SHOTS)
    shots.append(dict(img='endcard', t0=AUDIO_DUR, t1=TOTAL, k=-1))
    return shots


SHOT_LIST = build_shots()


# ------------------------------------------------------------------ грейдинг
def grade(img, g, gain=1.0):
    a = np.asarray(img.convert('RGB'), np.float32) / 255.0
    a = a * gain
    lum = (a @ np.array([0.299, 0.587, 0.114], np.float32))[..., None]
    P = {
        'cold': (0.5, (0.88, 0.97, 1.1), 1.12),
        'morning': (0.75, (1.06, 0.98, 0.88), 1.05),
        'day': (0.45, (0.92, 1.0, 1.02), 1.15),
        'bleak': (0.25, (0.9, 0.95, 1.0), 1.2),
        'fire': (0.95, (1.1, 0.95, 0.85), 1.1),
        'night': (0.7, (0.9, 0.98, 1.12), 1.1),
        'interior': (0.65, (0.95, 0.97, 1.08), 1.1),
        'peep': (0.7, (1.0, 0.98, 0.88), 1.12),
        'stair': (0.6, (1.0, 1.0, 0.9), 1.1),
        'selfie': (0.55, (0.9, 0.98, 1.12), 1.1),
        'none': (1.0, (1, 1, 1), 1.0),
    }[g]
    sat, mul, con = P
    a = lum + (a - lum) * sat
    a = a * np.array(mul, np.float32)
    a = np.clip(a, 0, None)
    a = 0.5 + (a - 0.5) * con if g != 'none' else a
    a = np.clip(a, 0, 1)
    if g != 'none':
        # bloom
        small = Image.fromarray((np.clip(a - 0.55, 0, 1) * 2 * 255).astype(np.uint8)).resize((a.shape[1] // 8, a.shape[0] // 8), Image.BILINEAR)
        small = small.filter(ImageFilter.GaussianBlur(6)).resize((a.shape[1], a.shape[0]), Image.BILINEAR)
        bl = np.asarray(small, np.float32) / 255.0
        a = 1 - (1 - a) * (1 - bl * (0.6 if g in ('fire', 'night', 'peep') else 0.35))
        # тени в синеву, мягкий toe
        a = a ** 1.08
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))


# ------------------------------------------------------------------ графика: телефон, ТВ
def rounded(draw, box, r, fill, outline=None, width=1):
    draw.rounded_rectangle(box, r, fill=fill, outline=outline, width=width)


def phone_image(variant):
    bg = Image.open(os.path.join(REN, 'phone_floor.png')).convert('RGB').resize((SW, SH))
    bg = bg.filter(ImageFilter.GaussianBlur(28))
    bg = Image.fromarray((np.asarray(bg, np.float32) * 0.35).astype(np.uint8))
    im = bg.convert('RGBA')
    ov = Image.new('RGBA', (SW, SH), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    pw, ph = 640, 1120
    x0, y0 = (SW - pw) // 2, (SH - ph) // 2 + 10
    rounded(d, (x0 - 14, y0 - 14, x0 + pw + 14, y0 + ph + 14), 78, (12, 12, 14, 255), outline=(60, 60, 66, 255), width=3)
    # экран: градиент
    scr = Image.new('RGBA', (pw, ph))
    g = np.linspace(0, 1, ph)[:, None]
    col = np.stack([10 + 18 * g, 12 + 10 * g, 26 + 30 * (1 - g)], -1)
    scr_arr = np.repeat(col, pw, 1).astype(np.uint8)
    scr = Image.fromarray(scr_arr).convert('RGBA')
    mask = Image.new('L', (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw, ph), 64, fill=255)
    ov.paste(scr, (x0, y0), mask)
    d = ImageDraw.Draw(ov)
    # вырез камеры
    rounded(d, (x0 + pw // 2 - 60, y0 + 18, x0 + pw // 2 + 60, y0 + 52), 17, (0, 0, 0, 255))
    fs = font(FONT_B, 26)
    d.text((x0 + 48, y0 + 22), '03:17', font=fs, fill=(235, 235, 240, 255))
    # нет сети
    d.text((x0 + pw - 210, y0 + 22), 'Нет сети', font=font(FONT_R, 24), fill=(235, 235, 240, 255))
    for i in range(4):
        hh = 8 + i * 5
        d.rectangle((x0 + pw - 82 + i * 9, y0 + 46 - hh, x0 + pw - 76 + i * 9, y0 + 46), fill=(120, 120, 125, 255))
    d.line((x0 + pw - 86, y0 + 50, x0 + pw - 46, y0 + 22), fill=(230, 60, 60, 255), width=3)
    # батарея
    rounded(d, (x0 + pw - 42 + 0, y0 + 26, x0 + pw - 10 + 0, y0 + 44), 4, None, outline=(230, 230, 235, 255), width=2)
    d.rectangle((x0 + pw - 39, y0 + 29, x0 + pw - 30, y0 + 41), fill=(230, 70, 60, 255))
    # часы
    big = font(FONT_R, 150)
    tw = d.textlength('03:17', font=big)
    d.text((x0 + (pw - tw) / 2, y0 + 120), '03:17', font=big, fill=(240, 240, 245, 235))
    sm = font(FONT_R, 30)
    t = 'пятница, 13 ноября'
    d.text((x0 + (pw - d.textlength(t, font=sm)) / 2, y0 + 300), t, font=sm, fill=(220, 220, 228, 220))

    def card(y, title, body, red=False, hl=False):
        rounded(d, (x0 + 26, y, x0 + pw - 26, y + 170), 30, (255, 255, 255, 46) if not red else (180, 20, 20, 120),
                outline=(255, 80, 80, 200) if hl else None, width=3)
        d.ellipse((x0 + 50, y + 26, x0 + 100, y + 76), fill=(70, 70, 80, 255) if not red else (220, 40, 40, 255))
        d.text((x0 + 66, y + 32), '?', font=font(FONT_B, 32), fill=(255, 255, 255, 255))
        d.text((x0 + 118, y + 30), title, font=font(FONT_B, 24), fill=(255, 140, 140, 255) if hl else (230, 230, 235, 255))
        d.text((x0 + pw - 120, y + 32), 'сейчас', font=font(FONT_R, 20), fill=(200, 200, 205, 200))
        lines = wrap_text(d, body, font(FONT_B, 40), pw - 110)
        for i, ln in enumerate(lines):
            d.text((x0 + 52, y + 84 + i * 44), ln, font=font(FONT_B, 40), fill=(255, 255, 255, 255))

    if variant == 'nosignal':
        rounded(d, (x0 + 40, y0 + 470, x0 + pw - 40, y0 + 690), 34, (255, 255, 255, 40))
        f1 = font(FONT_B, 54)
        t = 'НЕТ СЕТИ'
        d.text((x0 + (pw - d.textlength(t, font=f1)) / 2, y0 + 510), t, font=f1, fill=(255, 90, 90, 255))
        f2 = font(FONT_R, 28)
        t = 'Только экстренные вызовы'
        d.text((x0 + (pw - d.textlength(t, font=f2)) / 2, y0 + 600), t, font=f2, fill=(230, 230, 235, 230))
    cards = {
        'clean': [],
        'msg1': [('Неизвестный номер', 'НЕ ВЫХОДИ ИЗ КВАРТИРЫ', False, False)],
        'msg1s': [('Отправитель неизвестен', 'НЕ ВЫХОДИ ИЗ КВАРТИРЫ', False, True)],
        'msg2': [('Отправитель неизвестен', 'НЕ ВЫХОДИ ИЗ КВАРТИРЫ', False, True),
                 ('Отправитель неизвестен', 'ОНИ ЗНАЮТ, ГДЕ ТЫ', False, True)],
        'msg3': [('Отправитель неизвестен', 'НЕ ВЫХОДИ ИЗ КВАРТИРЫ', False, True),
                 ('Отправитель неизвестен', 'ОНИ ЗНАЮТ, ГДЕ ТЫ', False, True),
                 ('Отправитель неизвестен', 'НЕ ДОВЕРЯЙ СЕБЕ', True, True)],
    }.get(variant, [])
    # новые сверху
    for i, (ti, bo, red, hl) in enumerate(reversed(cards)):
        card(y0 + 400 + i * 190, ti, bo, red, hl)
    d.rounded_rectangle((x0 + pw // 2 - 90, y0 + ph - 26, x0 + pw // 2 + 90, y0 + ph - 18), 4, fill=(230, 230, 235, 200))
    im = Image.alpha_composite(im, ov)
    return im.convert('RGB')


def wrap_text(d, text, f, maxw):
    words = text.split()
    lines, cur = [], ''
    for w_ in words:
        t = (cur + ' ' + w_).strip()
        if d.textlength(t, font=f) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


TV_TEXT = {
    '0': ('ВНИМАНИЕ', 'СИСТЕМА ЭКСТРЕННОГО ОПОВЕЩЕНИЯ'),
    '1': ('НЕ ВЫХОДИТЕ', 'НА УЛИЦУ'),
    '2': ('НЕ ПРИБЛИЖАЙТЕСЬ', 'К ЗАРАЖЁННЫМ'),
    '3': ('ЕСЛИ ВАС', 'УКУСИЛИ…'),
}


def tv_image(n):
    im = Image.new('RGB', (SW, SH))
    g = np.linspace(0, 1, SH)[:, None, None]
    base = np.array([8, 14, 40], np.float32) * (1 - g) + np.array([2, 4, 12], np.float32) * g
    im = Image.fromarray(np.repeat(base, SW, 1).astype(np.uint8))
    d = ImageDraw.Draw(im)
    if n == 'static':
        return im
    d.rectangle((0, 90, SW, 210), fill=(190, 16, 20))
    f = font(FONT_B, 72)
    t = 'ЭКСТРЕННОЕ ВЕЩАНИЕ'
    d.text(((SW - d.textlength(t, font=f)) / 2, 108), t, font=f, fill=(255, 255, 255))
    # бейдж
    d.rectangle((180, 260, 530, 320), fill=(255, 255, 255))
    d.ellipse((198, 274, 230, 306), fill=(220, 20, 20))
    d.text((244, 266), 'ПРЯМОЙ ЭФИР', font=font(FONT_B, 34), fill=(20, 20, 20))
    # знак
    cx, cy = SW // 2, 470
    d.polygon([(cx, cy - 120), (cx - 140, cy + 110), (cx + 140, cy + 110)], outline=(255, 210, 40), width=12)
    d.text((cx - 18, cy - 50), '!', font=font(FONT_B, 130), fill=(255, 210, 40))
    l1, l2 = TV_TEXT[n]
    f1 = font(FONT_B, 120)
    f2 = font(FONT_B, 80)
    d.text(((SW - d.textlength(l1, font=f1)) / 2, 640), l1, font=f1, fill=(255, 255, 255))
    d.text(((SW - d.textlength(l2, font=f2)) / 2, 790), l2, font=f2, fill=(230, 230, 240))
    d.rectangle((0, SH - 170, SW, SH - 90), fill=(10, 10, 12))
    d.rectangle((0, SH - 170, 260, SH - 90), fill=(190, 16, 20))
    d.text((30, SH - 155), 'СРОЧНО', font=font(FONT_B, 44), fill=(255, 255, 255))
    return im


def endcard_image():
    im = Image.new('RGB', (W, H), (0, 0, 0))
    return im


@lru_cache(maxsize=64)
def base_image(img, g, gain):
    """Полноразмерный (SW×SH) обработанный кадр."""
    if img.startswith('phone:'):
        return phone_image(img.split(':')[1])
    if img.startswith('tv:'):
        return tv_image(img.split(':')[1])
    if img == 'black':
        return Image.new('RGB', (SW, SH))
    src = Image.open(os.path.join(REN, img + '.png')).convert('RGB')
    if src.size != (SW, SH):
        src = src.resize((SW, SH), Image.LANCZOS)
    return grade(src, g, gain)


# ------------------------------------------------------------------ оверлеи
def text_rgba(text, f, fill=(255, 255, 255), stroke=4, maxw=1500, spacing=10, align='center', shadow=True):
    tmp = ImageDraw.Draw(Image.new('RGBA', (10, 10)))
    lines = wrap_text(tmp, text, f, maxw)
    lh = f.size + spacing
    wmax = max(int(tmp.textlength(l, font=f)) for l in lines) + stroke * 2 + 20
    im = Image.new('RGBA', (wmax, lh * len(lines) + stroke * 2 + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, l in enumerate(lines):
        lw = d.textlength(l, font=f)
        x = (wmax - lw) / 2 if align == 'center' else 10
        d.text((x, 10 + i * lh), l, font=f, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))
    if shadow:
        sh = im.split()[3].filter(ImageFilter.GaussianBlur(6))
        shadow_im = Image.new('RGBA', im.size, (0, 0, 0, 0))
        shadow_im.putalpha(sh.point(lambda v: int(v * 0.7)))
        im = Image.alpha_composite(shadow_im, im)
    return im


@lru_cache(maxsize=None)
def subtitle(k):
    t = UNITS[k]['text']
    return np.asarray(text_rgba(t, font(FONT_B, 54), maxw=1600), np.float32) / 255.0


SECTIONS = []
_prev = None
for k, u in enumerate(UNITS):
    if u['section'] != _prev:
        SECTIONS.append((u['start'], u['section']))
        _prev = u['section']


@lru_cache(maxsize=None)
def section_card(i):
    name = {'КЛИФФХЭНГЕР': 'НЕ ДОВЕРЯЙ СЕБЕ'}.get(SECTIONS[i][1], SECTIONS[i][1])
    im = Image.new('RGBA', (900, 140), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 18, 8, 118), fill=(200, 20, 24, 255))
    d.text((30, 12), f'ЧАСТЬ {i + 1:02d}', font=font(FONT_M, 28), fill=(220, 40, 40, 255))
    d.text((30, 52), name, font=font(FONT_T, 52), fill=(240, 240, 240, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
    return np.asarray(im, np.float32) / 255.0


@lru_cache(maxsize=None)
def title_card():
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f1 = font(FONT_M, 40)
    t1 = 'Э П И З О Д   0 1'
    d.text(((W - d.textlength(t1, font=f1)) / 2, 380), t1, font=f1, fill=(225, 40, 40, 255))
    f2 = font(FONT_T, 120)
    t2 = 'НАЧАЛО'
    t3 = 'КАТАСТРОФЫ'
    d.text(((W - d.textlength(t2, font=f2)) / 2, 440), t2, font=f2, fill=(245, 245, 245, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
    d.text(((W - d.textlength(t3, font=f2)) / 2, 570), t3, font=f2, fill=(245, 245, 245, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
    d.rectangle((W / 2 - 220, 720, W / 2 + 220, 724), fill=(225, 40, 40, 255))
    return np.asarray(im, np.float32) / 255.0


@lru_cache(maxsize=None)
def end_card():
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f2 = font(FONT_T, 96)
    t = 'ПРОДОЛЖЕНИЕ СЛЕДУЕТ'
    d.text(((W - d.textlength(t, font=f2)) / 2, 440), t, font=f2, fill=(240, 240, 240, 255))
    f1 = font(FONT_M, 38)
    t = 'Э П И З О Д   0 2'
    d.text(((W - d.textlength(t, font=f1)) / 2, 590), t, font=f1, fill=(225, 40, 40, 255))
    return np.asarray(im, np.float32) / 255.0


@lru_cache(maxsize=None)
def camui():
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 90), fill=(0, 0, 0, 150))
    d.rectangle((0, H - 170, W, H), fill=(0, 0, 0, 150))
    d.ellipse((W / 2 - 55, H - 140, W / 2 + 55, H - 30), outline=(255, 255, 255, 255), width=8)
    d.ellipse((W / 2 - 42, H - 127, W / 2 + 42, H - 43), fill=(255, 255, 255, 230))
    for i, t in enumerate(['ВИДЕО', 'ФОТО', 'ПОРТРЕТ']):
        col = (255, 210, 60, 255) if t == 'ФОТО' else (220, 220, 220, 255)
        d.text((W / 2 - 330 + i * 250, H - 160), t, font=font(FONT_B, 22), fill=col)
    d.text((40, 28), '● ФРОНТАЛЬНАЯ КАМЕРА', font=font(FONT_B, 28), fill=(255, 255, 255, 255))
    d.text((W - 140, 28), '03:41', font=font(FONT_B, 28), fill=(255, 255, 255, 255))
    # рамка фокуса на лице
    for (x, y, dx, dy) in [(1060, 260, 1, 1), (1500, 260, -1, 1), (1060, 760, 1, -1), (1500, 760, -1, -1)]:
        d.line((x, y, x + 50 * dx, y), fill=(255, 210, 60, 230), width=4)
        d.line((x, y, x, y + 50 * dy), fill=(255, 210, 60, 230), width=4)
    return np.asarray(im, np.float32) / 255.0


def blend(arr, rgba, x, y, alpha=1.0):
    h, w = rgba.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    s = rgba[y0 - y:y1 - y, x0 - x:x1 - x]
    a = s[..., 3:4] * alpha
    arr[y0:y1, x0:x1] = arr[y0:y1, x0:x1] * (1 - a) + s[..., :3] * a


# ------------------------------------------------------------------ шумы
def hash01(*v):
    x = math.sin(sum(a * b for a, b in zip(v, (12.9898, 78.233, 37.719, 4.581)))) * 43758.5453
    return x - math.floor(x)


def smooth_noise(t, seed, freq):
    s = 0
    for i, f in enumerate((1.0, 2.3, 4.7)):
        s += math.sin(t * freq * f * 6.283 + seed * 3.1 + i * 1.7) / (i + 1)
    return s / 1.83


GRAIN = None
VIGN = None


def init_static():
    global GRAIN, VIGN
    rng = np.random.default_rng(1)
    GRAIN = [rng.normal(0, 1, (H // 2, W // 2)).astype(np.float32) for _ in range(8)]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    VIGN = np.clip(1 - 0.45 * np.clip(r - 0.45, 0, None) ** 1.6, 0, 1)[..., None].astype(np.float32)


def ease(p):
    return p * p * (3 - 2 * p)


# ------------------------------------------------------------------ рендер кадра
def find_shot(t):
    for s in SHOT_LIST:
        if s['t0'] <= t < s['t1']:
            return s
    return SHOT_LIST[-1]


def crop_view(img, z, cx, cy, ox, oy):
    vw, vh = SW / z, SH / z
    x0 = cx * SW - vw / 2 + ox
    y0 = cy * SH - vh / 2 + oy
    x0 = min(max(x0, 0), SW - vw)
    y0 = min(max(y0, 0), SH - vh)
    return img.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + vw, y0 + vh))


def render_frame(fi):
    t = fi / FPS
    s = find_shot(t)
    fx = s.get('fx', {})
    dur = s['t1'] - s['t0']
    lt = t - s['t0']
    p = min(max(lt / dur, 0), 1)
    rng = random.Random(fi * 7919)

    if s['img'] == 'endcard':
        arr = np.zeros((H, W, 3), np.float32)
        a = min(1, max(0, (t - AUDIO_DUR - 0.6) / 1.0)) * min(1, max(0, (TOTAL - t) / 0.8))
        blend(arr, end_card(), 0, 0, a)
        return finish(arr, fi, grain=0.02)

    img_name = s['img']
    if img_name == 'handle':
        idx = int(round(ease(min(1, p * 1.15)) * 9))
        img_name = f'handle_{idx:02d}'
    g = s.get('g', 'none')
    gain = s.get('gain', 1.0)
    base = base_image(img_name, g, gain)

    z0, z1 = s.get('z', (1.0, 1.0))
    (cx0, cy0), (cx1, cy1) = s.get('c', ((.5, .5), (.5, .5)))
    e = ease(p)
    z = z0 + (z1 - z0) * e
    cx = cx0 + (cx1 - cx0) * e
    cy = cy0 + (cy1 - cy0) * e
    # тряска
    ox = oy = 0.0
    hh = fx.get('handheld', 0)
    if hh:
        ox += smooth_noise(t, 1, 0.35) * hh * 2.2
        oy += smooth_noise(t, 2, 0.3) * hh * 1.6
    hitamp = fx.get('hitamp', 10)
    for ht in fx.get('hits', []):
        d = lt - ht
        if 0 <= d < 0.5:
            k = math.exp(-d * 9)
            ox += (rng.random() - 0.5) * 2 * hitamp * 2.5 * k
            oy += (rng.random() - 0.5) * 2 * hitamp * 2.5 * k
    for bt in fx.get('buzz', []):
        d = lt - bt
        if 0 <= d < 0.9 and (d % 0.45) < 0.3:
            ox += (rng.random() - 0.5) * 14
            oy += (rng.random() - 0.5) * 6
    if 'stinger' in fx and lt < 0.4:
        z *= 1 + 0.04 * fx['stinger'] * math.exp(-lt * 8)
    view = crop_view(base, z, cx, cy, ox, oy)
    arr = np.asarray(view, np.float32) / 255.0

    # всплытие уведомления
    if fx.get('pop') and 'pre' in s and lt < 0.15:
        pre = base_image(s['pre'], 'none', 1.0)
        pv = np.asarray(crop_view(pre, z, cx, cy, ox, oy), np.float32) / 255.0
        a = ease(min(1, lt / 0.15))
        arr = pv * (1 - a) + arr * a

    # смаз при резком повороте
    if fx.get('whip') and lt < 0.3:
        k = int((1 - lt / 0.3) * 60) + 1
        acc = np.zeros_like(arr)
        n = 8
        for i in range(n):
            acc += np.roll(arr, int((i - n / 2) * k / n * 3), axis=1)
        arr = acc / n

    bright = 1.0
    if 'flicker' in fx:
        f = fx['flicker']
        bright *= 1 - f * (0.5 + 0.5 * smooth_noise(t, 3, 2.0)) - (f * 3 if hash01(fi, 4) < 0.03 else 0)
    if 'firefl' in fx:
        bright *= 1 + fx['firefl'] * smooth_noise(t, 5, 3.0)
    if 'pulse' in fx:
        ph = (t * 1.2) % 1.0
        beat = math.exp(-ph * 10) + 0.6 * math.exp(-max(0, ph - 0.22) * 10) * (ph > 0.22)
        bright *= 1 - fx['pulse'] + fx['pulse'] * 0.5 * beat * 2
    if 'lighton' in fx:
        lo = fx['lighton']
        if lt < lo:
            bright *= 0.35
        elif lt < lo + 0.5:
            bright *= 0.35 + 0.65 * (1 if hash01(fi, 9) > 0.45 else 0.2)
    if 'iris' in fx:
        r = ease(min(1, lt / 0.9))
        yy, xx = np.ogrid[0:H, 0:W]
        rr = np.sqrt((xx - W / 2) ** 2 + (yy - H / 2) ** 2) / (H * 0.95)
        arr *= np.clip((r - rr) * 12, 0, 1)[..., None]
    if 'nuke' in fx:
        d = lt - fx['nuke']
        if d >= 0:
            k = math.exp(-d * 1.4)
            arr = arr + np.array([1.0, 0.85, 0.6], np.float32) * k * 1.4
    fi_d = s.get('fi', 0)
    if fi_d and lt < fi_d:
        bright *= ease(lt / fi_d)
    fo_d = s.get('fo', 0)
    if fo_d and dur - lt < fo_d:
        bright *= ease(max(0, (dur - lt) / fo_d))
    arr = arr * bright

    if 'siren' in fx:
        ph = math.sin(t * 2 * math.pi * 1.6)
        col = np.array([1, 0.05, 0.05] if ph > 0 else [0.05, 0.2, 1], np.float32)
        arr = arr + col * fx['siren'] * abs(ph) * 0.5 * (0.3 + 0.7 * VIGN_EDGE())
    if 'redpulse' in fx:
        k = (0.5 + 0.5 * math.sin(t * 6)) * fx['redpulse']
        arr = arr * (1 - k * 0.3) + np.array([0.5, 0, 0], np.float32) * k * (1 - VIGN)
    for ft in fx.get('flashes', []):
        d = lt - ft
        if 0 <= d < 0.4:
            arr = arr + np.array([1, 0.9, 0.7], np.float32) * math.exp(-d * 18) * 1.5
    for rt in fx.get('redhit', []):
        d = lt - rt
        if 0 <= d < 0.8:
            k = math.exp(-d * 5)
            arr = arr * (1 - 0.4 * k) + np.array([0.6, 0.0, 0.0], np.float32) * k * 0.6
    if fx.get('tv'):
        arr = tv_overlay(arr, t, fi)
    if fx.get('static'):
        n = np.random.default_rng(fi).random((H // 4, W // 4)).astype(np.float32)
        n = np.asarray(Image.fromarray((n * 255).astype(np.uint8)).resize((W, H), Image.NEAREST), np.float32) / 255
        mix = min(1, lt / 0.15)
        arr = arr * (1 - mix) + n[..., None] * 0.8 * mix
        if lt > dur - 0.5:
            arr *= max(0, (dur - lt) / 0.5)
    gl = fx.get('glitch', 0)
    if gl and hash01(fi, 11) < gl:
        arr = glitch(arr, fi)
    if fx.get('camui'):
        blend(arr, camui(), 0, 0, 1.0)
        if hash01(fi // 12, 13) < 0.5:
            arr[30:58, 40:62] = np.array([1, 0.1, 0.1], np.float32)
    if 'crt_off' in fx:
        arr = crt_off(arr, lt, fx['crt_off'])

    # субтитры
    k = s['k']
    if k >= 0:
        u = UNITS[k]
        if not s.get('nosub') and u['start'] - 0.05 <= t <= u['end'] + 0.25:
            st = subtitle(k)
            a = min(1, (t - u['start'] + 0.05) / 0.12, (u['end'] + 0.25 - t) / 0.12)
            bottom = 215 if fx.get('camui') else (200 if fx.get('tv') else 70)
            blend(arr, st, (W - st.shape[1]) // 2, H - bottom - st.shape[0], max(0, a))
    # заставка и титры частей
    if t < 5.0:
        a = min(1, max(0, (t - 0.6) / 0.8)) * min(1, max(0, (5.0 - t) / 0.8))
        blend(arr, title_card(), 0, -60, a)
    for i, (st0, name) in enumerate(SECTIONS):
        if i == 0:
            continue
        d = t - st0
        if 0 <= d < 3.5:
            a = min(1, d / 0.4, (3.5 - d) / 0.6)
            blend(arr, section_card(i), 70 - int((1 - min(1, d / 0.4)) * 30), 60, a)
    grain = 0.05 if g in ('interior', 'selfie', 'peep', 'stair', 'night') else 0.035
    return finish(arr, fi, grain)


_VE = None


def VIGN_EDGE():
    global _VE
    if _VE is None:
        _VE = 1 - VIGN
    return _VE


def finish(arr, fi, grain=0.035):
    arr = arr * VIGN
    gr = GRAIN[fi % 8]
    gr = np.asarray(Image.fromarray(gr).resize((W, H), Image.BILINEAR), np.float32) if False else np.repeat(np.repeat(gr, 2, 0), 2, 1)
    arr = arr + gr[..., None] * grain * (0.4 + 0.6 * (1 - np.clip(arr, 0, 1)))
    return (np.clip(arr, 0, 1) * 255).astype(np.uint8)


def glitch(arr, fi):
    rng = np.random.default_rng(fi * 31)
    out = arr.copy()
    for _ in range(rng.integers(3, 9)):
        y = rng.integers(0, H - 20)
        h = rng.integers(6, 90)
        sh = rng.integers(-120, 120)
        out[y:y + h] = np.roll(arr[y:y + h], sh, axis=1)
    sh = rng.integers(6, 18)
    out[..., 0] = np.roll(out[..., 0], sh, axis=1)
    out[..., 2] = np.roll(out[..., 2], -sh, axis=1)
    return out


def tv_overlay(arr, t, fi):
    # бегущая строка + сканлайны
    tick = ticker_strip()
    off = int((t * 260) % tick.shape[1])
    y = int((SH - 165) * H / SH)
    hh = tick.shape[0]
    x_start = int(260 * W / SW)
    seg = np.concatenate([tick, tick], 1)[:, off:off + W - x_start]
    blend(arr, seg, x_start, y, 1.0)
    arr = arr * SCAN()
    if hash01(fi, 21) < 0.08:
        arr = glitch(arr, fi)
    return arr


_SCAN = None


def SCAN():
    global _SCAN
    if _SCAN is None:
        s = np.ones((H, 1, 1), np.float32)
        s[::3] = 0.72
        _SCAN = s
    return _SCAN


@lru_cache(maxsize=None)
def ticker_strip():
    t = '   НЕ ВЫХОДИТЕ НА УЛИЦУ  •  ЗАПРИТЕ ДВЕРИ И ОКНА  •  НЕ ПРИБЛИЖАЙТЕСЬ К ЗАРАЖЁННЫМ  •  ЖДИТЕ ДАЛЬНЕЙШИХ УКАЗАНИЙ  •'
    f = font(FONT_B, 40)
    wdt = int(ImageDraw.Draw(Image.new('RGB', (1, 1))).textlength(t, font=f)) + 10
    im = Image.new('RGBA', (wdt, 66), (10, 10, 12, 255))
    ImageDraw.Draw(im).text((0, 8), t, font=f, fill=(255, 255, 255, 255))
    return np.asarray(im, np.float32) / 255.0


def crt_off(arr, lt, start):
    if lt < start:
        return arr
    d = lt - start
    if d < 0.18:
        k = 1 - d / 0.18
        hgt = max(2, int(H * k * k))
        img = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8)).resize((W, hgt), Image.BILINEAR)
        out = np.zeros_like(arr)
        y0 = (H - hgt) // 2
        out[y0:y0 + hgt] = np.asarray(img, np.float32) / 255.0 * (1 + 1.5 * (1 - k))
        return out
    if d < 0.4:
        k = 1 - (d - 0.18) / 0.22
        out = np.zeros_like(arr)
        wdt = max(2, int(W * k * k))
        out[H // 2 - 2:H // 2 + 2, (W - wdt) // 2:(W + wdt) // 2] = 1.0
        return out
    if d < 0.6:
        out = np.zeros_like(arr)
        r = int(6 * (1 - (d - 0.4) / 0.2))
        out[H // 2 - r:H // 2 + r, W // 2 - r:W // 2 + r] = 1.0
        return out
    return np.zeros_like(arr)


# ------------------------------------------------------------------ запуск
def worker(args):
    a, b, path, preview = args
    init_static()
    size = f'{W}x{H}'
    vf = ['-vf', 'scale=960:540'] if preview else []
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', size, '-r', str(FPS),
           '-i', '-', *vf, '-c:v', 'libx264', '-preset', 'medium', '-crf', '19', '-pix_fmt', 'yuv420p',
           '-tune', 'grain', path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fi in range(a, b):
        p.stdin.write(render_frame(fi).tobytes())
    p.stdin.close()
    p.wait()
    return path


if __name__ == '__main__':
    import multiprocessing as mp
    preview = '--preview' in sys.argv
    t_from = float(sys.argv[sys.argv.index('--from') + 1]) if '--from' in sys.argv else 0
    t_to = float(sys.argv[sys.argv.index('--to') + 1]) if '--to' in sys.argv else TOTAL
    if '--still' in sys.argv:
        init_static()
        for tt in sys.argv[sys.argv.index('--still') + 1].split(','):
            Image.fromarray(render_frame(int(float(tt) * FPS))).save(os.path.join(BUILD, f'still_{float(tt):07.2f}.png'))
        sys.exit()
    f0, f1 = int(t_from * FPS), int(math.ceil(t_to * FPS))
    nw = int(os.environ.get('WORKERS', os.cpu_count() or 4))
    nchunks = nw * 3
    step = math.ceil((f1 - f0) / nchunks)
    jobs = []
    for i in range(nchunks):
        a = f0 + i * step
        b = min(f1, a + step)
        if a >= b:
            break
        jobs.append((a, b, os.path.join(BUILD, f'chunk_{i:03d}.mp4'), preview))
    with mp.Pool(nw) as pool:
        for r in pool.imap(worker, jobs):
            print('done', r, flush=True)
    with open(os.path.join(BUILD, 'chunks.txt'), 'w') as f:
        for j in jobs:
            f.write(f"file '{j[2]}'\n")
    out = os.path.join(BUILD, 'video_preview.mp4' if preview else 'video.mp4')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', os.path.join(BUILD, 'chunks.txt'),
                    '-c', 'copy', out], check=True)
    print('video', out)
