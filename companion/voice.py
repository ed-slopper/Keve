"""Talking to Keve out loud, and Keve talking back.

Two backends each way, picked by the GPU profile (profiles.json):

  Ears:  "windows"  Windows' built-in speech recognition (System.Speech). No download.
         "whisper"  faster-whisper on your mic (CPU or GPU). Much better; ~75-1500 MB model.
  Mouth: "windows"  Windows' built-in voices (Microsoft David / Zira). No download.
         "kokoro"   Kokoro-82M (kokoro-onnx), a natural voice on the CPU. ~115-330 MB.

Anything missing falls back to the Windows backend, so voice always works on Windows.
Keve doesn't listen to itself: what the mic hears while Keve is talking is thrown away.
"""
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

VOICE_DIR = Path(os.environ.get("KEVE_HOME") or Path(os.environ.get("LOCALAPPDATA", ".")) / "Keve") / "voice"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Ways speech-to-text tends to hear "Keve".
WAKE_WORDS = r"\b(keve|kev|keev|keeve|kiev|kevin|keves|keeva|key v|diva|deva|kiva|keva|keepa)\b"


def clean_heard(text):
    """Make a transcript look like typed chat: lower case, 'Kevin,' -> 'keve'."""
    t = text.strip().lower()
    t = re.sub(WAKE_WORDS, "keve", t)
    t = re.sub(r"[^\w\s']", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def speakable(text):
    """Chat text made for a voice: ALL-CAPS shouting reads as letters ("A. M."), so it goes
    to normal case; "..." becomes a pause; chat leftovers (*, _, coordinates' noise) go."""
    t = text.replace("...", ",").replace("…", ",")
    t = re.sub(r"[*_~`#]", "", t)
    t = re.sub(r"\b([A-Z]{2,})\b", lambda m: m.group(1).capitalize() if m.group(1) not in ("TNT", "XP")
               else m.group(1), t)
    t = re.sub(r"\bkeve\b", "Keve", t, flags=re.I)
    t = re.sub(r"\s*,\s*,+", ",", t)
    t = re.sub(r"\s+", " ", t).strip(" ,")
    return t


# --- mouths ------------------------------------------------------------------------------
class WindowsMouth:
    """System.Speech in one long-lived PowerShell: a line on stdin is spoken."""

    SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $s.SelectVoice('VOICE') } catch {}
$s.Rate = RATE
[Console]::Out.WriteLine('ready'); [Console]::Out.Flush()
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null) { break }
  if ($line.Length -gt 0) { $s.Speak($line) }
  [Console]::Out.WriteLine('done'); [Console]::Out.Flush()
}
$s.Dispose()
"""

    def __init__(self, voice="Microsoft David Desktop", rate=1, out_wav=None):
        script = self.SCRIPT.replace("VOICE", voice)
        if out_wav:  # tests: write to a file instead of the speakers
            script = script.replace("$s.Rate = RATE", f"$s.Rate = RATE; $s.SetOutputToWaveFile('{out_wav}')")
        script = script.replace("RATE", str(int(rate)))
        self.proc = subprocess.Popen(["powershell", "-NoProfile", "-Command", script],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                     creationflags=NO_WINDOW)
        self.proc.stdout.readline()  # ready

    def speak(self, text):
        self.proc.stdin.write(text.replace("\n", " ") + "\n")
        self.proc.stdin.flush()
        self.proc.stdout.readline()  # done: returns when the line has been said

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.terminate()


class KokoroMouth:
    """Kokoro-82M through kokoro-onnx, played with sounddevice."""

    def __init__(self, voice="am_adam", speed=1.1):
        from kokoro_onnx import Kokoro  # noqa: import only when chosen
        import sounddevice
        # The full or half-precision model sounds smoothest; the int8 one is smallest.
        model = next((p for p in (VOICE_DIR / "kokoro-v1.0.onnx", VOICE_DIR / "kokoro-v1.0.fp16.onnx",
                                  VOICE_DIR / "kokoro-v1.0.int8.onnx") if p.exists()), None)
        voices = VOICE_DIR / "voices-v1.0.bin"
        if model is None or not voices.exists():
            raise FileNotFoundError("Kokoro's model files aren't there (run Keve.bat --setup-voice)")
        self.k = Kokoro(str(model), str(voices))
        self.sd = sounddevice
        self.voice, self.speed = voice, speed

    def speak(self, text):
        samples, rate = self.k.create(text, voice=self.voice, speed=self.speed, lang="en-us")
        self.sd.play(samples, rate)
        self.sd.wait()

    def close(self):
        pass


# --- ears --------------------------------------------------------------------------------
NUMBERS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
           "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "twenty",
           "thirty", "thirty two", "forty", "fifty", "sixty four", "a few", "some", "a stack of"]
ITEMS = ["wood", "logs", "trees", "dirt", "sand", "gravel", "stone", "cobblestone", "sugar cane",
         "pumpkins", "clay", "diamonds", "iron", "coal", "gold", "redstone", "lapis", "copper",
         "emeralds", "torches"]
VERBS = ["get", "get me", "go get", "go get me", "grab", "grab me", "bring me", "collect", "mine",
         "mine me", "go mine", "chop", "fetch", "find", "make", "make me", "craft", "give me"]
ORDERS = ["follow me", "come here", "come over here", "stay", "stay here", "wait here", "stop",
          "jump", "look at me", "defend me", "protect me", "guard me", "help", "what can you do",
          "what you got", "what do you have", "status", "play with me", "be my buddy",
          "do your own thing", "go home", "this is home", "set home", "give me everything",
          "bring me the wood", "bring me the sand", "bring them to me", "mine for diamonds",
          "go mining", "make a stone pickaxe", "make an iron pickaxe", "make a wooden pickaxe",
          "make a stone sword", "make an iron sword", "make a crafting table", "make a furnace",
          "craft torches", "remember this as the mine", "go to the mine"]


def _ps_list(words):
    return "@(" + ",".join("'" + w.replace("'", "''") + "'" for w in words) + ")"


class WindowsEars:
    """System.Speech on the default microphone, in a PowerShell process. A grammar of
    Keve's orders does the heavy lifting (it hears "keve get me ten wood" reliably);
    free dictation, weighted lower, catches chat and anything else."""

    SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$e = New-Object System.Speech.Recognition.SpeechRecognitionEngine([System.Globalization.CultureInfo]'en-US')
$C = 'System.Speech.Recognition.Choices'; $B = 'System.Speech.Recognition.GrammarBuilder'
$wake = New-Object $C (,[string[]]@('keve','kev','kevin','hey keve'))
$num = New-Object $C (,[string[]]NUMBERS)
$item = New-Object $C (,[string[]]ITEMS)
$verb = New-Object $C (,[string[]]VERBS)
$tail = New-Object $C (,[string[]]@('and bring them to me','and bring it to me','for me','and give them to me'))
$tmpl = New-Object $B; $tmpl.Append($verb); $tmpl.Append($num, 0, 1); $tmpl.Append($item); $tmpl.Append($tail, 0, 1)
$any = New-Object $C (,[string[]]ORDERS)
$any.Add($tmpl)
$root = New-Object $B; $root.Append($wake, 0, 1); $root.Append($any)
$orders = New-Object System.Speech.Recognition.Grammar($root); $orders.Name = 'orders'; $orders.Weight = 1.0; $orders.Priority = 10
$e.LoadGrammar($orders)
$d = New-Object System.Speech.Recognition.DictationGrammar; $d.Name = 'dictation'; $d.Weight = 0.3
$e.LoadGrammar($d)
INPUT
$e.EndSilenceTimeout = [TimeSpan]::FromMilliseconds(600)
[Console]::Out.WriteLine('ready'); [Console]::Out.Flush()
while ($true) {
  try { $r = $e.Recognize([TimeSpan]::FromSeconds(30)) } catch { break }
  if ($r -ne $null -and $r.Text.Length -gt 0) {
    [Console]::Out.WriteLine(("heard`t{0:N2}`t{1}`t{2}" -f $r.Confidence, $r.Grammar.Name, $r.Text)); [Console]::Out.Flush()
  } elseif (WAVMODE) { break }
}
"""

    def __init__(self, on_heard, wav=None):
        inp = f"$e.SetInputToWaveFile('{wav}')" if wav else "$e.SetInputToDefaultAudioDevice()"
        script = (self.SCRIPT.replace("INPUT", inp).replace("WAVMODE", "$true" if wav else "$false")
                  .replace("NUMBERS", _ps_list(NUMBERS)).replace("ITEMS", _ps_list(ITEMS))
                  .replace("VERBS", _ps_list(VERBS)).replace("ORDERS", _ps_list(ORDERS)))
        self.proc = subprocess.Popen(["powershell", "-NoProfile", "-Command", script],
                                     stdout=subprocess.PIPE, text=True, creationflags=NO_WINDOW)
        self.on_heard = on_heard
        self.proc.stdout.readline()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 4 or parts[0] != "heard":
                continue
            try:
                conf = float(parts[1].replace(",", "."))
            except ValueError:
                conf = 0.0
            # An order the grammar matched is trusted from a lower score than free speech.
            if conf >= (0.35 if parts[2] == "orders" else 0.5):
                self.on_heard(parts[3])

    def close(self):
        try:
            self.proc.terminate()
        except OSError:
            pass


class WhisperEars:
    """faster-whisper on the mic, with a simple loudness detector to find when you speak."""

    RATE = 16000
    FRAME = 480  # 30 ms

    def __init__(self, on_heard, model="small.en", device="auto", gate=None):
        import numpy as np
        import sounddevice
        from faster_whisper import WhisperModel
        self.np, self.sd = np, sounddevice
        compute = "int8"
        if device in ("auto", "cuda"):
            try:
                self.model = WhisperModel(model, device="cuda", compute_type="float16",
                                          download_root=str(VOICE_DIR / "whisper"))
                compute = None
            except Exception:  # no CUDA libraries: the CPU is fine for short orders
                device = "cpu"
        if compute:
            self.model = WhisperModel(model, device="cpu", compute_type=compute,
                                      download_root=str(VOICE_DIR / "whisper"))
        self.on_heard = on_heard
        self.gate = gate or (lambda: True)
        self.q = queue.Queue()
        self.stream = sounddevice.InputStream(samplerate=self.RATE, channels=1, dtype="float32",
                                              blocksize=self.FRAME, callback=self._cb)
        self.stream.start()
        threading.Thread(target=self._loop, daemon=True).start()

    def _cb(self, data, frames, t, status):
        # Checked as the sound comes in, not later: while a clip is being transcribed,
        # frames wait in the queue, and by then Keve may have stopped talking.
        if not self.gate():
            return
        self.q.put(data[:, 0].copy())

    def _loop(self):
        np = self.np
        noise = []
        for _ in range(33):  # one second to learn the room's noise
            noise.append(float(np.sqrt(np.mean(self.q.get() ** 2))))
        floor = max(sorted(noise)[len(noise) // 2], 1e-4)
        talking, buf, quiet = False, [], 0
        while True:
            f = self.q.get()
            if not self.gate():  # Keve is speaking: don't listen to itself
                talking, buf, quiet = False, [], 0
                continue
            loud = float(np.sqrt(np.mean(f ** 2))) > floor * 3.5
            if loud:
                talking, quiet = True, 0
            if talking:
                buf.append(f)
                quiet = 0 if loud else quiet + 1
                if quiet > 23 or len(buf) > 400:  # ~0.7 s of quiet, or 12 s of talking
                    audio = np.concatenate(buf)
                    talking, buf, quiet = False, [], 0
                    if len(audio) > self.RATE * 0.35:
                        text = self.transcribe(audio)
                        if text:
                            self.on_heard(text)
            elif not loud:
                floor = floor * 0.995 + float(np.sqrt(np.mean(f ** 2))) * 0.005

    # Whisper "hears" these in fans, keyboards and breathing: they close most of the subtitled
    # videos it learned from. Alone in a clip, they're almost never what you said.
    PHANTOMS = {"thank you", "thank you very much", "thanks", "thanks for watching",
                "thank you for watching", "thanks for watching!", "bye", "bye bye", "goodbye",
                "you", "so", "okay", "oh", "uh", "um", "hmm", "please subscribe",
                "subscribe", "see you next time", "i'll see you next time", "the end", "music",
                "applause", "silence", "foreign", "."}

    # Teaches Whisper the name and the kind of thing you say (it otherwise hears "keep").
    PROMPT = "Keve, follow me. Keve, mine for diamonds. Keve, get me ten wood."

    def transcribe(self, audio):
        """Speech in a clip, or '' when it was only noise."""
        try:
            segs, _ = self.model.transcribe(
                audio, language="en", beam_size=1, condition_on_previous_text=False,
                initial_prompt=self.PROMPT, hotwords="Keve",
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 400},
                no_speech_threshold=0.5, log_prob_threshold=-0.9)
            segs = list(segs)
        except Exception:  # the VAD model missing: plain transcription, the other checks still run
            segs, _ = self.model.transcribe(audio, language="en", beam_size=1,
                                            condition_on_previous_text=False)
            segs = list(segs)
        kept = [s for s in segs if getattr(s, "no_speech_prob", 0) < 0.5
                and getattr(s, "avg_logprob", 0) > -1.0]
        text = " ".join(s.text for s in kept).strip()
        plain = re.sub(r"[^\w\s']", "", text.lower()).strip()
        if not plain or plain in self.PHANTOMS:
            return ""
        return text

    def close(self):
        try:
            self.stream.stop()
        except Exception:
            pass


# --- the whole voice ---------------------------------------------------------------------
class Voice:
    """Ears and a mouth with a queue, so speaking never blocks the game loop."""

    def __init__(self, ears="windows", mouth="windows", on_heard=None, whisper_model="small.en",
                 whisper_device="auto", kokoro_voice="am_adam", windows_voice="Microsoft David Desktop",
                 kokoro_speed=1.1, windows_rate=1):
        self.on_heard = on_heard or (lambda text: None)
        self.speaking_until = 0.0
        self.q = queue.Queue()
        self.mouth = None
        self.mouth_name = mouth
        if mouth == "kokoro":
            try:
                self.mouth = KokoroMouth(kokoro_voice, kokoro_speed)
            except Exception as e:
                print(f"[voice] Kokoro unavailable ({e}); using the Windows voice")
                self.mouth_name = "windows"
        if self.mouth is None and mouth != "off":
            self.mouth = WindowsMouth(windows_voice, windows_rate)
            self.mouth_name = "windows"
        if self.mouth:
            threading.Thread(target=self._speak_loop, daemon=True).start()
        self.ears = None
        self.ears_name = ears
        if ears == "whisper":
            try:
                self.ears = WhisperEars(self._heard, whisper_model, whisper_device, gate=self.listening)
            except Exception as e:
                print(f"[voice] faster-whisper unavailable ({e}); using Windows speech recognition")
                self.ears_name = "windows"
        if self.ears is None and ears != "off":
            try:
                self.ears = WindowsEars(self._heard)
                self.ears_name = "windows"
            except Exception as e:
                print(f"[voice] no speech recognition ({e})")
                self.ears_name = "off"

    def listening(self):
        return time.time() > self.speaking_until

    def _heard(self, text):
        if not self.listening():
            return  # its own voice coming back through the speakers
        # Its own line, caught by the mic anyway (speakers, a late clip): not you.
        import difflib
        plain = re.sub(r"[^\w\s]", "", text.lower()).strip()
        now = time.time()
        self.recent = [(t, s) for t, s in getattr(self, "recent", []) if now - t < 30]
        for _, said in self.recent:
            if plain and (plain in said or difflib.SequenceMatcher(None, plain, said).ratio() > 0.7):
                return
        self.on_heard(text)

    def say(self, text):
        if self.mouth:
            text = speakable(text)
            if text:
                self.q.put(text)

    def _speak_loop(self):
        while True:
            text = self.q.get()
            self.recent = getattr(self, "recent", []) + [
                (time.time(), re.sub(r"[^\w\s]", "", text.lower()).strip())]
            # Roughly how long the line takes, plus a tail: the mic ignores that window.
            self.speaking_until = time.time() + 0.6 + len(text) * 0.075
            try:
                self.mouth.speak(text)
            except Exception as e:
                print(f"[voice] couldn't speak ({e})", file=sys.stderr)
            self.speaking_until = time.time() + 0.5

    def close(self):
        for part in (self.ears, self.mouth):
            if part:
                part.close()
