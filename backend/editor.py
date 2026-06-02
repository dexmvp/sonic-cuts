import os
import math
import numpy as np

from PIL import Image, ImageEnhance
from moviepy import (
    VideoFileClip,
    AudioFileClip,
    CompositeVideoClip,
    concatenate_videoclips,
    ColorClip
)


print("EDITOR VERSION: STABLE CINEMATIC MUSIC EDIT V7")


EDIT_OUTPUT = "clips/edit.mp4"

EDIT_WIDTH = 1080
EDIT_HEIGHT = 1920

# Вертикальный Shorts, но весь монитор 16:9 виден целиком.
# Без blur-фона, без белых/чёрных full-screen flash.
MONITOR_WIDTH = 1080

MIN_SCENE_DURATION = 0.70
MAX_SCENE_DURATION = 1.80
MAX_SCENES = 32


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def cinematic_color(frame):
    image = Image.fromarray(frame)

    image = ImageEnhance.Brightness(image).enhance(0.93)
    image = ImageEnhance.Contrast(image).enhance(1.18)
    image = ImageEnhance.Color(image).enhance(1.10)
    image = ImageEnhance.Sharpness(image).enhance(1.06)

    return np.array(image)


def make_dark_background(duration):
    return ColorClip(
        size=(EDIT_WIDTH, EDIT_HEIGHT),
        color=(4, 5, 10),
        duration=duration
    )


def smooth_zoom(t, duration, intensity="medium"):
    if duration <= 0:
        return 1.0

    progress = clamp(t / duration, 0, 1)

    if intensity == "high":
        amount = 0.055
    elif intensity == "low":
        amount = 0.020
    else:
        amount = 0.035

    # Без резких ударов, чтобы не ломать кадр.
    return 1.0 + amount * progress


def prepare_monitor_clip(piece, intensity="medium"):
    piece = piece.image_transform(cinematic_color)

    monitor = piece.resized(width=MONITOR_WIDTH)
    duration = piece.duration

    try:
        monitor = monitor.resized(lambda t: smooth_zoom(t, duration, intensity))
    except Exception:
        pass

    # После resize(lambda) размеры могут немного меняться,
    # поэтому центрируем через ("center", "center").
    monitor = monitor.with_position(("center", "center"))

    return monitor


def create_scene(source_clip, start, end, intensity="medium"):
    piece = source_clip.subclipped(start, end)
    duration = piece.duration

    background = make_dark_background(duration)
    monitor = prepare_monitor_clip(piece, intensity)

    scene = CompositeVideoClip(
        [background, monitor],
        size=(EDIT_WIDTH, EDIT_HEIGHT)
    )

    scene = scene.with_duration(duration)

    return scene


def fallback_cut_durations(target_duration, intensity="medium"):
    if intensity == "high":
        pattern = [0.82, 0.72, 0.95, 0.78, 1.08]
    elif intensity == "low":
        pattern = [1.35, 1.10, 1.55, 1.25]
    else:
        pattern = [1.05, 0.90, 1.25, 0.95, 1.40]

    durations = []
    total = 0.0
    index = 0

    while total < target_duration and len(durations) < MAX_SCENES:
        duration = pattern[index % len(pattern)]
        durations.append(duration)
        total += duration
        index += 1

    return durations


def detect_cut_durations_from_music(music_path, target_duration, intensity="medium"):
    if not music_path or not os.path.exists(music_path):
        return fallback_cut_durations(target_duration, intensity)

    try:
        import librosa

        audio, sr = librosa.load(
            music_path,
            mono=True,
            duration=target_duration + 4
        )

        onset_env = librosa.onset.onset_strength(
            y=audio,
            sr=sr
        )

        tempo, beat_frames = librosa.beat.beat_track(
            onset_envelope=onset_env,
            sr=sr,
            trim=False
        )

        beat_times = librosa.frames_to_time(
            beat_frames,
            sr=sr
        )

        beat_times = [
            float(t)
            for t in beat_times
            if 0 <= float(t) <= target_duration
        ]

        if len(beat_times) < 4:
            return fallback_cut_durations(target_duration, intensity)

        # Интервалы по битам. Не режем на каждый бит слишком агрессивно.
        if intensity == "high":
            step = 2
        elif intensity == "low":
            step = 4
        else:
            step = 3

        cut_points = [0.0]

        for index in range(0, len(beat_times), step):
            point = beat_times[index]

            if point > cut_points[-1] + MIN_SCENE_DURATION:
                cut_points.append(point)

            if point >= target_duration:
                break

        if cut_points[-1] < target_duration:
            cut_points.append(float(target_duration))

        durations = []

        for i in range(len(cut_points) - 1):
            duration = cut_points[i + 1] - cut_points[i]
            duration = clamp(duration, MIN_SCENE_DURATION, MAX_SCENE_DURATION)
            durations.append(duration)

        if not durations:
            return fallback_cut_durations(target_duration, intensity)

        print("BEAT TEMPO:", tempo)
        print("SAFE BEAT DURATIONS:", durations)

        return durations[:MAX_SCENES]

    except Exception as error:
        print("BEAT DETECT ERROR:", error)
        return fallback_cut_durations(target_duration, intensity)


def build_timeline(clips, video_duration, target_duration=25, music_path=None, intensity="medium"):
    cut_durations = detect_cut_durations_from_music(
        music_path=music_path,
        target_duration=target_duration,
        intensity=intensity
    )

    sorted_clips = sorted(
        clips,
        key=lambda item: item.get("score", 0),
        reverse=True
    )

    if not sorted_clips:
        return []

    scenes = []
    total = 0.0
    index = 0

    for duration in cut_durations:
        if total >= target_duration:
            break

        if len(scenes) >= MAX_SCENES:
            break

        clip_data = sorted_clips[index % len(sorted_clips)]

        clip_start = float(clip_data.get("start", 0))
        clip_end = float(clip_data.get("end", clip_start + 3))
        moment = float(clip_data.get("time", (clip_start + clip_end) / 2))

        offset_pattern = [
            -0.50,
            -0.18,
            0.12,
            0.42,
            0.72
        ]

        offset = offset_pattern[index % len(offset_pattern)]

        start = moment + offset
        end = start + duration

        start = clamp(start, 0, max(0.1, video_duration - 0.1))
        end = clamp(end, start + 0.50, video_duration)

        if end - start < 0.50:
            index += 1
            continue

        scenes.append({
            "start": start,
            "end": end
        })

        total += end - start
        index += 1

    return scenes


def attach_music(final_edit, music_path, target_duration):
    if not music_path or not os.path.exists(music_path):
        return final_edit

    try:
        music = AudioFileClip(music_path)

        if music.duration > target_duration:
            music = music.subclipped(0, target_duration)

        final_edit = final_edit.with_audio(music)

    except Exception as error:
        print("MUSIC ATTACH ERROR:", error)

    return final_edit


def trim_to_duration(video_clip, target_duration):
    if video_clip.duration <= target_duration:
        return video_clip

    return video_clip.subclipped(0, target_duration)


def create_auto_edit(
    video_path,
    clips,
    target_duration=25,
    style="cinematic",
    intensity="medium",
    music_path=None
):
    os.makedirs("clips", exist_ok=True)

    try:
        target_duration = int(target_duration)
    except Exception:
        target_duration = 25

    target_duration = int(clamp(target_duration, 10, 45))

    if intensity not in {"low", "medium", "high"}:
        intensity = "medium"

    video = VideoFileClip(video_path)

    scenes_data = build_timeline(
        clips=clips,
        video_duration=video.duration,
        target_duration=target_duration,
        music_path=music_path,
        intensity=intensity
    )

    if not scenes_data:
        print("STABLE CINEMATIC MUSIC EDIT V7: no scenes found")
        video.close()
        return None

    print("STABLE CINEMATIC MUSIC EDIT V7 SETTINGS:", {
        "target_duration": target_duration,
        "style": style,
        "intensity": intensity,
        "music": music_path,
        "format": "vertical_full_monitor_centered_no_flash"
    })

    print("STABLE CINEMATIC MUSIC EDIT V7 SCENES:", scenes_data)

    scenes = []

    for scene_data in scenes_data:
        try:
            scene = create_scene(
                source_clip=video,
                start=scene_data["start"],
                end=scene_data["end"],
                intensity=intensity
            )

            scenes.append(scene)

        except Exception as error:
            print("STABLE CINEMATIC MUSIC EDIT V7 SCENE ERROR:", error)

    if not scenes:
        video.close()
        return None

    final_edit = concatenate_videoclips(
        scenes,
        method="compose"
    )

    final_edit = trim_to_duration(final_edit, target_duration)
    final_edit = attach_music(final_edit, music_path, target_duration)

    final_edit.write_videofile(
        EDIT_OUTPUT,
        codec="libx264",
        audio_codec="aac",
        fps=30
    )

    print("STABLE CINEMATIC MUSIC EDIT V7 CREATED:", EDIT_OUTPUT)

    for scene in scenes:
        try:
            scene.close()
        except Exception:
            pass

    final_edit.close()
    video.close()

    return EDIT_OUTPUT
