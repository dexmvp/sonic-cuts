import whisper

model = whisper.load_model("base")

def generate_subtitles(video_path):

    result = model.transcribe(video_path)

    return result["segments"]