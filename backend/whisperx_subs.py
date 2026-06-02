from faster_whisper import WhisperModel

print("LOADING FASTER WHISPER...")

model = WhisperModel(
    r"C:\whisper-large-v3",
    device="cpu",
    compute_type="int8"
)

print("FASTER WHISPER LOADED")


BLOCKED_WORDS = [
    "субтитры", "диматорзок",
    "агенты", "наблюдение", "амулет", "амулетом",
    "порталы", "демонов", "федералы", "передатчик"
]


def is_good_subtitle(text):
    text_low = text.strip().lower()

    if len(text_low) < 2:
        return False

    words = text_low.split()

    if len(words) > 14:
        return False

    if len(text_low) > 90:
        return False

    for word in BLOCKED_WORDS:
        if word in text_low:
            return False

    return True


def make_subtitles(video_path):
    segments, info = model.transcribe(
        video_path,
        language="ru",
        vad_filter=False,
        beam_size=5,
        condition_on_previous_text=False
    )

    subtitles = []

    print("========== FILTERED WHISPER SEGMENTS ==========")

    for segment in segments:
        text = segment.text.strip()

        if not is_good_subtitle(text):
            continue

        start = float(segment.start)
        end = float(segment.end)

        if end - start > 3.0:
            end = start + 3.0

        print(f"{start:.2f} -> {end:.2f}: {text}")

        subtitles.append({
            "start": start,
            "end": end,
            "text": text
        })

    print("========== SUBTITLES RETURNED ==========")
    print(subtitles)

    return subtitles