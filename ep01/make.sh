#!/usr/bin/env bash
# Полная сборка эпизода 01: рендер 3D → разметка → монтаж → звук → сведение
set -euo pipefail
cd "$(dirname "$0")"
[ -f renders/handle_09.png ] || python3 blender_scenes.py      # Blender (bpy): ~40 мин на 4 ядрах
python3 align.py > /dev/null                                    # привязка фраз к озвучке
python3 compose.py                                              # видеоряд → build/video.mp4
python3 sfx.py                                                  # звуковой дизайн → build/sfx.wav
D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 build/video.mp4)
ffmpeg -v error -y -i build/video.mp4 -c:v libx264 -preset slow -b:v 5M -pass 1 -passlogfile build/x264 -an -f null /dev/null
ffmpeg -v error -y -i build/video.mp4 -i vo.mp3 -i build/sfx.wav -filter_complex \
 "[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0,apad,asplit=2[vo][sc];\
  [2:a]volume=0.6[fx];[fx][sc]sidechaincompress=threshold=0.04:ratio=5:attack=15:release=350[fxd];\
  [vo][fxd]amix=inputs=2:normalize=0:duration=longest,loudnorm=I=-14:TP=-1.5:LRA=11[a]" \
 -map 0:v -map "[a]" -t "$D" -c:v libx264 -preset slow -b:v 5M -pass 2 -passlogfile build/x264 -pix_fmt yuv420p -c:a aac -b:a 192k -ar 48000 -movflags +faststart ep01.mp4
echo "готово: ep01/ep01.mp4"
