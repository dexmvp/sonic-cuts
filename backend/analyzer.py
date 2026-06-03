import os
import subprocess
import tempfile
import librosa
import numpy as np


DEFAULT_MAX_CLIPS = 5
DEFAULT_CLIP_LENGTH = 30


MODE_SETTINGS = {
    "balanced": {
        "name": "BALANCED V2",
        "threshold_std": 1.10,
        "fallback_threshold_std": 1.55,
        "weights": {
            "loudness": 0.24,
            "jump": 0.20,
            "energy_burst": 0.20,
            "voice": 0.16,
            "laughter": 0.12,
            "brightness": 0.05,
            "zcr": 0.03
        }
    },
    "reactions": {
        "name": "REACTIONS V2",
        "threshold_std": 0.95,
        "fallback_threshold_std": 1.65,
        "weights": {
            "loudness": 0.18,
            "jump": 0.25,
            "energy_burst": 0.25,
            "voice": 0.16,
            "laughter": 0.12,
            "brightness": 0.03,
            "zcr": 0.01
        }
    },
    "loud": {
        "name": "LOUD V2",
        "threshold_std": 1.35,
        "fallback_threshold_std": 1.45,
        "weights": {
            "loudness": 0.58,
            "jump": 0.18,
            "energy_burst": 0.12,
            "voice": 0.06,
            "laughter": 0.03,
            "brightness": 0.02,
            "zcr": 0.01
        }
    }
}


def normalize(values):
    values = np.array(values, dtype=float)

    min_value = np.min(values)
    max_value = np.max(values)

    if max_value - min_value < 1e-9:
        return np.zeros_like(values)

    return (values - min_value) / (max_value - min_value)


def safe_mean(values):
    if len(values) == 0:
        return 0

    return float(np.mean(values))


def calculate_laughter_score(loudness_score):
    laughter_score = np.zeros_like(loudness_score)

    for i in range(5, len(loudness_score) - 5):
        local = loudness_score[i - 5:i + 6]

        peaks = 0

        for j in range(1, len(local) - 1):
            if local[j] > local[j - 1] and local[j] > local[j + 1] and local[j] > 0.42:
                peaks += 1

        if peaks >= 2:
            laughter_score[i] = min(1.0, peaks / 4)

    return laughter_score


def calculate_energy_burst(smooth_rms):
    """
    Реакция часто выглядит так:
    было тише -> резко стало громче.
    Этот признак лучше отличает реакцию от просто постоянной громкой музыки.
    """
    energy_burst = np.zeros_like(smooth_rms)

    for i in range(10, len(smooth_rms)):
        previous_window = smooth_rms[max(0, i - 18):max(1, i - 6)]
        current_window = smooth_rms[max(0, i - 3):i + 1]

        previous_energy = safe_mean(previous_window)
        current_energy = safe_mean(current_window)

        if previous_energy <= 1e-7:
            continue

        burst = (current_energy - previous_energy) / (previous_energy + 1e-7)

        if burst > 0:
            energy_burst[i] = burst

    return normalize(energy_burst)


def calculate_voice_score(audio, sr, hop_length):
    """
    Простая оценка "похоже ли на голос".
    Голос обычно имеет заметную энергию в диапазоне примерно 120-3400 Hz.
    Музыка/взрывы часто дают слишком много низов/верхов.
    """
    stft = np.abs(librosa.stft(audio, n_fft=2048, hop_length=hop_length))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)

    voice_band = (freqs >= 120) & (freqs <= 3400)
    low_band = freqs < 90
    high_band = freqs > 5000

    voice_energy = np.mean(stft[voice_band], axis=0)
    low_energy = np.mean(stft[low_band], axis=0)
    high_energy = np.mean(stft[high_band], axis=0)
    total_energy = np.mean(stft, axis=0) + 1e-7

    voice_ratio = voice_energy / total_energy
    noise_penalty = (low_energy + high_energy) / (total_energy + 1e-7)

    voice_score = voice_ratio - noise_penalty * 0.25

    return normalize(np.maximum(voice_score, 0))


def calculate_music_noise_penalty(flatness_score, brightness_score, loudness_score):
    """
    Штрафуем участки, которые похожи на постоянный шум/музыку:
    высокая яркость + высокая плоскость спектра + высокая громкость.
    """
    penalty = (
        flatness_score * 0.45 +
        brightness_score * 0.25 +
        loudness_score * 0.30
    )

    return normalize(penalty)


def local_peak_score(values, index, radius=8):
    left = max(0, index - radius)
    right = min(len(values), index + radius + 1)

    local_max = np.max(values[left:right])

    if local_max <= 1e-9:
        return False

    return values[index] >= local_max



def load_audio_for_analysis(video_path, target_sr=22050):
    """
    Railway/server-safe audio loader.

    Problem:
    librosa.load(video_path) can fail on Railway with:
    audioread.exceptions.NoBackendError

    Fix:
    1. Extract audio from video with ffmpeg into a temporary WAV.
    2. Load that WAV with librosa.
    """
    temp_audio_path = None

    try:
        temp_file = tempfile.NamedTemporaryFile(
            suffix=".wav",
            delete=False
        )
        temp_audio_path = temp_file.name
        temp_file.close()

        command = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(target_sr),
            "-ac",
            "1",
            temp_audio_path
        ]

        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )

        audio, sr = librosa.load(
            temp_audio_path,
            sr=target_sr,
            mono=True
        )

        return audio, sr

    finally:
        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.remove(temp_audio_path)
            except Exception:
                pass


def find_loud_moments(
    video_path,
    max_clips=DEFAULT_MAX_CLIPS,
    clip_length=DEFAULT_CLIP_LENGTH,
    mode="balanced"
):

    settings = MODE_SETTINGS.get(mode, MODE_SETTINGS["balanced"])
    weights = settings["weights"]

    print(f"ANALYZING AI HIGHLIGHT SCORE MODE: {settings['name']}")

    max_clips = int(max_clips)
    clip_length = int(clip_length)

    clip_before = min(6, max(3, clip_length // 5))
    clip_after = max(5, clip_length - clip_before)

    audio, sr = load_audio_for_analysis(video_path)

    video_duration = len(audio) / sr

    hop_length = 512

    rms = librosa.feature.rms(
        y=audio,
        hop_length=hop_length
    )[0]

    window = 8
    smooth_rms = np.convolve(
        rms,
        np.ones(window) / window,
        mode="same"
    )

    volume_jump = np.diff(smooth_rms, prepend=smooth_rms[0])
    volume_jump = np.maximum(volume_jump, 0)

    spectral_centroid = librosa.feature.spectral_centroid(
        y=audio,
        sr=sr,
        hop_length=hop_length
    )[0]

    spectral_flatness = librosa.feature.spectral_flatness(
        y=audio,
        hop_length=hop_length
    )[0]

    zcr = librosa.feature.zero_crossing_rate(
        audio,
        hop_length=hop_length
    )[0]

    loudness_score = normalize(smooth_rms)
    jump_score = normalize(volume_jump)
    brightness_score = normalize(spectral_centroid)
    flatness_score = normalize(spectral_flatness)
    zcr_score = normalize(zcr)

    laughter_score = calculate_laughter_score(loudness_score)
    energy_burst_score = calculate_energy_burst(smooth_rms)
    voice_score = calculate_voice_score(audio, sr, hop_length)
    music_noise_penalty = calculate_music_noise_penalty(
        flatness_score=flatness_score,
        brightness_score=brightness_score,
        loudness_score=loudness_score
    )

    raw_highlight_score = (
        loudness_score * weights["loudness"] +
        jump_score * weights["jump"] +
        energy_burst_score * weights["energy_burst"] +
        voice_score * weights["voice"] +
        laughter_score * weights["laughter"] +
        brightness_score * weights["brightness"] +
        zcr_score * weights["zcr"]
    )

    # Штраф за участки, похожие на музыку/шум без явной реакции.
    highlight_score = raw_highlight_score - music_noise_penalty * 0.18

    # Бонус, если одновременно есть голос + всплеск + громкость.
    reaction_combo = (
        voice_score * 0.45 +
        energy_burst_score * 0.35 +
        loudness_score * 0.20
    )

    highlight_score += reaction_combo * 0.16

    highlight_score = normalize(np.maximum(highlight_score, 0))

    mean_score = np.mean(highlight_score)
    std_score = np.std(highlight_score)

    threshold = mean_score + std_score * settings["threshold_std"]

    candidates = []

    edge_ignore = min(30, max(5, video_duration * 0.04))

    for i, score in enumerate(highlight_score):

        time = librosa.frames_to_time(
            i,
            sr=sr,
            hop_length=hop_length
        )

        if time < edge_ignore:
            continue

        if time > video_duration - edge_ignore:
            continue

        if score < threshold:
            continue

        if not local_peak_score(highlight_score, i, radius=10):
            continue

        # Защита: не берём слишком "не голосовые" участки, если это не режим loud.
        if mode != "loud":
            if voice_score[i] < 0.18 and laughter_score[i] < 0.2:
                continue

        candidates.append({
            "time": float(time),
            "score": float(score),
            "loudness": float(loudness_score[i]),
            "jump": float(jump_score[i]),
            "energy_burst": float(energy_burst_score[i]),
            "voice": float(voice_score[i]),
            "laughter": float(laughter_score[i]),
            "noise_penalty": float(music_noise_penalty[i])
        })

    candidates = sorted(
        candidates,
        key=lambda item: item["score"],
        reverse=True
    )

    min_distance = max(
        clip_length * 2,
        int(video_duration / max(1, max_clips * 2))
    )

    selected = []

    for candidate in candidates:
        time = candidate["time"]

        too_close = False

        for selected_item in selected:
            if abs(time - selected_item["time"]) < min_distance:
                too_close = True
                break

        if too_close:
            continue

        selected.append(candidate)

        if len(selected) >= max_clips:
            break

    selected = sorted(
        selected,
        key=lambda item: item["time"]
    )

    clips = []

    for item in selected:
        moment = item["time"]

        clip_start = max(0, moment - clip_before)
        clip_end = min(video_duration, moment + clip_after)

        if clip_end <= clip_start:
            continue

        if clips and clip_start < clips[-1]["end"]:
            continue

        clips.append({
            "start": clip_start,
            "end": clip_end,
            "time": moment,
            "score": round(item["score"], 3),
            "mode": mode,
            "reason": {
                "voice": round(item["voice"], 2),
                "burst": round(item["energy_burst"], 2),
                "loudness": round(item["loudness"], 2),
                "laughter": round(item["laughter"], 2)
            }
        })

    if len(clips) < max_clips:
        print("NOT ENOUGH AI MOMENTS, ADDING SMART LOUD FALLBACK...")

        loud_candidates = []

        mean_volume = np.mean(smooth_rms)
        std_volume = np.std(smooth_rms)
        loud_threshold = mean_volume + std_volume * settings["fallback_threshold_std"]

        for i, value in enumerate(smooth_rms):
            if value < loud_threshold:
                continue

            time = librosa.frames_to_time(
                i,
                sr=sr,
                hop_length=hop_length
            )

            if time < edge_ignore or time > video_duration - edge_ignore:
                continue

            if not local_peak_score(smooth_rms, i, radius=10):
                continue

            # Даже fallback теперь предпочитает голосовые громкие моменты.
            fallback_score = (
                loudness_score[i] * 0.55 +
                voice_score[i] * 0.20 +
                energy_burst_score[i] * 0.18 +
                laughter_score[i] * 0.07
            )

            loud_candidates.append({
                "time": float(time),
                "score": float(fallback_score),
                "voice": float(voice_score[i]),
                "energy_burst": float(energy_burst_score[i]),
                "loudness": float(loudness_score[i]),
                "laughter": float(laughter_score[i])
            })

        loud_candidates = sorted(
            loud_candidates,
            key=lambda item: item["score"],
            reverse=True
        )

        for candidate in loud_candidates:
            if len(clips) >= max_clips:
                break

            moment = candidate["time"]
            clip_start = max(0, moment - clip_before)
            clip_end = min(video_duration, moment + clip_after)

            too_close = False

            for clip in clips:
                clip_center = (clip["start"] + clip["end"]) / 2

                if abs(moment - clip_center) < min_distance:
                    too_close = True
                    break

            if too_close:
                continue

            clips.append({
                "start": clip_start,
                "end": clip_end,
                "time": moment,
                "score": round(candidate["score"], 3),
                "mode": mode,
                "reason": {
                    "voice": round(candidate["voice"], 2),
                    "burst": round(candidate["energy_burst"], 2),
                    "loudness": round(candidate["loudness"], 2),
                    "laughter": round(candidate["laughter"], 2)
                }
            })

    clips = sorted(
        clips,
        key=lambda item: item["start"]
    )

    print("FOUND AI HIGHLIGHTS:", clips)

    return clips
