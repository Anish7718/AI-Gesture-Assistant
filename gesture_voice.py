import cv2
import mediapipe as mp
import time
import threading
import queue
import subprocess
import sys
import datetime
from collections import deque

# ============================================================
#  CROSS-PLATFORM TTS
# ============================================================
PLATFORM = sys.platform
SPEED_LEVELS = [120, 155, 200]
SPEED_LABELS = ["Slow", "Normal", "Fast"]
voice_speed_idx = 1

def _speak_blocking(text):
    rate = SPEED_LEVELS[voice_speed_idx]
    try:
        if PLATFORM == "win32":
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', rate)
            engine.setProperty('volume', 1.0)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        elif PLATFORM == "darwin":
            subprocess.run(["say", "-r", str(int(rate * 0.9)), text],
                           check=True, timeout=15)
        else:
            for binary in ["espeak-ng", "espeak"]:
                if subprocess.run(["which", binary], capture_output=True).returncode == 0:
                    subprocess.run([binary, "-s", str(rate), "-v", "en", text],
                                   check=True, timeout=15)
                    return
            proc = subprocess.Popen(["festival", "--tts"], stdin=subprocess.PIPE)
            proc.communicate(input=text.encode())
    except FileNotFoundError:
        print(f"[TTS] No engine found. Text: {text}")
    except subprocess.TimeoutExpired:
        print(f"[TTS] Timeout: {text}")
    except Exception as e:
        print(f"[TTS ERROR] {e}")

_tts_q = queue.Queue()
def _tts_worker():
    while True:
        item = _tts_q.get()
        if item is None:
            break
        _speak_blocking(item)
        _tts_q.task_done()

_tts_thread = threading.Thread(target=_tts_worker, daemon=True)
_tts_thread.start()

def speak(text):
    print(f"[VOICE] >> {text}")
    _tts_q.put(str(text))

# ============================================================
#  MEDIAPIPE
# ============================================================
mp_hands = mp.solutions.hands
detector = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.75,
    min_tracking_confidence=0.75,
)
mp_draw = mp.solutions.drawing_utils

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

# ============================================================
#  GESTURE DETECTION
# ============================================================
def detect_gesture(landmarks):
    lm = landmarks
    thumb = (1 if lm[4].x < lm[3].x else 0) if lm[0].x < lm[5].x \
            else (1 if lm[4].x > lm[3].x else 0)
    TIPS = [8, 12, 16, 20]
    PIPS = [6, 10, 14, 18]
    f = [1 if lm[TIPS[i]].y < lm[PIPS[i]].y - 0.025 else 0 for i in range(4)]
    combo = [thumb, f[0], f[1], f[2], f[3]]

    if combo == [1, 0, 0, 0, 0]: return "Yes"
    if combo == [0, 0, 0, 0, 1]: return "No"
    if combo == [0, 1, 1, 0, 0]: return "Peace"
    if combo == [1, 1, 1, 1, 1]: return "Stop"
    if combo == [0, 1, 0, 0, 0]: return "Point"
    if combo == [0, 0, 0, 0, 0]: return "Clear"
    if combo == [0, 1, 1, 1, 1]: return "Speak"
    if combo == [1, 1, 0, 0, 0]: return "Undo"
    return "Unknown"

WORD_MAP = {"Yes": "Yes", "No": "No", "Peace": "Peace",
            "Stop": "Stop", "Point": "Point"}

# ============================================================
#  STATE
# ============================================================
sentence      = ""
prev_stable   = "None"
last_action_t = 0.0
COOLDOWN_SEC  = 1.8
STABLE_FRAMES = 10
_gbuf         = deque(maxlen=STABLE_FRAMES)

def get_stable(raw):
    _gbuf.append(raw)
    if len(_gbuf) == STABLE_FRAMES and len(set(_gbuf)) == 1:
        return _gbuf[0]
    return "Pending"

gesture_log      = deque(maxlen=5)
session_start    = time.time()
total_gestures   = 0
total_words      = 0
total_sentences  = 0
fps_times        = deque(maxlen=30)
session_log_lines = []

def log_event(s):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    session_log_lines.append(f"[{ts}] {s}")

def save_session():
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fn  = f"gesture_session_{ts}.txt"
    dur = int(time.time() - session_start)
    with open(fn, "w") as f:
        f.write("=" * 50 + "\n")
        f.write("  AI GESTURE ASSISTANT — SESSION LOG\n")
        f.write("=" * 50 + "\n")
        f.write(f"Date     : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Duration : {dur//60}m {dur%60}s\n")
        f.write(f"Gestures : {total_gestures}\n")
        f.write(f"Words    : {total_words}\n")
        f.write(f"Sentences: {total_sentences}\n")
        f.write(f"Final    : {sentence.strip() or '(empty)'}\n")
        f.write("-" * 50 + "\n")
        f.write("\n".join(session_log_lines) + "\n")
    print(f"[SAVED] {fn}")
    speak(f"Session saved")

# ============================================================
#  COLORS (BGR)
# ============================================================
W  = (255, 255, 255)
YL = (0,   220, 220)
GN = (50,  220, 80)
RD = (60,  60,  230)
CY = (220, 200, 0)
GR = (140, 140, 140)
OR = (0,   160, 255)
LM = (0,   255, 128)
PK = (180, 100, 255)
BK = (0,   0,   0)

def txt(img, s, pos, scale=0.65, color=W, thick=1):
    cv2.putText(img, s, pos, cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, thick, cv2.LINE_AA)

def txt_shadow(img, s, pos, scale=0.65, color=W, thick=1):
    """Text with black shadow — readable on any camera background."""
    x, y = pos
    cv2.putText(img, s, (x+1, y+1), cv2.FONT_HERSHEY_SIMPLEX,
                scale, BK, thick + 1, cv2.LINE_AA)
    cv2.putText(img, s, pos, cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, thick, cv2.LINE_AA)

# ============================================================
#  VIEW MODE
#  fullscreen_mode = True  → camera fills window, minimal HUD overlay
#  fullscreen_mode = False → original layout with side panels
# ============================================================
fullscreen_mode = False   # F key toggles this

# Window setup — resizable so user can drag to any size
cv2.namedWindow("AI Gesture Assistant", cv2.WINDOW_NORMAL)
cv2.resizeWindow("AI Gesture Assistant", 1280, 720)

log_event("Session started")

# ============================================================
#  MAIN LOOP
# ============================================================
while True:
    t_frame_start = time.time()

    ok, frame = cap.read()
    if not ok:
        break

    frame = cv2.flip(frame, 1)
    h, w  = frame.shape[:2]          # actual camera frame size
    rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    res   = detector.process(rgb)

    raw    = "Unknown"
    stable = "Pending"

    if res.multi_hand_landmarks:
        hl = res.multi_hand_landmarks[0]
        mp_draw.draw_landmarks(
            frame, hl, mp_hands.HAND_CONNECTIONS,
            mp_draw.DrawingSpec(color=(0, 255, 100), thickness=2),
            mp_draw.DrawingSpec(color=(255, 220, 0), thickness=2),
        )
        raw    = detect_gesture(hl.landmark)
        stable = get_stable(raw)
    else:
        _gbuf.clear()
        prev_stable = "None"

    now   = time.time()
    ready = (now - last_action_t) >= COOLDOWN_SEC

    # ---- TRIGGER ACTION ----
    if stable not in ("Unknown", "Pending") and ready and stable != prev_stable:

        if stable == "Clear":
            log_event(f"CLEAR — '{sentence.strip()}'")
            sentence = ""
            speak("Sentence cleared")
            total_gestures += 1

        elif stable == "Speak":
            if sentence.strip():
                clean = sentence.strip()
                speak("Full sentence")
                speak(clean)
                log_event(f"SPEAK — '{clean}'")
                total_sentences += 1
                total_gestures  += 1
            else:
                speak("Sentence is empty")

        elif stable == "Undo":
            words = sentence.strip().split()
            if words:
                removed  = words[-1]
                sentence = " ".join(words[:-1]) + (" " if len(words) > 1 else "")
                speak(f"Removed {removed}")
                log_event(f"UNDO — removed '{removed}'")
                total_gestures += 1
            else:
                speak("Nothing to undo")

        elif stable in WORD_MAP:
            word = WORD_MAP[stable]
            sentence += word + " "
            speak(word)
            log_event(f"WORD — '{word}'")
            gesture_log.append((stable, datetime.datetime.now().strftime("%H:%M:%S")))
            total_gestures += 1
            total_words    += 1

        prev_stable   = stable
        last_action_t = now

    # ---- Keyboard ----
    key = cv2.waitKey(1) & 0xFF
    if key == 27:
        break
    elif key == ord('f') or key == ord('F'):
        fullscreen_mode = not fullscreen_mode
        mode_name = "Full Screen" if fullscreen_mode else "Normal"
        speak(f"{mode_name} mode")
        log_event(f"VIEW MODE: {mode_name}")
    elif key == ord('s') or key == ord('S'):
        save_session()
    elif key == ord('v') or key == ord('V'):
        voice_speed_idx = (voice_speed_idx + 1) % 3
        speak(f"Speed {SPEED_LABELS[voice_speed_idx]}")
        log_event(f"SPEED: {SPEED_LABELS[voice_speed_idx]}")

    # FPS
    fps_times.append(time.time())
    fps = (len(fps_times)-1)/(fps_times[-1]-fps_times[0]) if len(fps_times) >= 2 else 0.0
    latency_ms = int((time.time() - t_frame_start) * 1000)

    # ============================================================
    #  CONFIDENCE BAR values (used in both modes)
    # ============================================================
    stable_count = sum(1 for g in _gbuf if g == raw) if raw != "Unknown" else 0
    conf_pct     = stable_count / STABLE_FRAMES
    conf_col     = GN if conf_pct >= 1.0 else (YL if conf_pct > 0.5 else OR)

    if stable not in ("Pending", "Unknown") and res.multi_hand_landmarks:
        gdisplay, gcol = stable, GN
    elif raw != "Unknown" and res.multi_hand_landmarks:
        gdisplay, gcol = raw + "...", YL
    else:
        gdisplay, gcol = "---", GR

    # ============================================================
    #  MODE A: FULLSCREEN — camera fills entire window
    #          Minimal HUD overlay at top + bottom strip only
    # ============================================================
    if fullscreen_mode:

        # No dark overlay — raw camera is the canvas
        canvas = frame.copy()

        # ---- TOP strip (semi-transparent) ----
        top_h = 52
        overlay_top = canvas.copy()
        cv2.rectangle(overlay_top, (0, 0), (w, top_h), (8, 10, 24), -1)
        cv2.addWeighted(overlay_top, 0.55, canvas, 0.45, 0, canvas)

        txt(canvas, "AI Gesture Assistant  [F] Normal mode",
            (10, 33), 0.75, CY, 2)
        dot = GN if res.multi_hand_landmarks else RD
        cv2.circle(canvas, (w - 20, 26), 9, dot, -1)

        # ---- Large gesture name — top left, shadowed ----
        txt_shadow(canvas, gdisplay, (20, 110), 2.0, gcol, 3)

        # Confidence bar below gesture name
        bar_w = 220
        bar_f = int(bar_w * conf_pct)
        cv2.rectangle(canvas, (20, 118), (20 + bar_w, 130), (30, 30, 55), -1)
        if bar_f > 0:
            cv2.rectangle(canvas, (20, 118), (20 + bar_f, 130), conf_col, -1)
        txt_shadow(canvas, f"{int(conf_pct*100)}%", (248, 129), 0.45, conf_col)

        # ---- Sentence box — bottom strip ----
        bot_y   = h - 100
        overlay_bot = canvas.copy()
        cv2.rectangle(overlay_bot, (0, bot_y), (w, h), (8, 10, 24), -1)
        cv2.addWeighted(overlay_bot, 0.60, canvas, 0.40, 0, canvas)

        # Sentence
        txt(canvas, "Built:", (12, bot_y + 28), 0.65, YL, 1)
        disp = (sentence[-72:] if len(sentence) > 72 else sentence) or "(empty)"
        txt(canvas, disp, (90, bot_y + 28), 0.80, W, 2)

        # Cooldown bar
        prog = min((now - last_action_t) / COOLDOWN_SEC, 1.0)
        bw   = int(300 * prog)
        cv2.rectangle(canvas, (12, bot_y + 40), (312, bot_y + 50), (20,20,45), -1)
        if bw > 0:
            cv2.rectangle(canvas, (12, bot_y + 40), (12 + bw, bot_y + 50),
                          LM if prog >= 1.0 else OR, -1)
        txt(canvas, "READY" if prog >= 1.0 else "wait...",
            (320, bot_y + 50), 0.50, LM if prog >= 1.0 else GR)

        # Stats line
        elapsed    = int(now - session_start)
        mins, secs = elapsed // 60, elapsed % 60
        txt(canvas,
            f"{mins:02d}:{secs:02d}  G:{total_gestures}  W:{total_words}  S:{total_sentences}  FPS:{fps:.0f}  Spd:{SPEED_LABELS[voice_speed_idx]}",
            (12, bot_y + 72), 0.48, GR)

        # TTS indicator
        if _tts_q.qsize() > 0:
            txt_shadow(canvas, f"Speaking...", (12, bot_y + 90), 0.50, OR)

        cv2.imshow("AI Gesture Assistant", canvas)

    # ============================================================
    #  MODE B: NORMAL — original layout (740x560 crop + panels)
    # ============================================================
    else:
        # Crop/resize camera to fit normal layout area (left side)
        # Camera shows in left 420px, panels on right 320px
        DISP_W, DISP_H = 1280, 720

        # Resize frame to display dimensions first
        canvas = cv2.resize(frame, (DISP_W, DISP_H))

        # Dark overlay on right panel area only
        ov = canvas.copy()
        cv2.rectangle(ov, (0, 0), (DISP_W, DISP_H), (8, 10, 24), -1)
        canvas = cv2.addWeighted(ov, 0.42, canvas, 0.58, 0)

        # ---- Title bar ----
        cv2.rectangle(canvas, (0, 0), (DISP_W, 58), (15, 15, 35), -1)
        txt(canvas, "AI Gesture Assistant", (400, 38), 1.1, CY, 2)
        txt(canvas, "[F] Fullscreen  [V] Speed  [S] Save  [ESC] Exit",
            (730, 38), 0.48, GR)
        dot = GN if res.multi_hand_landmarks else RD
        cv2.circle(canvas, (DISP_W - 22, 29), 10, dot, -1)
        txt(canvas, "Hand" if res.multi_hand_landmarks else "None",
            (DISP_W - 80, 34), 0.50, dot)

        # ---- Gesture name ----
        txt(canvas, gdisplay, (40, 118), 1.8, gcol, 3)

        # Confidence bar
        bar_w = 220
        bar_f = int(bar_w * conf_pct)
        cv2.rectangle(canvas, (40, 128), (40 + bar_w, 140), (30,30,55), -1)
        if bar_f > 0:
            cv2.rectangle(canvas, (40, 128), (40 + bar_f, 140), conf_col, -1)
        txt(canvas, f"{int(conf_pct*100)}%", (270, 139), 0.44, conf_col)

        # ---- Sentence box ----
        cv2.rectangle(canvas, (30, 150), (DISP_W - 20, 192), (18,18,42), -1)
        cv2.rectangle(canvas, (30, 150), (DISP_W - 20, 192), (70,70,110), 1)
        txt(canvas, "Built:", (38, 177), 0.65, YL)
        disp = (sentence[-80:] if len(sentence) > 80 else sentence) or "(empty)"
        txt(canvas, disp, (115, 177), 0.78, W, 2)

        # Cooldown bar
        prog = min((now - last_action_t) / COOLDOWN_SEC, 1.0)
        bw   = int(300 * prog)
        cv2.rectangle(canvas, (30, 200), (330, 212), (20,20,45), -1)
        if bw > 0:
            cv2.rectangle(canvas, (30, 200), (30 + bw, 212),
                          LM if prog >= 1.0 else OR, -1)
        txt(canvas, "READY" if prog >= 1.0 else "wait...",
            (338, 211), 0.52, LM if prog >= 1.0 else GR)

        if _tts_q.qsize() > 0:
            txt(canvas, f"Speaking... ({_tts_q.qsize()} queued)", (30, 230), 0.52, OR)

        # ---- LEFT panel: History + Stats ----
        px_l = 30
        # History
        cv2.rectangle(canvas, (px_l, 248), (490, 430), (14,14,32), -1)
        cv2.rectangle(canvas, (px_l, 248), (490, 430), (55,55,95), 1)
        txt(canvas, "Recent gestures:", (px_l + 8, 268), 0.60, CY, 1)
        if gesture_log:
            for i, (gname, gtime) in enumerate(reversed(list(gesture_log))):
                y   = 292 + i * 26
                alp = 1.0 - i * 0.18
                col = tuple(int(c * alp) for c in W)
                txt(canvas, f"{gtime}  {gname}", (px_l + 12, y), 0.56, col)
        else:
            txt(canvas, "(no words yet)", (px_l + 12, 292), 0.54, GR)

        # Stats
        cv2.rectangle(canvas, (px_l, 440), (490, 570), (14,14,32), -1)
        cv2.rectangle(canvas, (px_l, 440), (490, 570), (55,55,95), 1)
        txt(canvas, "Session stats:", (px_l + 8, 460), 0.60, CY)
        elapsed    = int(now - session_start)
        mins, secs = elapsed // 60, elapsed % 60
        txt(canvas, f"Time     : {mins:02d}:{secs:02d}", (px_l+12, 486), 0.56, W)
        txt(canvas, f"Words    : {total_words}",         (px_l+12, 512), 0.56, W)
        txt(canvas, f"Sentences: {total_sentences}",      (px_l+12, 538), 0.56, W)
        txt(canvas, f"Gestures : {total_gestures}",       (px_l+12, 564), 0.56, W)

        # ---- RIGHT panel: Instructions ----
        px_r = 510
        cv2.rectangle(canvas, (px_r, 248), (DISP_W - 10, 660), (14,14,32), -1)
        cv2.rectangle(canvas, (px_r, 248), (DISP_W - 10, 660), (55,55,95), 1)

        rows = [
            ("GESTURE",       "VOICE / ACTION",           CY),
            ("Thumbs Up",     "=> speaks 'Yes'",           W),
            ("Pinky Only",    "=> speaks 'No'",            W),
            ("Peace (V)",     "=> speaks 'Peace'",         W),
            ("All 5 Fingers", "=> speaks 'Stop'",          W),
            ("Index Only",    "=> speaks 'Point'",         W),
            ("Thumb+Index",   "=> UNDO last word",         PK),
            ("Closed Fist",   "=> clears sentence",        RD),
            ("4 Fingers Up",  "=> speaks full sentence",   LM),
        ]
        for i, (g, a, c) in enumerate(rows):
            y  = 272 + i * 36
            sc = 0.62 if i == 0 else 0.57
            th = 2    if i == 0 else 1
            txt(canvas, g, (px_r + 12,       y), sc, c, th)
            txt(canvas, a, (px_r + 200,  y), sc, c, th)

        cv2.line(canvas, (px_r, 608), (DISP_W-10, 608), (55,55,95), 1)
        txt(canvas,
            f"[V] Speed:{SPEED_LABELS[voice_speed_idx]}   [S] Save log   [F] Fullscreen",
            (px_r + 12, 626), 0.50, GR)
        txt(canvas, f"FPS:{fps:4.1f}   Ping:{latency_ms}ms",
            (px_r + 12, 648), 0.50, GR)

        # Bottom bar
        txt(canvas, f"FPS:{fps:.0f}  Gestures:{total_gestures}  Words:{total_words}  Speed:{SPEED_LABELS[voice_speed_idx]}",
            (30, DISP_H - 12), 0.48, GR)

        cv2.imshow("AI Gesture Assistant", canvas)

# ============================================================
#  CLEANUP
# ============================================================
log_event("Session ended")
_tts_q.put(None)
_tts_thread.join(timeout=3)
cap.release()
cv2.destroyAllWindows()
print("Closed.")