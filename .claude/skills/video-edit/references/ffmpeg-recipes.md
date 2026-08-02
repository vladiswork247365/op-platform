# ffmpeg: рецепты монтажа

Все команды предполагают `-hide_banner -loglevel error` и лог в `work/ffmpeg.log`.

## Переходы

### Кросс-фейд / вайп / слайд (xfade)
`offset` = момент начала перехода в первом клипе (сек), `duration` = длительность.
```bash
ffmpeg -i a.mp4 -i b.mp4 -filter_complex \
"[0:v][1:v]xfade=transition=fade:duration=0.4:offset=3.6[v]; \
 [0:a][1:a]acrossfade=d=0.4[a]" -map "[v]" -map "[a]" -c:v libx264 -crf 18 out.mp4
```
Полезные `transition`: `fade`, `wipeleft`, `slideup`, `circleopen`, `dissolve`,
`pixelize`, `radial`, `smoothleft`, `hlslice`, `zoomin`.

### Whip pan (резкий смаз-поворот)
```bash
ffmpeg -i a.mp4 -i b.mp4 -filter_complex \
"[0:v]crop=iw:ih,boxblur=luma_radius=min(h\,w)/40:luma_power=1:enable='gte(t,3.7)'[a0]; \
 [1:v]boxblur=luma_radius=min(h\,w)/40:luma_power=1:enable='lte(t,0.2)'[b0]; \
 [a0][b0]xfade=transition=slideleft:duration=0.18:offset=3.75[v]" \
 -map "[v]" -c:v libx264 -crf 18 out.mp4
```
Работает, когда в конце первого клипа и начале второго есть движение камеры в одну сторону.

### Speed ramp (разгон перед склейкой)
```bash
ffmpeg -i in.mp4 -filter_complex \
"[0:v]setpts='if(gt(T,3),0.35*PTS+1.95*TB,PTS)'[v];[0:a]atempo=1.0[a]" \
 -map "[v]" -map "[a]" -c:v libx264 -crf 18 out.mp4
```
Проще и надёжнее: нарезать участок отдельно, ускорить его, склеить.
```bash
ffmpeg -i part.mp4 -filter:v "setpts=0.4*PTS" -filter:a "atempo=2.5" part_fast.mp4
```

### Glitch / RGB-сдвиг на 3 кадра
```bash
ffmpeg -i in.mp4 -vf "chromashift=cbh=6:crh=-6:enable='between(t,3.70,3.82)', \
noise=alls=28:allf=t+u:enable='between(t,3.70,3.82)'" -c:a copy out.mp4
```

### Вспышка-переход (flash cut)
```bash
ffmpeg -i in.mp4 -vf "eq=brightness=0.55:enable='between(t,3.76,3.84)'" -c:a copy out.mp4
```

### Zoom-punch на слове (акцент)
```bash
ffmpeg -i in.mp4 -vf \
"scale=2*iw:-1,crop=iw/2:ih/2:(iw-ow)/2:(ih-oh)/2,scale=1080:1920:enable='between(t,5.0,5.4)'" \
 -c:a copy out.mp4
```
Надёжнее — `zoompan` на вырезанном куске, затем склейка.

## Ритм и динамика

### Лёгкий постоянный зум (убирает статичность говорящей головы)
```bash
ffmpeg -i in.mp4 -vf "zoompan=z='min(zoom+0.0006,1.10)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30" -c:a copy out.mp4
```

### Стабилизация (двухпроходная, vid.stab)
```bash
ffmpeg -i in.mp4 -vf vidstabdetect=shakiness=6:accuracy=15 -f null -
ffmpeg -i in.mp4 -vf vidstabtransform=smoothing=20:zoom=2,unsharp=5:5:0.6 -c:a copy out.mp4
```

### Замедление с интерполяцией (плавные 120 fps из 30)
```bash
ffmpeg -i in.mp4 -vf "minterpolate=fps=120:mi_mode=mci:mc_mode=aobmc:vsr_mode=obmc,setpts=4*PTS" -an out.mp4
```

## Вертикаль 9:16

### Кроп из горизонтали по центру
```bash
ffmpeg -i in.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920,setsar=1" -c:a copy out.mp4
```

### Размытый фон + вписанное видео (когда кроп режет важное)
```bash
ffmpeg -i in.mp4 -filter_complex \
"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=28[bg]; \
 [0:v]scale=1080:-1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v]" -map "[v]" -map 0:a -c:a copy out.mp4
```

## Плашки и текст на экране

```bash
ffmpeg -i in.mp4 -vf "drawtext=fontfile=/path/Montserrat-Bold.ttf:text='ДЕНЬ 14':\
fontsize=84:fontcolor=white:borderw=6:bordercolor=black@0.85:x=(w-tw)/2:y=260:\
enable='between(t,0.3,2.0)'" -c:a copy out.mp4
```
Для кириллицы шрифт обязан содержать кириллицу (Montserrat, Inter, Unbounded — да; Bebas Neue — нет).

## b-roll поверх основного плана (picture-in-picture / вставка)

```bash
ffmpeg -i main.mp4 -i broll.mp4 -filter_complex \
"[1:v]scale=1080:1920,setpts=PTS-STARTPTS+12/TB[b];[0:v][b]overlay=0:0:enable='between(t,12,15)'[v]" \
 -map "[v]" -map 0:a -c:v libx264 -crf 18 -c:a copy out.mp4
```
Голос основного плана продолжает идти — классическая вставка «говорю за кадром».

## Обложка

```bash
ffmpeg -ss 00:00:01.2 -i final.mp4 -frames:v 1 -q:v 2 out/cover.jpg
```

## Финальный экспорт под площадку

```bash
ffmpeg -i in.mp4 -c:v libx264 -profile:v high -level 4.1 -crf 20 -preset slow \
  -pix_fmt yuv420p -r 30 -vf "scale=1080:1920,setsar=1" \
  -c:a aac -b:a 192k -ar 48000 -movflags +faststart out/final.mp4
```
`+faststart` обязателен: без него ролик долго стартует при загрузке.

## Диагностика

| Симптом | Причина | Решение |
|---|---|---|
| Чёрные кадры на склейке | разный fps у кусков | привести к общему `-r 30` при нарезке |
| Рассинхрон звука | concat разноформатных файлов | перекодировать при нарезке, не `-c copy` |
| Не читается на телефоне | не `yuv420p` | добавить `-pix_fmt yuv420p` |
| Квадратики вместо кириллицы | шрифт без кириллицы | сменить шрифт |
| Файл огромный | низкий crf / высокий bitrate | `-crf 20…23`, `-preset slow` |
