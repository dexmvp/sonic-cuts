from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import os
import shutil
import uuid
import subprocess
import zipfile

from analyzer import find_loud_moments
from cutter import create_shorts
from editor import create_auto_edit

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("uploads", exist_ok=True)
os.makedirs("clips", exist_ok=True)
os.makedirs("static", exist_ok=True)

app.mount("/clips", StaticFiles(directory="clips"), name="clips")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Лимиты для публичного MVP
MAX_VIDEO_SIZE_MB = 2048
MAX_VIDEO_SIZE_BYTES = MAX_VIDEO_SIZE_MB * 1024 * 1024



@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    return JSONResponse(
        status_code=400,
        content={
            "status": "error",
            "message": str(exc)
        }
    )


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request, exc):
    return JSONResponse(
        status_code=400,
        content={
            "status": "error",
            "message": str(exc)
        }
    )

@app.get("/", response_class=HTMLResponse)
async def home():
    return """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Sonic Cuts</title>

    <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.3/dist/confetti.browser.min.js"></script>

    <style>
        * { box-sizing: border-box; }

        body {
            margin: 0;
            min-height: 100vh;
            font-family: Arial, sans-serif;
            color: white;
            display: flex;
            align-items: flex-start;
            justify-content: center;
            padding-top: 190px;
            background:
                radial-gradient(circle at top left, rgba(255,42,109,.55), transparent 30%),
                radial-gradient(circle at bottom right, rgba(5,217,232,.5), transparent 35%),
                linear-gradient(rgba(6,8,18,.76), rgba(6,8,18,.88)),
                url("/static/green_hill.jpg");
            background-size: cover;
            background-position: center;
            background-attachment: fixed;
        }

        .box-wrapper {
            position: relative;
        }

        .hero-sonic {
            position: absolute;
            width: 430px;
            left: 50%;
            top: -115px;
            transform: translateX(-50%);
            z-index: 100;
            pointer-events: none;
            filter:
                drop-shadow(0 20px 40px rgba(0,0,0,.55))
                drop-shadow(0 0 35px rgba(0,150,255,.38));
        }

        .box {
            width: 860px;
            padding: 125px 34px 34px;
            border-radius: 26px;
            text-align: center;
            background: rgba(18, 18, 28, 0.82);
            box-shadow: 0 0 60px rgba(124, 58, 237, 0.45);
            border: 1px solid rgba(255,255,255,0.12);
            backdrop-filter: blur(14px);
        }

        h1 {
            margin: 0 0 10px;
            font-size: 38px;
            letter-spacing: 0.5px;
        }

        .title {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
        }

        .title-ring {
            width: 50px;
            height: 50px;
            filter:
                drop-shadow(0 0 12px rgba(255,215,0,.8))
                drop-shadow(0 0 24px rgba(255,215,0,.4));
        }

        p { color: #cfcfea; }

        input {
            margin: 22px 0;
            color: white;
        }

        button {
            background: linear-gradient(135deg, #ff2a6d, #7c3aed);
            color: white;
            border: none;
            padding: 15px 26px;
            border-radius: 14px;
            font-size: 16px;
            cursor: pointer;
            font-weight: bold;
            box-shadow: 0 10px 30px rgba(255, 42, 109, 0.35);
        }

        button:hover { transform: translateY(-1px); }

        .mode-title {
            margin-top: 14px;
            margin-bottom: 8px;
            color: #d8d8ff;
            font-weight: bold;
            text-align: left;
        }

        .source-switch {
            margin: 18px 0 10px;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }

        .source-option {
            padding: 13px 14px;
            border-radius: 14px;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.12);
            cursor: pointer;
            font-weight: bold;
            color: #d8d8ff;
            transition: 0.2s ease;
        }

        .source-option.active {
            color: white;
            background: linear-gradient(135deg, rgba(255,42,109,.65), rgba(124,58,237,.65));
            border-color: rgba(255,255,255,.42);
            box-shadow: 0 0 18px rgba(255,42,109,.35);
        }

        .source-option.disabled {
            opacity: 0.65;
            cursor: not-allowed;
            position: relative;
        }

        .source-option.disabled:hover {
            transform: none;
        }

        .coming-soon-card {
            margin: 14px 0 8px;
            padding: 16px;
            border-radius: 16px;
            text-align: left;
            background: rgba(255, 215, 0, 0.08);
            border: 1px solid rgba(255, 215, 0, 0.20);
            color: #ffe66d;
        }

        .coming-soon-card strong {
            display: block;
            margin-bottom: 8px;
            font-size: 16px;
            color: #fff2a8;
        }

        .coming-soon-card ul {
            margin: 8px 0 0 18px;
            padding: 0;
            color: #f4e9a6;
            line-height: 1.55;
        }

        .source-input {
            display: none;
        }

        .source-input.active {
            display: block;
        }

        .hidden {
            display: none !important;
        }

        .edit-settings {
            margin: 18px 0 8px;
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 14px;
            text-align: left;
        }

        .edit-note {
            margin-top: 12px;
            padding: 12px;
            border-radius: 14px;
            background: rgba(255, 215, 0, 0.08);
            border: 1px solid rgba(255, 215, 0, 0.18);
            color: #ffe66d;
            font-size: 13px;
            text-align: left;
        }

        .url-input {
            width: 100%;
            padding: 13px 14px;
            border-radius: 14px;
            border: 1px solid rgba(255,255,255,0.16);
            background: #111827;
            color: white;
            font-size: 15px;
            outline: none;
            margin: 12px 0 22px;
        }

        .url-input::placeholder {
            color: #8d8db5;
        }

        .settings {
            margin: 18px 0 8px;
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 14px;
            text-align: left;
        }

        .setting-card {
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 16px;
            padding: 14px;
        }

        .setting-card label {
            display: block;
            font-size: 14px;
            color: #d8d8ff;
            margin-bottom: 8px;
            font-weight: bold;
        }

        select {
            width: 100%;
            padding: 11px 12px;
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.16);
            background: #111827;
            color: white;
            font-size: 15px;
            outline: none;
        }

        .webcam-area {
            margin: 18px 0 8px;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
            text-align: left;
        }

        .screen-preview {
            position: relative;
            height: 220px;
            border-radius: 16px;
            overflow: hidden;
            background:
                linear-gradient(135deg, rgba(5,217,232,.14), rgba(255,42,109,.14)),
                #0f172a;
            border: 1px solid rgba(255,255,255,0.14);
        }

        .screen-title {
            position: absolute;
            left: 12px;
            top: 10px;
            color: rgba(255,255,255,0.55);
            font-size: 12px;
        }

        .webcam-dot {
            position: absolute;
            width: 52px;
            height: 38px;
            border-radius: 10px;
            border: 2px solid rgba(255,255,255,0.35);
            background: rgba(124, 58, 237, 0.25);
            color: white;
            font-weight: bold;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: 0.2s ease;
        }

        .webcam-dot:hover {
            transform: scale(1.08);
            background: rgba(255,42,109,.45);
        }

        .webcam-dot.active {
            background: linear-gradient(135deg, #ff2a6d, #7c3aed);
            border-color: white;
            box-shadow: 0 0 18px rgba(255,42,109,.65);
        }

        .pos-1 { left: 12px; top: 36px; }
        .pos-2 { right: 12px; top: 36px; }
        .pos-5 { left: 12px; top: 91px; }
        .pos-6 { right: 12px; top: 91px; }
        .pos-3 { left: 12px; bottom: 12px; }
        .pos-4 { right: 12px; bottom: 12px; }

        .webcam-controls {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .no-webcam {
            display: flex;
            gap: 8px;
            align-items: center;
            color: #d8d8ff;
            font-size: 14px;
        }

        .no-webcam input { margin: 0; }

        .loader {
            display: none;
            margin-top: 28px;
        }

        .stage {
            margin-bottom: 14px;
            font-size: 18px;
            color: #ffffff;
            font-weight: bold;
        }

        .progress-wrap {
            position: relative;
            width: 100%;
            height: 34px;
            background: #111827;
            border-radius: 999px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.15);
        }

        .progress-bar {
            width: 0%;
            height: 100%;
            border-radius: 999px;
            background:
                radial-gradient(circle at 18% 50%, rgba(255,255,255,.85), transparent 24%),
                radial-gradient(circle at 38% 55%, rgba(230,230,230,.7), transparent 23%),
                radial-gradient(circle at 60% 45%, rgba(255,255,255,.6), transparent 21%),
                radial-gradient(circle at 82% 55%, rgba(210,210,210,.55), transparent 24%),
                linear-gradient(90deg, rgba(235,235,235,.95), rgba(160,160,160,.75));
            filter: blur(2px);
            opacity: 0.9;
            transition: width 0.4s ease;
        }

        .sonic {
            position: absolute;
            top: -18px;
            left: 0%;
            width: 78px;
            transform: translateX(-20px);
            transition: left 0.4s ease;
            image-rendering: auto;
            z-index: 10;
        }

        .percent {
            margin-top: 14px;
            font-size: 22px;
            font-weight: bold;
        }

        .time {
            margin-top: 8px;
            color: #bdbde5;
            font-size: 14px;
        }

        .result {
            margin-top: 28px;
            text-align: left;
        }

        .ring-icon {
            width: 28px;
            height: 28px;
            vertical-align: middle;
            margin-right: 10px;
            filter: drop-shadow(0 0 10px rgba(255, 220, 0, .65));
        }

        .clip-card {
            margin: 14px 0;
            padding: 14px;
            border-radius: 16px;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.12);
        }

        .clip-title {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
            font-weight: bold;
            color: #ffffff;
        }

        .clip-preview {
            width: 100%;
            max-height: 520px;
            border-radius: 14px;
            background: #050814;
            border: 1px solid rgba(255,255,255,0.12);
            box-shadow: 0 12px 32px rgba(0,0,0,.28);
            display: block;
            margin-bottom: 10px;
        }

        .clip-link {
            display: flex;
            align-items: center;
            padding: 12px 14px;
            margin: 10px 0;
            border-radius: 12px;
            text-decoration: none;
            color: white;
            background: rgba(124, 58, 237, 0.25);
            border: 1px solid rgba(255,255,255,0.12);
        }

        .clip-link:hover { background: rgba(124, 58, 237, 0.45); }

        .zip-link {
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 15px 16px;
            margin: 14px 0 18px;
            border-radius: 14px;
            text-decoration: none;
            color: #111827;
            background: linear-gradient(135deg, #ffe66d, #ffb703);
            border: 1px solid rgba(255,255,255,0.25);
            font-weight: bold;
            box-shadow: 0 10px 28px rgba(255, 215, 0, 0.26);
        }

        .zip-link:hover {
            transform: translateY(-1px);
        }


        .subtitle-report {
            margin-top: 10px;
            padding: 12px;
            border-radius: 12px;
            background: rgba(0,0,0,0.22);
            border: 1px solid rgba(255,255,255,0.10);
        }

        .subtitle-quality {
            font-weight: bold;
            margin-bottom: 8px;
            color: #ffe66d;
        }

        .subtitle-text {
            width: 100%;
            min-height: 76px;
            resize: vertical;
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.14);
            background: #0f172a;
            color: white;
            padding: 10px;
            font-size: 14px;
            outline: none;
            font-family: Arial, sans-serif;
        }



        .hint {
            margin-top: 12px;
            font-size: 13px;
            color: #aaa9d6;
        }
    </style>
</head>
<body>
    <div class="box-wrapper">
        <img src="/static/sonic_hero.png" class="hero-sonic">

        <div class="box">
        <h1 class="title">
    Sonic Cuts
    <img src="/static/ring.gif" class="title-ring">
</h1>
        <p>Загрузи стрим или вставь ссылку — Sonic найдёт хайлайты и сделает Shorts.</p>

        <div class="mode-title">Тип проекта</div>

        <div class="source-switch">
            <div id="shortsModeBtn" class="source-option active" onclick="setProjectMode('shorts')">
                🎬 Шортсы
            </div>

            <div id="editModeBtn" class="source-option disabled" title="Функция находится в разработке">
                ⚡ Авто-эдит 🚧
            </div>
        </div>

        <div class="coming-soon-card">
            <strong>🚧 Авто-эдит в разработке</strong>
            Скоро здесь появится отдельный режим для создания эдитов:
            <ul>
                <li>монтаж под бит музыки;</li>
                <li>velocity / speed ramp эффекты;</li>
                <li>cinematic-стили;</li>
                <li>AI-сценарии для эдитов.</li>
            </ul>
        </div>

        <div class="mode-title">Источник видео</div>

        <div class="source-switch">
            <div id="fileSourceBtn" class="source-option active" onclick="setSourceMode('file')">
                📁 Загрузить файл
            </div>

            <div id="urlSourceBtn" class="source-option" onclick="setSourceMode('url')">
                🔗 YouTube / Twitch ссылка
            </div>
        </div>

        <div id="fileSourceBlock" class="source-input active">
            <input id="file" type="file" accept="video/*">
        </div>

        <div id="urlSourceBlock" class="source-input">
            <input
                id="videoUrl"
                class="url-input"
                type="text"
                placeholder="Вставь ссылку на YouTube или Twitch"
            >
        </div>

        <div class="hint">
            Максимальный размер видео для MVP: 2 ГБ.
        </div>

        <div id="shortsSettings" class="settings shorts-only">
            <div class="setting-card">
                <label for="clipCount">Количество клипов</label>
                <select id="clipCount">
                    <option value="3">3 клипа</option>
                    <option value="5" selected>5 клипов</option>
                    <option value="10">10 клипов</option>
                </select>
            </div>

            <div class="setting-card">
                <label for="clipLength">Длина клипа</label>
                <select id="clipLength">
                    <option value="15">15 секунд</option>
                    <option value="30" selected>30 секунд</option>
                    <option value="45">45 секунд</option>
                </select>
            </div>

            <div class="setting-card">
                <label for="highlightMode">Режим поиска</label>
                <select id="highlightMode">
                    <option value="balanced" selected>⚖️ Сбалансированный</option>
                    <option value="reactions">🔥 Реакции</option>
                    <option value="loud">🔊 Громкие моменты</option>
                </select>
            </div>
        </div>

        <div id="shortsWebcamArea" class="webcam-area shorts-only">
            <div class="setting-card">
                <label>Позиция вебки</label>

                <div class="screen-preview">
                    <div class="screen-title">Экран стрима</div>

                    <button type="button" class="webcam-dot pos-1 active" onclick="selectWebcamPosition('top_left', this)">1</button>
                    <button type="button" class="webcam-dot pos-2" onclick="selectWebcamPosition('top_right', this)">2</button>
                    <button type="button" class="webcam-dot pos-5" onclick="selectWebcamPosition('middle_left', this)">5</button>
                    <button type="button" class="webcam-dot pos-6" onclick="selectWebcamPosition('middle_right', this)">6</button>
                    <button type="button" class="webcam-dot pos-3" onclick="selectWebcamPosition('bottom_left', this)">3</button>
                    <button type="button" class="webcam-dot pos-4" onclick="selectWebcamPosition('bottom_right', this)">4</button>
                </div>
            </div>

            <div class="setting-card webcam-controls">
                <div>
                    <label for="webcamSize">Размер вебки</label>
                    <select id="webcamSize">
                        <option value="small">Маленькая</option>
                        <option value="medium" selected>Средняя</option>
                        <option value="large">Большая</option>
                    </select>
                </div>

                <label class="no-webcam">
                    <input id="noWebcam" type="checkbox" onchange="toggleNoWebcam()">
                    Без вебки
                </label>

                <label class="no-webcam">
                    <input id="enableSubtitles" type="checkbox" checked>
                    Красивые субтитры
                </label>

                <div class="hint">
                    Выбери, где вебка находится в исходном стриме. Sonic вырежет её и поставит сверху в Shorts.
                </div>
            </div>
        </div>

        <div id="shortsHint" class="hint shorts-only">Совет: 5 клипов по 30 секунд — самый стабильный вариант.</div>

        <div id="editSettings" class="edit-settings edit-only hidden">
            <div class="setting-card">
                <label for="editDuration">Длина эдита</label>
                <select id="editDuration">
                    <option value="15">15 секунд</option>
                    <option value="25" selected>25 секунд</option>
                    <option value="35">35 секунд</option>
                </select>
            </div>

            <div class="setting-card">
                <label for="editStyle">Стиль эдита</label>
                <select id="editStyle">
                    <option value="aggressive" selected>🔥 Агрессивный</option>
                    <option value="smooth">💜 Плавный</option>
                    <option value="gaming">🎮 Gaming</option>
                </select>
            </div>

            <div class="setting-card">
                <label for="editIntensity">Интенсивность</label>
                <select id="editIntensity">
                    <option value="low">Лёгкая</option>
                    <option value="medium" selected>Средняя</option>
                    <option value="high">Максимальная</option>
                </select>
            </div>
        </div>

        <div id="editNote" class="edit-note edit-only hidden">
            ⚡ В режиме авто-эдита Sonic сам выберет сильные моменты, нарежет короткие фрагменты и соберёт один динамичный edit.mp4.
            Вебка, субтитры и отдельные клипы здесь не используются.
        </div>

        <br>
        <button onclick="uploadVideo()">Создать шортсы</button>

        <div id="loader" class="loader">
            <div id="stage" class="stage">Подготовка...</div>

            <div class="progress-wrap">
                <div id="progressBar" class="progress-bar"></div>
                <img id="sonic" class="sonic" src="/static/sonic.gif">
            </div>

            <div id="percent" class="percent">0%</div>
            <div id="time" class="time">Прошло: 0 сек</div>
        </div>

        <audio id="finishSound" src="/static/ring.mp3" preload="auto"></audio>

        <div id="result" class="result"></div>
        </div>
    </div>

    <script>
        let progressTimer = null;
        let seconds = 0;
        let fakeProgress = 0;
        let selectedWebcamPosition = "top_left";
        let sourceMode = "file";
        let projectMode = "shorts";

        const stages = [
            { percent: 5, text: "📥 Загружаю видео..." },
            { percent: 18, text: "🎧 Анализирую звук..." },
            { percent: 34, text: "🔥 Ищу хайлайты..." },
            { percent: 52, text: "🎬 Рендерю клипы..." },
            { percent: 72, text: "📝 Добавляю субтитры..." },
            { percent: 88, text: "📦 Собираю ZIP..." },
            { percent: 96, text: "🏁 Почти готово..." }
        ];

        const sonicPhrases = [
            "📥 Загружаю видео...",
            "🎧 Анализирую звук...",
            "🔥 Ищу хайлайты...",
            "🎬 Рендерю клипы...",
            "📝 Добавляю субтитры...",
            "📦 Собираю ZIP...",
            "🏁 Почти готово..."
        ];

        function setProjectMode(mode) {
            // Авто-эдит временно отключён.
            projectMode = "shorts";

            const shortsBtn = document.getElementById("shortsModeBtn");
            const editBtn = document.getElementById("editModeBtn");
            const mainButton = document.querySelector("button[onclick='uploadVideo()']");

            const shortsBlocks = document.querySelectorAll(".shorts-only");
            const editBlocks = document.querySelectorAll(".edit-only");

            shortsBtn.classList.add("active");
            editBtn.classList.remove("active");

            shortsBlocks.forEach((block) => block.classList.remove("hidden"));
            editBlocks.forEach((block) => block.classList.add("hidden"));

            if (mainButton) {
                mainButton.innerText = "Создать шортсы";
            }
        }

        function setSourceMode(mode) {
            sourceMode = mode;

            const fileBtn = document.getElementById("fileSourceBtn");
            const urlBtn = document.getElementById("urlSourceBtn");
            const fileBlock = document.getElementById("fileSourceBlock");
            const urlBlock = document.getElementById("urlSourceBlock");

            if (mode === "file") {
                fileBtn.classList.add("active");
                urlBtn.classList.remove("active");
                fileBlock.classList.add("active");
                urlBlock.classList.remove("active");
            } else {
                urlBtn.classList.add("active");
                fileBtn.classList.remove("active");
                urlBlock.classList.add("active");
                fileBlock.classList.remove("active");
            }
        }

        function selectWebcamPosition(position, element) {
            selectedWebcamPosition = position;
            document.getElementById("noWebcam").checked = false;

            document.querySelectorAll(".webcam-dot").forEach((dot) => {
                dot.classList.remove("active");
            });

            element.classList.add("active");
        }

        function toggleNoWebcam() {
            const noWebcam = document.getElementById("noWebcam").checked;

            document.querySelectorAll(".webcam-dot").forEach((dot) => {
                dot.classList.remove("active");
            });

            if (!noWebcam) {
                const firstDot = document.querySelector(".pos-1");
                firstDot.classList.add("active");
                selectedWebcamPosition = "top_left";
            }
        }

        function setProgress(value) {
            const bar = document.getElementById("progressBar");
            const sonic = document.getElementById("sonic");
            const percent = document.getElementById("percent");

            value = Math.min(value, 95);
            bar.style.width = value + "%";
            sonic.style.left = value + "%";
            percent.innerText = Math.floor(value) + "%";
        }

        function startFakeProgress() {
            seconds = 0;
            fakeProgress = 0;

            if (progressTimer) {
                clearInterval(progressTimer);
            }

            document.getElementById("stage").innerText = "📥 Загружаю видео...";

            progressTimer = setInterval(() => {
                seconds += 1;

                let targetProgress = 0;

                if (seconds < 8) {
                    targetProgress = 5 + seconds * 1.6;
                } else if (seconds < 22) {
                    targetProgress = 18 + (seconds - 8) * 1.05;
                } else if (seconds < 45) {
                    targetProgress = 34 + (seconds - 22) * 0.8;
                } else if (seconds < 85) {
                    targetProgress = 52 + (seconds - 45) * 0.45;
                } else if (seconds < 130) {
                    targetProgress = 72 + (seconds - 85) * 0.24;
                } else {
                    targetProgress = 88 + (seconds - 130) * 0.06;
                }

                fakeProgress = Math.min(targetProgress, 96);

                setProgress(fakeProgress);

                let currentStage = stages[0].text;

                for (const stageItem of stages) {
                    if (fakeProgress >= stageItem.percent) {
                        currentStage = stageItem.text;
                    }
                }

                document.getElementById("stage").innerText = currentStage;
                document.getElementById("time").innerText = "Прошло: " + seconds + " сек";
            }, 1000);
        }

        function launchConfetti() {
            if (typeof confetti !== "function") {
                return;
            }

            confetti({
                particleCount: 250,
                spread: 180,
                origin: { y: 0.6 }
            });

            setTimeout(() => {
                confetti({
                    particleCount: 180,
                    spread: 120,
                    origin: { x: 0, y: 0.65 }
                });

                confetti({
                    particleCount: 180,
                    spread: 120,
                    origin: { x: 1, y: 0.65 }
                });
            }, 700);

            setTimeout(() => {
                confetti({
                    particleCount: 220,
                    spread: 160,
                    origin: { y: 0.35 }
                });
            }, 1400);
        }

        function finishProgress() {
            clearInterval(progressTimer);

            document.getElementById("progressBar").style.width = "100%";
            document.getElementById("sonic").style.left = "100%";
            document.getElementById("percent").innerText = "100%";
            document.getElementById("stage").innerText = "✅ ГОТОВО!";

            launchConfetti();

            const finishSound = document.getElementById("finishSound");
            if (finishSound) {
                finishSound.currentTime = 0;
                finishSound.play().catch(() => {});
            }
        }

        async function uploadVideo() {
            const fileInput = document.getElementById("file");
            const videoUrlInput = document.getElementById("videoUrl");
            const result = document.getElementById("result");
            const loader = document.getElementById("loader");
            const clipCount = document.getElementById("clipCount").value;
            const clipLength = document.getElementById("clipLength").value;
            const highlightMode = document.getElementById("highlightMode").value;
            const webcamSize = document.getElementById("webcamSize").value;
            const noWebcam = document.getElementById("noWebcam").checked;
            const enableSubtitles = document.getElementById("enableSubtitles").checked;
            const editDuration = document.getElementById("editDuration")?.value || "25";
            const editStyle = document.getElementById("editStyle")?.value || "aggressive";
            const editIntensity = document.getElementById("editIntensity")?.value || "medium";

            if (sourceMode === "file" && !fileInput.files.length) {
                alert("Выбери видео");
                return;
            }

            if (sourceMode === "url" && !videoUrlInput.value.trim()) {
                alert("Вставь ссылку на YouTube или Twitch");
                return;
            }

            const formData = new FormData();
            formData.append("project_mode", projectMode);
            formData.append("source_mode", sourceMode);

            if (sourceMode === "file") {
                formData.append("file", fileInput.files[0]);
            } else {
                formData.append("video_url", videoUrlInput.value.trim());
            }
            if (projectMode === "edit") {
                formData.append("clip_count", "10");
                formData.append("clip_length", "20");
                formData.append("highlight_mode", "reactions");
                formData.append("webcam_position", "none");
                formData.append("webcam_size", "medium");
                formData.append("enable_subtitles", "false");
                formData.append("edit_duration", editDuration);
                formData.append("edit_style", editStyle);
                formData.append("edit_intensity", editIntensity);
            } else {
                formData.append("clip_count", clipCount);
                formData.append("clip_length", clipLength);
                formData.append("highlight_mode", highlightMode);
                formData.append("webcam_position", noWebcam ? "none" : selectedWebcamPosition);
                formData.append("webcam_size", webcamSize);
                formData.append("enable_subtitles", enableSubtitles ? "true" : "false");
            }

            result.innerHTML = "";
            loader.style.display = "block";
            setProgress(0);
            startFakeProgress();

            try {
                const response = await fetch("/upload", {
                    method: "POST",
                    body: formData
                });

                let data = null;

                try {
                    data = await response.json();
                } catch (jsonError) {
                    data = {
                        status: "error",
                        message: "Сервер вернул ошибку без JSON"
                    };
                }

                finishProgress();

                if (!response.ok || data.status !== "success") {
                    result.innerHTML = data.message || "Ошибка при обработке";
                    return;
                }

                let html = projectMode === "edit"
                    ? "<h3>⚡ Готовый авто-эдит:</h3>"
                    : "<h3>🟡 Готовые клипы:</h3>";

                if (data.zip_url) {
                    html += `
                        <a class="zip-link" href="${data.zip_url}" download>
                            📦 Скачать все клипы ZIP
                        </a>
                    `;
                }

                data.clips.forEach((clip, index) => {
                    html += `
                        <div class="clip-card">
                            <div class="clip-title">
                                ${projectMode === "edit" ? "⚡ Авто-эдит" : `🔥 Хайлайт #${index + 1}`}
                            </div>

                            <video class="clip-preview" controls preload="metadata">
                                <source src="${clip.url}" type="video/mp4">
                                Ваш браузер не поддерживает просмотр видео.
                            </video>

                            <a class="clip-link" href="${clip.url}" download>
                                <img class="ring-icon" src="/static/ring.gif">
                                🟣 Скачать клип
                            </a>

                            ${data.subtitle_reports && data.subtitle_reports[index] ? `
                                <div class="subtitle-report">
                                    <div class="subtitle-quality">
                                        🎙 Распознавание: ${data.subtitle_reports[index].quality}/100
                                    </div>

                                    <textarea class="subtitle-text" readonly>${data.subtitle_reports[index].text || "Субтитры не распознаны"}</textarea>
                                </div>
                            ` : ""}
                        </div>
                    `;
                });

                result.innerHTML = html;

            } catch (error) {
                clearInterval(progressTimer);
                result.innerHTML = "Ошибка: " + error;
            }
        }
    </script>
</body>
</html>
    """





def get_file_size_mb(file_path):
    if not os.path.exists(file_path):
        return 0

    return round(os.path.getsize(file_path) / (1024 * 1024), 2)


def validate_video_size(file_path):
    size_bytes = os.path.getsize(file_path)
    size_mb = round(size_bytes / (1024 * 1024), 2)

    if size_bytes > MAX_VIDEO_SIZE_BYTES:
        try:
            os.remove(file_path)
        except Exception:
            pass

        raise ValueError(
            f"Видео слишком большое: {size_mb} МБ. "
            f"Максимум: {MAX_VIDEO_SIZE_MB} МБ."
        )

    print("VIDEO SIZE OK:", f"{size_mb} MB")


def safe_remove_file(file_path):
    try:
        if os.path.isfile(file_path):
            os.remove(file_path)
            return True

    except PermissionError:
        print(f"SKIP DELETE, FILE IN USE: {file_path}")

    except Exception as error:
        print(f"DELETE ERROR {file_path}: {error}")

    return False


def cleanup_folder(folder_path, keep_extensions=None, keep_filenames=None):
    if not os.path.exists(folder_path):
        return

    keep_extensions = keep_extensions or set()
    keep_filenames = keep_filenames or set()

    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)

        if not os.path.isfile(file_path):
            continue

        if filename in keep_filenames:
            continue

        _, extension = os.path.splitext(filename)

        if extension.lower() in keep_extensions:
            continue

        safe_remove_file(file_path)


def cleanup_before_processing():
    # Перед новой обработкой чистим старые результаты.
    # Если клип открыт браузером — не падаем, просто пропускаем.
    cleanup_folder("clips")


def cleanup_after_processing(current_video_path=None):
    # temp чистим всегда
    cleanup_folder("temp")

    # uploads чистим после обработки, чтобы сервер не забивался видеофайлами.
    # Текущий файл тоже можно удалять, потому что рендер уже закончен.
    cleanup_folder("uploads")


def create_clips_zip():
    zip_path = os.path.join("clips", "sonic_clips.zip")

    if os.path.exists(zip_path):
        try:
            os.remove(zip_path)
        except PermissionError:
            print("ZIP DELETE SKIPPED, FILE IN USE:", zip_path)

    mp4_files = []

    for filename in sorted(os.listdir("clips")):
        if filename.endswith(".mp4"):
            mp4_files.append(filename)

    if not mp4_files:
        return None

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for filename in mp4_files:
            file_path = os.path.join("clips", filename)
            zip_file.write(file_path, arcname=filename)

    print("ZIP CREATED:", zip_path)

    return zip_path


def download_video_from_url(video_url):
    if not video_url:
        raise ValueError("Пустая ссылка")

    os.makedirs("uploads", exist_ok=True)

    output_template = os.path.join(
        "uploads",
        f"url_video_{uuid.uuid4().hex}.%(ext)s"
    )

    command = [
        "python",
        "-m",
        "yt_dlp",
        "-f",
        "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "--merge-output-format",
        "mp4",
        "-o",
        output_template,
        video_url
    ]

    print("DOWNLOADING URL VIDEO...")
    print("URL:", video_url)

    result = subprocess.run(
        command,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print("YT-DLP ERROR:", result.stderr)
        raise RuntimeError("Не удалось скачать видео по ссылке. Проверь ссылку или установку yt-dlp.")

    downloaded_files = []

    for filename in os.listdir("uploads"):
        if filename.startswith("url_video_") and filename.endswith(".mp4"):
            file_path = os.path.join("uploads", filename)
            downloaded_files.append(file_path)

    if not downloaded_files:
        raise RuntimeError("Видео скачалось, но mp4-файл не найден.")

    downloaded_files = sorted(
        downloaded_files,
        key=lambda path: os.path.getmtime(path),
        reverse=True
    )

    video_path = downloaded_files[0]

    print("DOWNLOADED:", video_path)

    return video_path


@app.post("/upload")
async def upload_video(
    file: UploadFile | None = File(None),
    project_mode: str = Form("shorts"),
    source_mode: str = Form("file"),
    video_url: str = Form(""),
    clip_count: int = Form(5),
    clip_length: int = Form(30),
    highlight_mode: str = Form("balanced"),
    webcam_position: str = Form("top_left"),
    webcam_size: str = Form("medium"),
    enable_subtitles: str = Form("true")
):

    clip_count = max(1, min(int(clip_count), 10))
    clip_length = max(10, min(int(clip_length), 60))
    subtitles_enabled = str(enable_subtitles).lower() == "true"

    allowed_project_modes = {
        "shorts",
        "edit"
    }

    if project_mode not in allowed_project_modes:
        project_mode = "shorts"

    # Авто-эдит пока отключён для публичного MVP.
    print("STATUS: 🎬 Starting render")

    if project_mode == "edit":
        project_mode = "shorts"

    allowed_modes = {
        "balanced",
        "reactions",
        "loud"
    }

    if highlight_mode not in allowed_modes:
        highlight_mode = "balanced"

    allowed_positions = {
        "top_left",
        "top_right",
        "middle_left",
        "middle_right",
        "bottom_left",
        "bottom_right",
        "none"
    }

    allowed_sizes = {
        "small",
        "medium",
        "large"
    }

    if webcam_position not in allowed_positions:
        webcam_position = "top_left"

    if webcam_size not in allowed_sizes:
        webcam_size = "medium"

    cleanup_before_processing()

    if source_mode not in {"file", "url"}:
        source_mode = "file"

    print("STATUS: 📥 Preparing video source")

    if source_mode == "file":
        if file is None:
            raise ValueError("Файл не был загружен")

        video_path = os.path.join("uploads", file.filename)

        with open(video_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        validate_video_size(video_path)

    else:
        video_path = download_video_from_url(video_url)
        validate_video_size(video_path)

    print("STATUS: 🎧 Starting audio analysis")
    print("START ANALYZE")
    print("SETTINGS:", {
        "project_mode": project_mode,
        "source_mode": source_mode,
        "clip_count": clip_count,
        "clip_length": clip_length,
        "highlight_mode": highlight_mode,
        "webcam_position": webcam_position,
        "webcam_size": webcam_size,
        "subtitles_enabled": subtitles_enabled
    })

    print("STATUS: 🔥 Searching highlights")

    clips = find_loud_moments(
        video_path,
        max_clips=clip_count,
        clip_length=clip_length,
        mode=highlight_mode
    )

    print("LOUD MOMENTS:", clips)

    subtitle_reports = []
    result_clips = []

    if project_mode == "edit":
        print("PROJECT MODE EDIT SELECTED: creating auto edit")

        edit_path = create_auto_edit(
            video_path,
            clips
        )

        if edit_path is not None:
            result_clips.append({
                "name": os.path.basename(edit_path),
                "url": f"/clips/{os.path.basename(edit_path)}"
            })

    else:
        subtitle_reports = create_shorts(
            video_path,
            clips,
            webcam_position=webcam_position,
            webcam_size=webcam_size,
            subtitles_enabled=subtitles_enabled
        )

        if subtitle_reports is None:
            subtitle_reports = []

        for filename in sorted(os.listdir("clips")):
            if filename.endswith(".mp4"):
                result_clips.append({
                    "name": filename,
                    "url": f"/clips/{filename}"
                })

    cleanup_after_processing(current_video_path=video_path)

    print("STATUS: 📦 Creating ZIP archive")
    zip_path = create_clips_zip()
    zip_url = None

    if zip_path is not None:
        zip_url = "/clips/sonic_clips.zip"

    print("STATUS: ✅ Done")

    return {
        "status": "success",
        "project_mode": project_mode,
        "clips_created": len(result_clips),
        "clips": result_clips,
        "zip_url": zip_url,
        "subtitle_reports": subtitle_reports
    }
