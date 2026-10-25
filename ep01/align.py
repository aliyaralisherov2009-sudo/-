"""Привязка фраз сценария к озвучке: DP по паузам (без ASR)."""
import subprocess, re, json, numpy as np
SR = 16000
raw = subprocess.run(['ffmpeg','-v','quiet','-i','vo.mp3','-ac','1','-ar',str(SR),'-f','s16le','-'],
                     capture_output=True).stdout
x = np.frombuffer(raw, np.int16).astype(float) / 32768
hop = 160  # 10 ms
e = np.sqrt((x[:len(x)//hop*hop].reshape(-1, hop)**2).mean(1))
db = 20*np.log10(e + 1e-9)
db = np.convolve(db, np.ones(5)/5, 'same')
sil = db < -38
T = len(db) * hop / SR

# паузы >= 0.12 с
pauses = []
i = 0
while i < len(sil):
    if sil[i]:
        j = i
        while j < len(sil) and sil[j]: j += 1
        if (j - i) * 0.01 >= 0.12: pauses.append((i*0.01, j*0.01))
        i = j
    else: i += 1
speech_start = pauses[0][1] if pauses and pauses[0][0] < 0.05 else 0.0
if pauses and pauses[0][0] < 0.05: pauses = pauses[1:]
speech_end = pauses[-1][0] if pauses and pauses[-1][1] > T - 0.05 else T
if pauses and pauses[-1][1] > T - 0.05: pauses = pauses[:-1]

# фразы
units = []; section = None
for line in open('script.txt', encoding='utf-8'):
    line = line.strip()
    if not line: continue
    if line.startswith('#'): section = line[1:].strip(); new_sec = True; continue
    parts = re.findall(r'[^.!?…»]+(?:[.!?…]+»?|»|$)', line)
    parts = [p.strip() for p in parts if p.strip()]
    # склеиваем слишком короткие хвосты (типа «— сказала она.»)
    merged = []
    for p in parts:
        if merged and (len(p) < 4 or p.startswith('—') and not merged[-1].endswith(('.', '?', '!'))):
            merged[-1] += ' ' + p
        else: merged.append(p)
    for k, p in enumerate(merged):
        units.append(dict(text=p, section=section, line_end=(k == len(merged)-1)))

N = len(units)
w = np.array([len(u['text']) + 4 for u in units], float)
P = [(speech_start, speech_start)] + pauses + [(speech_end, speech_end)]
M = len(P)
plen = np.array([b-a for a, b in P])
top = np.sort(plen[1:-1])[::-1][:N-1]
rate = (speech_end - speech_start - top.sum()) / w.sum()
cw = np.concatenate([[0], np.cumsum(w)])
INF = 1e18
D = np.full((N+1, M), INF); B = {}
D[0][0] = 0
for k in range(N):
    for j in range(M):
        if D[k][j] >= INF: continue
        for g in (1, 2, 3):
            if k+g > N: break
            W = cw[k+g] - cw[k]; exp = W*rate
            for j2 in range(j+1, M):
                d = P[j2][0] - P[j][1]
                if d > exp*2.2 + 3: break
                if k+g == N and j2 != M-1: continue
                if k+g < N and j2 == M-1: continue
                c = ((d-exp)/(0.22*exp+0.35))**2 - (0 if j2 == M-1 else min(plen[j2], 0.7)*3) + (g-1)*6
                if D[k][j] + c < D[k+g][j2]:
                    D[k+g][j2] = D[k][j] + c; B[(k+g, j2)] = (k, j, g)
k, j = N, M-1
spans = []
while k > 0:
    pk, pj, g = B[(k, j)]
    spans.append((pk, g, P[pj][1], P[j][0])); k, j = pk, pj
spans.reverse()
for pk, g, a, b in spans:
    W = cw[pk+g] - cw[pk]; t = a
    for u in range(pk, pk+g):
        dt = (b-a) * w[u] / W
        units[u]['start'] = round(float(t), 2); units[u]['end'] = round(float(t+dt), 2)
        units[u]['snapped'] = (u == pk+g-1); t += dt
json.dump(dict(duration=T, units=units), open('timeline.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for u in units: print(f"{u['start']:7.2f} {u['end']:7.2f} {'*' if u['snapped'] else ' '} {u['text'][:60]}")
print('pauses', M, 'units', N, 'T', T)
