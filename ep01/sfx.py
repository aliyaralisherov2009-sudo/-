"""Звуковой дизайн: синтез эффектов по таймлайну → build/sfx.wav (48 кГц, стерео)."""
import json, os, math
import numpy as np
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
TL = json.load(open(os.path.join(HERE, 'timeline.json'), encoding='utf-8'))
U = TL['units']
SR = 48000
TOTAL = TL['duration'] + 5.0
N = int(TOTAL * SR)
L = np.zeros(N, np.float32)
R = np.zeros(N, np.float32)
rng = np.random.default_rng(7)


def find(prefix, nth=0):
    hits = [u for u in U if u['text'].startswith(prefix)]
    return hits[nth]


def env(n, a=0.005, d=0.3):
    t = np.arange(n) / SR
    return np.minimum(1, t / max(a, 1e-4)) * np.exp(-t / d)


def lowpass(x, fc):
    # однополюсный ФНЧ, дважды
    a = math.exp(-2 * math.pi * fc / SR)
    y = np.empty_like(x)
    for _ in range(2):
        acc = 0.0
        out = np.empty_like(x)
        # векторизовано через lfilter-подобный трюк недоступен без scipy — используем cumsum-приближение
        out = _iir(x, a)
        x = out
    return x


def _iir(x, a):
    try:
        from scipy.signal import lfilter
        return lfilter([1 - a], [1, -a], x).astype(np.float32)
    except Exception:
        y = np.empty_like(x)
        acc = 0.0
        b = 1 - a
        for i in range(len(x)):
            acc = b * x[i] + a * acc
            y[i] = acc
        return y


def highpass(x, fc):
    return x - lowpass(x, fc)


def add(sig, t, gain=1.0, pan=0.0):
    i = int(t * SR)
    if i >= N:
        return
    sig = sig[:N - i] * gain
    L[i:i + len(sig)] += sig * math.sqrt(0.5 * (1 - pan))
    R[i:i + len(sig)] += sig * math.sqrt(0.5 * (1 + pan))


def noise(n):
    return rng.standard_normal(n).astype(np.float32)


def tone(f, dur, f2=None):
    n = int(dur * SR)
    t = np.arange(n) / SR
    if f2 is None:
        return np.sin(2 * np.pi * f * t).astype(np.float32)
    ph = 2 * np.pi * np.cumsum(np.linspace(f, f2, n)) / SR
    return np.sin(ph).astype(np.float32)


# ---------------------------------------------------------------- звуки
def boom(dur=2.5, f=45):
    n = int(dur * SR)
    s = tone(f, dur, f * 0.6) * env(n, 0.01, dur / 3) + lowpass(noise(n), 200) * env(n, 0.005, dur / 4) * 2
    return s


def knock():
    n = int(0.25 * SR)
    s = lowpass(noise(n), 900) * env(n, 0.001, 0.03) * 3 + tone(140, 0.25) * env(n, 0.001, 0.06)
    return s


def bang():
    n = int(0.6 * SR)
    s = lowpass(noise(n), 400) * env(n, 0.001, 0.08) * 4 + tone(70, 0.6, 50) * env(n, 0.001, 0.15) * 1.5
    return s


def crunch():
    n = int(0.5 * SR)
    s = highpass(noise(n), 1500) * env(n, 0.001, 0.12) * (rng.random(n) > 0.6) * 2
    return s.astype(np.float32) + bang() [:n] * 0.6


def gunshot():
    n = int(1.2 * SR)
    s = noise(n) * env(n, 0.0005, 0.04) * 2 + lowpass(noise(n), 300) * env(n, 0.001, 0.35) * 2.5
    return s


def heartbeat():
    n = int(0.5 * SR)
    b = tone(52, 0.5, 40) * env(n, 0.004, 0.07) * 1.4
    out = np.zeros(int(0.8 * SR), np.float32)
    out[:n] += b
    k = int(0.22 * SR)
    out[k:k + n] += b * 0.7
    return lowpass(out, 150)


def buzz(dur=0.35):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.sign(np.sin(2 * np.pi * 160 * t)).astype(np.float32)
    s = lowpass(s, 600) * np.minimum(1, t / 0.01) * np.minimum(1, (dur - t) / 0.02)
    return s


def siren(dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 750 + 350 * np.sin(2 * np.pi * 0.35 * t)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR).astype(np.float32)
    s += 0.3 * np.sin(4 * np.pi * np.cumsum(f) / SR).astype(np.float32)
    fade = np.minimum(1, t / 1.5) * np.minimum(1, (dur - t) / 1.5)
    return lowpass(s, 2500) * fade


def crackle(dur):
    n = int(dur * SR)
    s = np.zeros(n, np.float32)
    idx = rng.integers(0, n, int(dur * 60))
    s[idx] = rng.standard_normal(len(idx)) * 1.5
    s = highpass(lowpass(s, 4000), 300)
    s += lowpass(noise(n), 250) * 0.4
    t = np.arange(n) / SR
    return s * np.minimum(1, t / 1.0) * np.minimum(1, (dur - t) / 1.0)


def static(dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    return highpass(noise(n), 800) * np.minimum(1, t / 0.02) * np.minimum(1, (dur - t) / 0.1)


def eas_tone(dur=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = (np.sin(2 * np.pi * 853 * t) + np.sin(2 * np.pi * 960 * t)).astype(np.float32) * 0.5
    return s * np.minimum(1, t / 0.02) * np.minimum(1, (dur - t) / 0.05)


def step():
    n = int(0.35 * SR)
    return lowpass(noise(n), 250) * env(n, 0.002, 0.05) * 3 + tone(60, 0.35) * env(n, 0.002, 0.08)


def whoosh(dur=0.5):
    n = int(dur * SR)
    t = np.arange(n) / SR
    e = np.sin(np.pi * t / dur) ** 2
    return lowpass(noise(n), 1500) * e * 1.5


def glitch_burst(dur=0.3):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.sign(np.sin(2 * np.pi * rng.uniform(200, 900) * t)) * (rng.random(n) > 0.3)
    s = s.astype(np.float32) * 0.6 + highpass(noise(n), 2000) * 0.5
    gate = (np.floor(t * 40) % 2).astype(np.float32)
    return s * gate * np.minimum(1, (dur - t) / 0.03)


def creak(dur=2.2):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 380 + 140 * np.sin(2 * np.pi * 0.8 * t) + 40 * np.sin(2 * np.pi * 13 * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sign(np.sin(ph)) * (0.5 + 0.5 * np.sin(2 * np.pi * 23 * t))
    s = lowpass(s.astype(np.float32), 1800)
    return s * np.sin(np.pi * t / dur)


def click():
    n = int(0.05 * SR)
    return highpass(noise(n), 2000) * env(n, 0.0005, 0.006) * 2


def hum(dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = (np.sin(2 * np.pi * 100 * t) + 0.5 * np.sin(2 * np.pi * 200 * t) + 0.2 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    return s * np.minimum(1, t / 0.3) * np.minimum(1, (dur - t) / 0.5)


def riser(dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = tone(60, dur, 180) * (t / dur) ** 2 + highpass(noise(n), 3000) * (t / dur) ** 3 * 0.4
    return s


# ---------------------------------------------------------------- фоновый дрон
def drone():
    t = np.arange(N) / SR
    s = (np.sin(2 * np.pi * 41 * t) + np.sin(2 * np.pi * 41.6 * t) + 0.5 * np.sin(2 * np.pi * 61.5 * t)).astype(np.float32)
    s += lowpass(noise(N), 120) * 1.5
    s *= 0.6 + 0.4 * np.sin(2 * np.pi * 0.05 * t).astype(np.float32)
    # уровень по частям
    lvl = np.full(N, 0.10, np.float32)
    marks = [(0, 0.08), (find('К вечеру')['start'], 0.12), (find('А потом в дверь')['start'], 0.15),
             (find('Я отступил от двери')['start'], 0.17), (find('Я не понимал')['start'], 0.16),
             (find('Я схватил рюкзак')['start'], 0.2), (find('Я резко обернулся')['start'], 0.24)]
    for (a, v), (b, _) in zip(marks, marks[1:] + [(TOTAL, 0)]):
        lvl[int(a * SR):int(b * SR)] = v
    # провалы в тишину
    for pref in ('Тишина.', 'И вдруг все'):
        u = find(pref)
        lvl[int(u['start'] * SR):int(u['end'] * SR)] *= 0.15
    end = find('Экран погас')
    lvl[int((end['start'] + 0.15) * SR):] = 0
    k = int(0.3 * SR)
    c = np.concatenate([[0], np.cumsum(lvl, dtype=np.float64)])
    idx = np.clip(np.arange(N) + k // 2, 0, N); idx0 = np.clip(np.arange(N) - k // 2, 0, N)
    lvl = ((c[idx] - c[idx0]) / np.maximum(idx - idx0, 1)).astype(np.float32)
    return s * lvl


d = drone()
L += d * 0.7
R += d * 0.7

# ---------------------------------------------------------------- события
u = find('Или ядерного'); add(boom(3.0, 38), u['start'] + 0.35, 0.5)
u = find('Сначала перестали'); add(glitch_burst(0.25), u['start'] + 0.1, 0.15)
u = find('Потом на улицах'); add(siren(4.0), u['start'], 0.04, pan=-0.6)
u = find('А через несколько'); add(crackle(3.5), u['start'], 0.15)
u = find('Полицейский выстрелил')
for o, pn in zip((1.15, 1.55, 1.95), (-0.2, 0.0, 0.2)):
    add(gunshot(), u['start'] + o, 0.55, pan=pn)
u = find('Он всё равно'); add(boom(2.0, 50), u['start'], 0.35)
s0 = find('К вечеру')['start']; s1 = find('Когда добрался')['start']
add(siren(s1 - s0 + 1), s0 - 0.5, 0.09, pan=0.5)
add(siren(s1 - s0 + 1) * 0.7, s0 + 1.3, 0.06, pan=-0.6)
add(crackle(s1 - s0 + 1), s0, 0.35)
u = find('Я бежал домой')
for i in range(int((u['end'] - u['start']) / 0.32)):
    add(step(), u['start'] + i * 0.32, 0.25, pan=0.1 * (-1) ** i)
u = find('Когда добрался'); add(bang(), u['end'] - 0.3, 0.3)
u = find('На телевизоре'); add(eas_tone(1.2), u['start'] + 0.2, 0.07)
add(hum(find('Трансляция')['start'] - u['start']), u['start'], 0.03)
u = find('Трансляция'); add(static(1.4), u['start'], 0.12); add(click(), u['end'] + 0.1, 0.5)
u = find('А потом в дверь')
for o in (0.9, 1.3, 1.7):
    add(knock(), u['start'] + o, 0.5)
u = find('Она не моргала'); add(boom(2.0, 55), u['start'], 0.45)
u = find('Но потом она ударилась'); add(bang(), u['start'] + 1.9, 0.6)
add(bang(), find('Один раз')['start'] + 0.05, 0.65)
add(bang(), find('Второй')['start'] + 0.05, 0.7)
u = find('На третий раз'); add(bang(), u['start'] + 0.6, 0.7); add(crunch(), u['start'] + 0.62, 0.5)
u = find('Она начала смеяться'); add(glitch_burst(0.5), u['start'] + 0.2, 0.12)
for pref in ('Я закрыл рот', 'Через несколько секунд'):
    u = find(pref)
    tt = u['start']
    while tt < u['end'] + 0.3:
        add(heartbeat(), tt, 0.5); tt += 0.83
u = find('На экране появилось новое'); add(buzz(), u['start'] + 0.4, 0.25); add(buzz(), u['start'] + 0.85, 0.25)
u = find('«НЕ ВЫХОДИ'); add(boom(1.5, 60), u['start'], 0.25)
u = find('И вдруг все'); add(boom(2.5, 40), u['start'], 0.45)
u = find('Затем каждый'); add(riser(u['end'] - u['start']), u['start'], 0.25)
u = find('Я отшатнулся'); add(whoosh(0.5), u['start'], 0.35)
u = find('Телефон завибрировал'); add(buzz(), u['start'] + 0.1, 0.3); add(buzz(), u['start'] + 0.7, 0.3)
u = find('«ОНИ ЗНАЮТ'); add(boom(1.8, 50), u['start'], 0.35)
u = find('В этот момент в подъезде'); add(click(), u['start'] + 0.6, 0.6); add(hum(3.0), u['start'] + 0.6, 0.03)
s0 = find('Кто-то начал')['start']; s1 = find('Но я жил на девятом')['end']
tt = s0 + 0.4
while tt < s1:
    add(step(), tt, 0.35, pan=-0.3); tt += 0.95
u = find('Но я жил на девятом'); add(boom(2.0, 45), u['end'] - 0.2, 0.4)
u = find('Я схватил рюкзак'); add(whoosh(0.4), u['start'], 0.2)
u = find('Шаги остановились')
tt = u['start'] - 0.9
for i in range(3):
    add(step(), tt + i * 0.95, 0.4 - i * 0.05, pan=-0.2)
u = find('Я поднял фонарик'); add(click(), u['start'] + 0.5, 0.6)
u = find('Это был мой голос'); add(boom(2.0, 48), u['start'], 0.45)
for pref in ('Я замер.',):
    u = find(pref, 0)
    tt = u['start']
    while tt < u['end'] + 0.6:
        add(heartbeat(), tt, 0.55); tt += 0.75
u = find('За дверью кто-то'); tt = u['start']
while tt < find('Я отступил ещё')['start']:
    add(heartbeat(), tt, 0.5); tt += 0.7
u = find('Потому что в этот момент'); add(click(), u['start'] + 0.2, 0.4); add(glitch_burst(0.2), u['start'] + 0.25, 0.1)
u = find('И фигуру'); add(boom(2.5, 42), u['start'], 0.55)
u = find('Я резко обернулся'); add(whoosh(0.45), u['start'], 0.5)
u = find('Но когда снова'); add(boom(2.0, 52), u['start'] + 1.0, 0.5)
u = find('Я бросил телефон'); add(bang(), u['start'] + 0.6, 0.3)
tt = u['start'] + 0.9
while tt < find('И тут на экране')['start']:
    add(step(), tt, 0.3); tt += 0.33
u = find('И тут на экране'); add(buzz(), u['start'] + 2.0, 0.3); add(buzz(), u['start'] + 2.45, 0.3)
u = find('«НЕ ДОВЕРЯЙ'); add(glitch_burst(0.6), u['start'], 0.18); add(boom(2.0, 44), u['start'], 0.5)
u = find('Я замер.', 1); tt = u['start']
while tt < find('Ручка входной')['start']:
    add(heartbeat(), tt, 0.6); tt += 0.62
u = find('— Наконец-то'); add(glitch_burst(0.4), u['start'], 0.15)
u = find('Ручка входной'); add(creak(u['end'] - u['start'] + 0.3), u['start'], 0.08); add(click(), u['end'] - 0.1, 0.6)
u = find('А затем я услышал'); add(riser(u['end'] - u['start'] + 0.3), u['start'], 0.35)
tt = u['start']
while tt < u['end']:
    add(heartbeat(), tt, 0.65); tt += 0.5
u = find('— Мы уже внутри'); add(boom(4.0, 36), u['start'], 0.8); add(glitch_burst(0.7), u['start'], 0.2)
u = find('Экран погас'); add(click(), u['start'] + 0.15, 0.7); add(static(0.15), u['start'] + 0.15, 0.2)
# финальный удар на титре
add(boom(4.0, 34), TL['duration'] + 0.6, 0.5)

# ---------------------------------------------------------------- запись
st = np.stack([L, R], 1)
peak = np.abs(st).max()
st = st / max(peak, 1e-6) * 0.9
os.makedirs(os.path.join(HERE, 'build'), exist_ok=True)
with wave.open(os.path.join(HERE, 'build', 'sfx.wav'), 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((st * 32767).astype(np.int16).tobytes())
print('sfx ok, peak before norm', peak)
