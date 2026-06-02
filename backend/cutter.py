import os
import re
import json
import subprocess
import numpy as np
import cv2

from PIL import Image, ImageFilter, ImageDraw, ImageFont
from moviepy import VideoFileClip, CompositeVideoClip, ImageClip


print("CUTTER VERSION: WORD TIMINGS STABLE SUBTITLES V8")

FONT_PATH = "C:/Windows/Fonts/arialbd.ttf"
WHISPER_MODEL_PATH = r"C:\whisper-large-v3"

STREAMER_PROMPT = """
Это русскоязычный игровой стрим. Возможные слова:
стрим, чат, донат, подписка, лайк, дизлайк, имба, катка, раунд,
тиммейт, противник, килл, фраг, хедшот, лут, скин, рофл, кринж,
жесть, капец, блин, ахаха, ха-ха, угар, смотрите, ребята, погнали.
"""

# Стабильные Shorts-субтитры.
# Тут НЕ используем активное слово, потому что word timestamps часто ошибаются.
SUBTITLE_Y = 1110
SUBTITLE_MAX_WIDTH = 960
SUBTITLE_FONT_SIZE = 82
SUBTITLE_STROKE_WIDTH = 8
SUBTITLE_TIME_OFFSET = 0.05

WORDS_PER_CAPTION = 3
MIN_CAPTION_DURATION = 0.65
MAX_CAPTION_DURATION = 1.35

WHITE = (255, 255, 255, 255)
YELLOW = (255, 220, 0, 255)
BLACK = (0, 0, 0, 255)
SHADOW = (0, 0, 0, 170)

# Авто-центрирование лица в основном видео
SMART_CENTER_ENABLED = True
SMART_CENTER_SAMPLES = 8
MAIN_CLIP_WIDTH = 1800
MAIN_CLIP_Y = 520
DEFAULT_MAIN_CLIP_X = -430

# Авто-зум на момент реакции
REACTION_ZOOM_ENABLED = True
REACTION_ZOOM_SCALE = 1.12
REACTION_ZOOM_IN_TIME = 0.25
REACTION_ZOOM_HOLD_TIME = 0.85
REACTION_ZOOM_OUT_TIME = 0.35


WEBCAM_SIZES = {
    "small": {
        "crop_width_ratio": 0.18,
        "crop_height_ratio": 0.24,
        "output_width": 500
    },
    "medium": {
        "crop_width_ratio": 0.23,
        "crop_height_ratio": 0.30,
        "output_width": 620
    },
    "large": {
        "crop_width_ratio": 0.30,
        "crop_height_ratio": 0.38,
        "output_width": 740
    }
}


def blur_frame(frame):
    image = Image.fromarray(frame)
    image = image.filter(ImageFilter.GaussianBlur(radius=10))
    return np.array(image)


def get_webcam_crop(video_width, video_height, position, size_name):
    size = WEBCAM_SIZES.get(size_name, WEBCAM_SIZES["medium"])

    crop_width = int(video_width * size["crop_width_ratio"])
    crop_height = int(video_height * size["crop_height_ratio"])

    crop_width = max(240, min(crop_width, video_width))
    crop_height = max(180, min(crop_height, video_height))

    if position == "top_left":
        x1 = 0
        y1 = 0

    elif position == "top_right":
        x1 = video_width - crop_width
        y1 = 0

    elif position == "middle_left":
        x1 = 0
        y1 = (video_height - crop_height) / 2

    elif position == "middle_right":
        x1 = video_width - crop_width
        y1 = (video_height - crop_height) / 2

    elif position == "bottom_left":
        x1 = 0
        y1 = video_height - crop_height

    elif position == "bottom_right":
        x1 = video_width - crop_width
        y1 = video_height - crop_height

    else:
        x1 = 0
        y1 = 0

    return {
        "x1": int(x1),
        "y1": int(y1),
        "width": int(crop_width),
        "height": int(crop_height),
        "output_width": int(size["output_width"])
    }


def clean_subtitle_word(word):
    word = word.strip()
    word = re.sub(r"[^\wА-Яа-яЁё0-9]+", "", word, flags=re.UNICODE)
    return word.upper()


def load_font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def load_whisper_model():
    try:
        from faster_whisper import WhisperModel

        print("LOADING WHISPER MODEL FOR SUBTITLES...")

        model = WhisperModel(
            WHISPER_MODEL_PATH,
            device="cpu",
            compute_type="int8"
        )

        print("WHISPER MODEL LOADED")
        return model

    except Exception as error:
        print("SUBTITLES DISABLED. WHISPER LOAD ERROR:", error)
        return None


def split_words_to_chunks(words, words_per_caption):
    chunks = []

    for i in range(0, len(words), words_per_caption):
        chunks.append(words[i:i + words_per_caption])

    return chunks



def create_clean_audio_for_whisper(video_path, output_audio_path):
    """
    Создаёт очищенный WAV для Whisper:
    голос громче, низкий гул тише, пики мягче.
    """
    try:
        command = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-af",
            (
                "highpass=f=90,"
                "lowpass=f=7800,"
                "afftdn=nf=-25,"
                "dynaudnorm=f=150:g=12:p=0.95,"
                "acompressor=threshold=-18dB:ratio=3:attack=8:release=120,"
                "volume=1.8"
            ),
            output_audio_path
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print("FFMPEG CLEAN AUDIO ERROR:", result.stderr)
            return None

        if not os.path.exists(output_audio_path):
            print("CLEAN AUDIO FILE NOT FOUND")
            return None

        print("CLEAN AUDIO CREATED:", output_audio_path)
        return output_audio_path

    except Exception as error:
        print("CLEAN AUDIO ERROR:", error)
        return None


def get_word_value(word_info, key):
    if hasattr(word_info, key):
        return getattr(word_info, key)

    if isinstance(word_info, dict):
        return word_info.get(key)

    return None


def estimate_whisper_quality(segment_reports):
    if not segment_reports:
        return 0

    avg_logprob_values = [
        item["avg_logprob"]
        for item in segment_reports
        if item.get("avg_logprob") is not None
    ]

    no_speech_values = [
        item["no_speech_prob"]
        for item in segment_reports
        if item.get("no_speech_prob") is not None
    ]

    if not avg_logprob_values:
        return 70

    avg_logprob = float(np.mean(avg_logprob_values))
    no_speech_prob = float(np.mean(no_speech_values)) if no_speech_values else 0

    quality = 100 + avg_logprob * 35 - no_speech_prob * 35
    quality = max(0, min(100, quality))

    return int(round(quality))


def make_word_captions(words, clip_duration):
    captions = []
    index = 0

    while index < len(words):
        group = [words[index]]
        group_start = words[index]["start"]
        group_end = words[index]["end"]

        index += 1

        while index < len(words):
            next_word = words[index]

            if len(group) >= WORDS_PER_CAPTION:
                break

            if next_word["start"] - group_end > 0.55:
                break

            if next_word["end"] - group_start > MAX_CAPTION_DURATION:
                break

            group.append(next_word)
            group_end = next_word["end"]
            index += 1

        caption_text = " ".join([item["text"] for item in group])

        start = max(0.0, group_start)
        end = min(group[-1]["end"], clip_duration)

        if end - start < MIN_CAPTION_DURATION:
            end = min(start + MIN_CAPTION_DURATION, clip_duration)

        captions.append({
            "start": start,
            "end": end,
            "text": caption_text
        })

    return captions


def make_subtitles_for_clip(clip_path, clip_duration, model):
    if model is None:
        return [], {
            "text": "",
            "quality": 0,
            "segments": []
        }

    captions = []
    raw_text_parts = []
    segment_reports = []
    word_items = []

    try:
        clean_audio_path = os.path.join(
            "temp",
            "clean_audio_for_whisper.wav"
        )

        audio_for_whisper = create_clean_audio_for_whisper(
            clip_path,
            clean_audio_path
        )

        if audio_for_whisper is None:
            audio_for_whisper = clip_path

        segments, info = model.transcribe(
            audio_for_whisper,
            language="ru",
            vad_filter=False,
            beam_size=10,
            best_of=5,
            temperature=0,
            condition_on_previous_text=False,
            initial_prompt=STREAMER_PROMPT,
            word_timestamps=True
        )

        for segment in segments:
            text = segment.text.strip()

            if text:
                raw_text_parts.append(text)

            avg_logprob = getattr(segment, "avg_logprob", None)
            no_speech_prob = getattr(segment, "no_speech_prob", None)

            segment_reports.append({
                "start": round(float(segment.start), 2),
                "end": round(float(segment.end), 2),
                "text": text,
                "avg_logprob": float(avg_logprob) if avg_logprob is not None else None,
                "no_speech_prob": float(no_speech_prob) if no_speech_prob is not None else None
            })

            words = getattr(segment, "words", None)

            if words:
                for word_info in words:
                    raw_word = get_word_value(word_info, "word")
                    raw_start = get_word_value(word_info, "start")
                    raw_end = get_word_value(word_info, "end")

                    if raw_word is None or raw_start is None or raw_end is None:
                        continue

                    cleaned = clean_subtitle_word(str(raw_word))

                    if not cleaned:
                        continue

                    start = max(0.0, float(raw_start) + SUBTITLE_TIME_OFFSET)
                    end = min(float(raw_end) + SUBTITLE_TIME_OFFSET, clip_duration)

                    if end <= start:
                        continue

                    word_items.append({
                        "start": start,
                        "end": end,
                        "text": cleaned
                    })

        if audio_for_whisper == clean_audio_path and os.path.exists(clean_audio_path):
            os.remove(clean_audio_path)

    except Exception as error:
        print("SUBTITLE TRANSCRIBE ERROR:", error)

    word_items = sorted(word_items, key=lambda item: item["start"])

    if word_items:
        captions = make_word_captions(word_items, clip_duration)
    else:
        # fallback по старому принципу, если Whisper почему-то не дал word timestamps
        print("NO WORD TIMESTAMPS, USING SEGMENT FALLBACK")

        for segment in segment_reports:
            text = segment.get("text", "").strip()

            if not text:
                continue

            words = []

            for raw_word in text.split():
                cleaned = clean_subtitle_word(raw_word)
                if cleaned:
                    words.append(cleaned)

            if not words:
                continue

            segment_start = max(0.0, float(segment["start"]) + SUBTITLE_TIME_OFFSET)
            segment_end = min(float(segment["end"]) + SUBTITLE_TIME_OFFSET, clip_duration)

            chunks = split_words_to_chunks(words, WORDS_PER_CAPTION)

            total_duration = max(0.1, segment_end - segment_start)
            caption_duration = total_duration / max(1, len(chunks))
            caption_duration = max(MIN_CAPTION_DURATION, min(MAX_CAPTION_DURATION, caption_duration))

            for index, chunk in enumerate(chunks):
                start = segment_start + index * caption_duration
                end = min(start + caption_duration, clip_duration)

                captions.append({
                    "start": start,
                    "end": end,
                    "text": " ".join(chunk)
                })

    fixed_captions = []

    for caption in captions:
        if fixed_captions and caption["start"] < fixed_captions[-1]["end"]:
            fixed_captions[-1]["end"] = max(
                fixed_captions[-1]["start"] + 0.20,
                caption["start"]
            )

        if caption["end"] > caption["start"]:
            fixed_captions.append(caption)

    full_text = " ".join(raw_text_parts).strip()
    quality = estimate_whisper_quality(segment_reports)

    report = {
        "text": full_text,
        "quality": quality,
        "segments": segment_reports
    }

    print("WHISPER QUALITY:", quality)
    print("WHISPER TEXT:", full_text)
    print("WORD ITEMS:", word_items)
    print("WORD TIMING CAPTIONS:", fixed_captions)

    return fixed_captions, report


def pop_scale(t):
    if t < 0:
        return 1.0

    if t < 0.07:
        return 0.86 + (t / 0.07) * 0.18

    if t < 0.14:
        return 1.04 - ((t - 0.07) / 0.07) * 0.04

    return 1.0


def get_caption_font_size(text):
    length = len(text)

    if length <= 12:
        return SUBTITLE_FONT_SIZE

    if length <= 20:
        return 74

    if length <= 28:
        return 66

    return 58


def render_caption_image(text):
    font_size = get_caption_font_size(text)
    font = load_font(font_size)

    canvas_width = SUBTITLE_MAX_WIDTH + 240
    canvas_height = 250

    image = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Делим длинные фразы на две строки
    words = text.split()
    lines = []

    if len(words) <= 2:
        lines = [" ".join(words)]
    elif len(words) == 3:
        lines = [" ".join(words[:2]), words[2]]
    else:
        middle = len(words) // 2
        lines = [" ".join(words[:middle]), " ".join(words[middle:])]

    while font_size > 42:
        font = load_font(font_size)

        line_boxes = [
            draw.textbbox(
                (0, 0),
                line,
                font=font,
                stroke_width=SUBTITLE_STROKE_WIDTH
            )
            for line in lines
        ]

        line_widths = [box[2] - box[0] for box in line_boxes]
        line_heights = [box[3] - box[1] for box in line_boxes]

        max_width = max(line_widths)
        total_height = sum(line_heights) + 12 * (len(lines) - 1)

        if max_width <= SUBTITLE_MAX_WIDTH:
            break

        font_size -= 4

    y = (canvas_height - total_height) / 2

    for line_index, line in enumerate(lines):
        bbox = draw.textbbox(
            (0, 0),
            line,
            font=font,
            stroke_width=SUBTITLE_STROKE_WIDTH
        )

        line_width = bbox[2] - bbox[0]
        line_height = bbox[3] - bbox[1]

        x = (canvas_width - line_width) / 2 - bbox[0]
        y_line = y - bbox[1]

        # Первое слово/ключевая часть чуть жёлтая, чтобы выглядело живее
        fill_color = YELLOW if line_index == 0 and len(lines) > 1 else WHITE

        draw.text(
            (x + 5, y_line + 7),
            line,
            font=font,
            fill=SHADOW,
            stroke_width=SUBTITLE_STROKE_WIDTH,
            stroke_fill=SHADOW
        )

        draw.text(
            (x, y_line),
            line,
            font=font,
            fill=fill_color,
            stroke_width=SUBTITLE_STROKE_WIDTH,
            stroke_fill=BLACK
        )

        y += line_height + 12

    return np.array(image)


def create_subtitle_clips(captions):
    subtitle_clips = []

    for caption in captions:
        subtitle_image = render_caption_image(caption["text"])

        txt_clip = ImageClip(subtitle_image)

        try:
            txt_clip = txt_clip.resized(lambda t: pop_scale(t))
        except Exception:
            pass

        txt_clip = (
            txt_clip
            .with_position(("center", SUBTITLE_Y))
            .with_start(caption["start"])
            .with_end(caption["end"])
        )

        subtitle_clips.append(txt_clip)

    return subtitle_clips


def detect_face_center_in_clip(clip):
    if not SMART_CENTER_ENABLED:
        return None

    try:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)

        if face_cascade.empty():
            print("SMART CENTER: face cascade not loaded")
            return None

        face_centers = []

        duration = max(0.1, clip.duration)

        for sample_index in range(SMART_CENTER_SAMPLES):
            t = duration * (sample_index + 1) / (SMART_CENTER_SAMPLES + 1)

            frame = clip.get_frame(t)

            small_width = 640
            scale = small_width / frame.shape[1]
            small_height = int(frame.shape[0] * scale)

            small_frame = cv2.resize(frame, (small_width, small_height))
            gray = cv2.cvtColor(small_frame, cv2.COLOR_RGB2GRAY)

            faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(40, 40)
            )

            if len(faces) == 0:
                continue

            faces = sorted(
                faces,
                key=lambda item: item[2] * item[3],
                reverse=True
            )

            x, y, w, h = faces[0]

            center_x_small = x + w / 2
            center_x_original = center_x_small / scale

            face_centers.append(center_x_original)

        if not face_centers:
            print("SMART CENTER: no face found")
            return None

        face_center = float(np.median(face_centers))

        print("SMART CENTER FACE X:", round(face_center, 2))

        return face_center

    except Exception as error:
        print("SMART CENTER ERROR:", error)
        return None


def get_smart_main_position(clip):
    face_center = detect_face_center_in_clip(clip)

    if face_center is None:
        return DEFAULT_MAIN_CLIP_X

    source_width = clip.w
    resize_scale = MAIN_CLIP_WIDTH / source_width

    face_center_resized = face_center * resize_scale
    shorts_center_x = 1080 / 2

    target_x = shorts_center_x - face_center_resized

    min_x = 1080 - MAIN_CLIP_WIDTH
    max_x = 0

    target_x = max(min_x, min(max_x, target_x))

    final_x = DEFAULT_MAIN_CLIP_X * 0.35 + target_x * 0.65
    final_x = int(max(min_x, min(max_x, final_x)))

    print("SMART CENTER MAIN X:", final_x)

    return final_x



def make_reaction_zoom_clip(clip, clip_data, main_x):
    if not REACTION_ZOOM_ENABLED:
        return None

    try:
        clip_start_global = float(clip_data.get("start", 0))
        clip_end_global = float(clip_data.get("end", clip_start_global + clip.duration))

        # Если analyzer передал точку реакции, используем её.
        # Если нет — считаем, что реакция примерно в начале после clip_before.
        moment_global = float(
            clip_data.get(
                "time",
                clip_data.get(
                    "moment",
                    clip_start_global + min(6, max(3, clip.duration * 0.20))
                )
            )
        )

        zoom_center = moment_global - clip_start_global

        # Защита границ
        zoom_center = max(0.5, min(clip.duration - 0.5, zoom_center))

        zoom_start = max(0, zoom_center - REACTION_ZOOM_IN_TIME)
        zoom_end = min(
            clip.duration,
            zoom_center + REACTION_ZOOM_HOLD_TIME + REACTION_ZOOM_OUT_TIME
        )

        if zoom_end <= zoom_start:
            return None

        zoom_piece = clip.subclipped(zoom_start, zoom_end)

        zoom_width = int(MAIN_CLIP_WIDTH * REACTION_ZOOM_SCALE)
        zoom_y = int(MAIN_CLIP_Y - ((MAIN_CLIP_WIDTH * REACTION_ZOOM_SCALE - MAIN_CLIP_WIDTH) * 0.16))

        # Компенсируем увеличение, чтобы центр был примерно там же
        zoom_x = int(main_x - (zoom_width - MAIN_CLIP_WIDTH) / 2)

        min_x = 1080 - zoom_width
        max_x = 0
        zoom_x = max(min_x, min(max_x, zoom_x))

        zoom_clip = zoom_piece.resized(width=zoom_width)
        zoom_clip = zoom_clip.with_position((zoom_x, zoom_y))
        zoom_clip = zoom_clip.with_start(zoom_start)

        try:
            zoom_clip = zoom_clip.with_opacity(
                lambda t: (
                    min(1, max(0, t / REACTION_ZOOM_IN_TIME))
                    if t < REACTION_ZOOM_IN_TIME
                    else (
                        min(1, max(0, (zoom_end - zoom_start - t) / REACTION_ZOOM_OUT_TIME))
                        if t > (zoom_end - zoom_start - REACTION_ZOOM_OUT_TIME)
                        else 1
                    )
                )
            )
        except Exception:
            pass

        print("REACTION ZOOM:", {
            "center": round(zoom_center, 2),
            "start": round(zoom_start, 2),
            "end": round(zoom_end, 2),
            "x": zoom_x,
            "y": zoom_y,
            "width": zoom_width
        })

        return zoom_clip

    except Exception as error:
        print("REACTION ZOOM ERROR:", error)
        return None


def create_shorts(
    video_path,
    clips,
    webcam_position="top_left",
    webcam_size="medium",
    subtitles_enabled=True
):
    os.makedirs("clips", exist_ok=True)
    os.makedirs("temp", exist_ok=True)

    video = VideoFileClip(video_path)

    subtitle_reports = []

    whisper_model = None

    if subtitles_enabled:
        whisper_model = load_whisper_model()

    for i, clip_data in enumerate(clips):
        start = max(0, clip_data["start"])
        end = min(clip_data["end"], video.duration)

        if end <= start:
            print("SKIPPED BAD CLIP:", clip_data)
            continue

        clip = video.subclipped(start, end)

        background = clip.resized(height=1920)
        background = background.cropped(
            width=1080,
            height=1920,
            x_center=background.w / 2,
            y_center=background.h / 2
        )
        background = background.image_transform(blur_frame)

        main_x = get_smart_main_position(clip)

        # Уводим старую вебку из основного кадра.
        # Отдельная вебка сверху остаётся, а дубль в основном видео уезжает за пределы Shorts.
        webcam_shift = 350

        if webcam_position in {
            "top_left",
            "middle_left",
            "bottom_left"
        }:
            main_x -= webcam_shift

        elif webcam_position in {
            "top_right",
            "middle_right",
            "bottom_right"
        }:
            main_x += webcam_shift

        # Ограничиваем позицию, чтобы основной кадр не уехал слишком далеко.
        min_main_x = 1080 - MAIN_CLIP_WIDTH
        max_main_x = 0
        main_x = int(max(min_main_x, min(max_main_x, main_x)))

        print("MAIN X AFTER WEBCAM SHIFT:", main_x)

        main_clip = clip.resized(width=MAIN_CLIP_WIDTH)
        main_clip = main_clip.with_position((main_x, MAIN_CLIP_Y))

        layers = [background, main_clip]

        reaction_zoom_clip = make_reaction_zoom_clip(
            clip=clip,
            clip_data=clip_data,
            main_x=main_x
        )

        if reaction_zoom_clip is not None:
            layers.append(reaction_zoom_clip)

        if webcam_position != "none":
            crop = get_webcam_crop(
                video_width=clip.w,
                video_height=clip.h,
                position=webcam_position,
                size_name=webcam_size
            )

            webcam = clip.cropped(
                x1=crop["x1"],
                y1=crop["y1"],
                width=crop["width"],
                height=crop["height"]
            )

            webcam = webcam.resized(width=crop["output_width"])
            webcam = webcam.with_position(("center", 45))

            layers.append(webcam)

        subtitle_clips = []

        if subtitles_enabled and whisper_model is not None:
            temp_clip_path = f"temp/subtitle_source_{i}.mp4"

            clip.write_videofile(
                temp_clip_path,
                codec="libx264",
                audio_codec="aac",
                fps=30,
                logger=None
            )

            captions, subtitle_report = make_subtitles_for_clip(
                temp_clip_path,
                clip.duration,
                whisper_model
            )

            subtitle_report["clip_index"] = i
            subtitle_report["clip_name"] = f"clip_{i}.mp4"
            subtitle_reports.append(subtitle_report)

            subtitle_clips = create_subtitle_clips(captions)

            if os.path.exists(temp_clip_path):
                os.remove(temp_clip_path)

        if not subtitles_enabled or whisper_model is None:
            subtitle_reports.append({
                "clip_index": i,
                "clip_name": f"clip_{i}.mp4",
                "text": "",
                "quality": 0,
                "segments": []
            })

        final_video = CompositeVideoClip(
            layers + subtitle_clips,
            size=(1080, 1920)
        )

        output = f"clips/clip_{i}.mp4"

        final_video.write_videofile(
            output,
            codec="libx264",
            audio_codec="aac",
            fps=30
        )

        print("CREATED:", output)

        final_video.close()
        clip.close()

    report_path = os.path.join("clips", "subtitles_report.json")

    with open(report_path, "w", encoding="utf-8") as report_file:
        json.dump(subtitle_reports, report_file, ensure_ascii=False, indent=2)

    print("SUBTITLE REPORT SAVED:", report_path)

    video.close()

    return subtitle_reports
