import whisper

model = whisper.load_model("base")

def generate_subtitles(video_path):

    print("START WHISPER")

    result = model.transcribe(video_path)

    print("WHISPER DONE")

    subtitles = []

    for segment in result["segments"]:

        subtitles.append({
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"]
        })

    print(subtitles)

    return subtitles