#!/usr/bin/env python3
"""
Pygame Karaoke Recorder for Windows

Records two sources at the same time:
  1. Windows speaker/output audio via WASAPI loopback
  2. A microphone, with optional live monitoring

The final mixed recording is always saved as WAV. If FFmpeg is installed and
available on PATH, an MP3 copy is created automatically.

Install:
    py -m pip install pygame numpy PyAudioWPatch

Run:
    py pygame_karaoke_recorder.py

Optional MP3 support:
    Install FFmpeg and make sure ffmpeg.exe is on PATH.

Headphones are strongly recommended when MIC LISTEN is enabled, otherwise the
microphone can pick up its own monitored output and create feedback.
"""

from __future__ import annotations

import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import numpy as np
    import pygame
    import pyaudiowpatch as pyaudio
except ImportError as exc:
    print("Missing dependency:", exc)
    print("Install with: py -m pip install pygame numpy PyAudioWPatch")
    raise SystemExit(1)

# ------------------------------ Configuration ------------------------------

WIDTH, HEIGHT = 1000, 720
FPS = 60
TARGET_RATE = 48000
BLOCK = 1024
BG = (14, 18, 27)
PANEL = (25, 31, 44)
PANEL_2 = (33, 41, 57)
TEXT = (235, 240, 248)
MUTED = (151, 163, 181)
ACCENT = (64, 164, 255)
GREEN = (51, 209, 122)
YELLOW = (255, 196, 64)
RED = (244, 78, 91)
BORDER = (63, 74, 94)

RECORDINGS_DIR = Path.home() / "Music" / "Karaoke Recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class AudioDevice:
    index: int
    name: str
    rate: int
    channels: int
    host_api: int


@dataclass
class TimedChunk:
    started: float
    rate: int
    channels: int
    samples: np.ndarray


class AudioEngine:
    """Captures system-loopback and microphone audio in independent threads."""

    def __init__(self):
        self.pa = pyaudio.PyAudio()
        self.mics: list[AudioDevice] = []
        self.loopbacks: list[AudioDevice] = []
        self.outputs: list[AudioDevice] = []
        self.refresh_devices()

        self.recording = False
        self.stop_event = threading.Event()
        self.monitor_enabled = True
        self.monitor_gain = 0.55
        self.mic_gain = 0.80
        self.system_gain = 0.80
        self.mic_level = 0.0
        self.system_level = 0.0
        self.status = "Ready"
        self.started_at = 0.0
        self.mic_chunks: list[TimedChunk] = []
        self.system_chunks: list[TimedChunk] = []
        self.monitor_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=8)
        self.threads: list[threading.Thread] = []
        self.last_wav: Optional[Path] = None
        self.last_mp3: Optional[Path] = None
        self.error: Optional[str] = None

    def refresh_devices(self):
        self.mics.clear()
        self.loopbacks.clear()
        self.outputs.clear()
        for i in range(self.pa.get_device_count()):
            d = self.pa.get_device_info_by_index(i)
            name = str(d.get("name", f"Device {i}"))
            rate = int(float(d.get("defaultSampleRate", TARGET_RATE)))
            host = int(d.get("hostApi", -1))
            ins = int(d.get("maxInputChannels", 0))
            outs = int(d.get("maxOutputChannels", 0))
            if ins > 0:
                item = AudioDevice(i, name, rate, min(ins, 2), host)
                if d.get("isLoopbackDevice", False) or "loopback" in name.lower():
                    self.loopbacks.append(item)
                else:
                    self.mics.append(item)
            if outs > 0:
                self.outputs.append(AudioDevice(i, name, rate, min(outs, 2), host))

        # PyAudioWPatch can expose loopbacks through a generator even if the
        # regular device list did not label them clearly.
        if not self.loopbacks:
            try:
                for d in self.pa.get_loopback_device_info_generator():
                    self.loopbacks.append(AudioDevice(
                        int(d["index"]), str(d["name"]),
                        int(float(d["defaultSampleRate"])),
                        max(1, min(int(d["maxInputChannels"]), 2)),
                        int(d["hostApi"]),
                    ))
            except Exception:
                pass

    def default_indices(self):
        mic_i = 0
        loop_i = 0
        out_i = 0
        try:
            default_mic = int(self.pa.get_default_input_device_info()["index"])
            mic_i = next((i for i, d in enumerate(self.mics) if d.index == default_mic), 0)
        except Exception:
            pass
        try:
            default_out = int(self.pa.get_default_output_device_info()["index"])
            out_i = next((i for i, d in enumerate(self.outputs) if d.index == default_out), 0)
            # Match the default output name to its WASAPI loopback counterpart.
            out_name = self.outputs[out_i].name.lower() if self.outputs else ""
            stem = out_name.split("(")[0].strip()
            loop_i = next((i for i, d in enumerate(self.loopbacks)
                           if stem and stem in d.name.lower()), 0)
        except Exception:
            pass
        return mic_i, loop_i, out_i

    @staticmethod
    def _level(samples: np.ndarray) -> float:
        if samples.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
        # Useful display mapping rather than a raw linear RMS meter.
        db = 20.0 * math.log10(max(rms, 1e-7))
        return max(0.0, min(1.0, (db + 55.0) / 55.0))

    def start(self, mic: AudioDevice, loopback: AudioDevice,
              output: Optional[AudioDevice]):
        if self.recording:
            return
        self.error = None
        self.mic_chunks.clear()
        self.system_chunks.clear()
        while not self.monitor_queue.empty():
            try:
                self.monitor_queue.get_nowait()
            except queue.Empty:
                break
        self.stop_event.clear()
        self.started_at = time.perf_counter()
        self.recording = True
        self.status = "Recording"

        self.threads = [
            threading.Thread(target=self._capture, args=(mic, False), daemon=True),
            threading.Thread(target=self._capture, args=(loopback, True), daemon=True),
        ]
        if output is not None:
            self.threads.append(threading.Thread(
                target=self._monitor, args=(output, mic.rate), daemon=True))
        for thread in self.threads:
            thread.start()

    def _capture(self, device: AudioDevice, system: bool):
        stream = None
        try:
            stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=device.channels,
                rate=device.rate,
                input=True,
                input_device_index=device.index,
                frames_per_buffer=BLOCK,
            )
            while not self.stop_event.is_set():
                timestamp = time.perf_counter()
                raw = stream.read(BLOCK, exception_on_overflow=False)
                data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                data = data.reshape(-1, device.channels)
                chunk = TimedChunk(timestamp, device.rate, device.channels, data.copy())
                if system:
                    self.system_chunks.append(chunk)
                    self.system_level = self._level(data)
                else:
                    self.mic_chunks.append(chunk)
                    self.mic_level = self._level(data)
                    if self.monitor_enabled:
                        try:
                            self.monitor_queue.put_nowait(data.copy())
                        except queue.Full:
                            try:
                                self.monitor_queue.get_nowait()
                                self.monitor_queue.put_nowait(data.copy())
                            except queue.Empty:
                                pass
        except Exception as exc:
            self.error = f"{'System' if system else 'Mic'} capture: {exc}"
            self.status = "Audio device error"
            self.stop_event.set()
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass

    @staticmethod
    def _resample(data: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
        if src_rate == dst_rate or len(data) < 2:
            return data.astype(np.float32, copy=False)
        new_count = max(1, int(round(len(data) * dst_rate / src_rate)))
        old_x = np.arange(len(data), dtype=np.float64)
        new_x = np.linspace(0, len(data) - 1, new_count, dtype=np.float64)
        channels = [np.interp(new_x, old_x, data[:, c]) for c in range(data.shape[1])]
        return np.stack(channels, axis=1).astype(np.float32)

    @staticmethod
    def _stereo(data: np.ndarray) -> np.ndarray:
        if data.shape[1] == 1:
            return np.repeat(data, 2, axis=1)
        return data[:, :2]

    def _monitor(self, output: AudioDevice, mic_rate: int):
        stream = None
        try:
            # Use the output's native rate and stereo where possible.
            channels = max(1, min(output.channels, 2))
            stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=output.rate,
                output=True,
                output_device_index=output.index,
                frames_per_buffer=BLOCK,
            )
            while not self.stop_event.is_set() or not self.monitor_queue.empty():
                try:
                    data = self.monitor_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if not self.monitor_enabled:
                    continue
                data = self._resample(data, mic_rate, output.rate)
                if channels == 2:
                    data = self._stereo(data)
                else:
                    data = np.mean(data, axis=1, keepdims=True)
                data = np.clip(data * self.monitor_gain, -1.0, 1.0)
                stream.write((data * 32767.0).astype(np.int16).tobytes())
        except Exception as exc:
            # Monitoring failure should not destroy an otherwise good recording.
            if self.error is None:
                self.error = f"Mic monitoring: {exc}"
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass

    def stop_and_save_async(self):
        if not self.recording:
            return
        self.recording = False
        self.status = "Finishing recording..."
        self.stop_event.set()
        threading.Thread(target=self._finish, daemon=True).start()

    def _finish(self):
        for thread in self.threads:
            if thread is not threading.current_thread():
                thread.join(timeout=3.0)
        self.mic_level = 0.0
        self.system_level = 0.0
        try:
            self.last_wav, self.last_mp3 = self._mix_and_save()
            if self.last_mp3:
                self.status = f"Saved MP3: {self.last_mp3.name}"
            else:
                self.status = f"Saved WAV: {self.last_wav.name} (FFmpeg not found)"
        except Exception as exc:
            self.error = f"Saving: {exc}"
            self.status = "Could not save recording"

    def _chunks_to_track(self, chunks: list[TimedChunk]) -> tuple[np.ndarray, int]:
        if not chunks:
            return np.zeros((0, 2), np.float32), 0
        src_rate = chunks[0].rate
        data = np.concatenate([c.samples for c in chunks], axis=0)
        data = self._stereo(data)
        data = self._resample(data, src_rate, TARGET_RATE)
        offset = max(0, int(round((chunks[0].started - self.started_at) * TARGET_RATE)))
        return data, offset

    def _mix_and_save(self) -> tuple[Path, Optional[Path]]:
        mic, mic_offset = self._chunks_to_track(self.mic_chunks)
        system, sys_offset = self._chunks_to_track(self.system_chunks)
        if len(mic) == 0 and len(system) == 0:
            raise RuntimeError("No audio was captured")
        total = max(mic_offset + len(mic), sys_offset + len(system))
        mix = np.zeros((total, 2), dtype=np.float32)
        if len(system):
            mix[sys_offset:sys_offset + len(system)] += system * self.system_gain
        if len(mic):
            mix[mic_offset:mic_offset + len(mic)] += mic * self.mic_gain

        # Soft limiting avoids harsh clipping when both tracks peak together.
        peak = float(np.max(np.abs(mix))) if mix.size else 0.0
        if peak > 0.98:
            mix *= 0.98 / peak
        pcm = (np.clip(mix, -1.0, 1.0) * 32767.0).astype(np.int16)

        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        wav_path = RECORDINGS_DIR / f"Karaoke_{stamp}.wav"
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(TARGET_RATE)
            wf.writeframes(pcm.tobytes())

        mp3_path = None
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            mp3_path = wav_path.with_suffix(".mp3")
            result = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-i", str(wav_path), "-codec:a", "libmp3lame", "-b:a", "192k",
                 str(mp3_path)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                mp3_path = None
                self.error = "FFmpeg MP3 conversion failed; WAV was saved"
        return wav_path, mp3_path

    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at if self.recording else 0.0

    def close(self):
        if self.recording:
            self.stop_event.set()
            self.recording = False
        try:
            self.pa.terminate()
        except Exception:
            pass


# ---------------------------------- UI --------------------------------------

class Button:
    def __init__(self, rect, text, color=ACCENT):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.color = color

    def draw(self, screen, font, enabled=True, active=False):
        mouse = pygame.mouse.get_pos()
        hover = enabled and self.rect.collidepoint(mouse)
        color = self.color
        if active:
            color = GREEN
        if hover:
            color = tuple(min(255, c + 22) for c in color)
        if not enabled:
            color = (62, 68, 79)
        pygame.draw.rect(screen, color, self.rect, border_radius=10)
        label = font.render(self.text, True, (255, 255, 255) if enabled else MUTED)
        screen.blit(label, label.get_rect(center=self.rect.center))

    def hit(self, pos):
        return self.rect.collidepoint(pos)


class Slider:
    def __init__(self, x, y, w, value):
        self.rect = pygame.Rect(x, y, w, 26)
        self.value = value
        self.dragging = False

    def set_from_x(self, x):
        self.value = max(0.0, min(1.5, (x - self.rect.x) / self.rect.w * 1.5))

    def event(self, event, enabled=True):
        if not enabled:
            self.dragging = False
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.inflate(0, 14).collidepoint(event.pos):
            self.dragging = True
            self.set_from_x(event.pos[0])
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging = False
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            self.set_from_x(event.pos[0])

    def draw(self, screen):
        pygame.draw.rect(screen, BORDER, (self.rect.x, self.rect.centery - 4, self.rect.w, 8), border_radius=4)
        px = self.rect.x + int(self.rect.w * self.value / 1.5)
        pygame.draw.rect(screen, ACCENT, (self.rect.x, self.rect.centery - 4, px - self.rect.x, 8), border_radius=4)
        pygame.draw.circle(screen, TEXT, (px, self.rect.centery), 10)


def clipped(text: str, font, width: int) -> str:
    if font.size(text)[0] <= width:
        return text
    while text and font.size(text + "...")[0] > width:
        text = text[:-1]
    return text + "..."


def selector(screen, font, small, y, label, devices, index, enabled=True):
    font_label = small.render(label, True, MUTED)
    screen.blit(font_label, (50, y))
    box = pygame.Rect(50, y + 25, 900, 50)
    pygame.draw.rect(screen, PANEL_2 if enabled else PANEL, box, border_radius=10)
    pygame.draw.rect(screen, BORDER, box, 1, border_radius=10)
    value = devices[index].name if devices else "No compatible device found"
    txt = font.render(clipped(value, font, 745), True, TEXT if enabled else MUTED)
    screen.blit(txt, (105, y + 39))
    left = pygame.Rect(60, y + 34, 34, 32)
    right = pygame.Rect(906, y + 34, 34, 32)
    for rect, symbol in ((left, "<"), (right, ">")):
        pygame.draw.rect(screen, ACCENT if enabled else BORDER, rect, border_radius=7)
        s = font.render(symbol, True, TEXT)
        screen.blit(s, s.get_rect(center=rect.center))
    return left, right


def meter(screen, x, y, w, value, label, font):
    screen.blit(font.render(label, True, TEXT), (x, y - 26))
    pygame.draw.rect(screen, (10, 13, 20), (x, y, w, 21), border_radius=5)
    fill = int(w * max(0.0, min(1.0, value)))
    color = GREEN if value < 0.75 else YELLOW if value < 0.92 else RED
    if fill:
        pygame.draw.rect(screen, color, (x, y, fill, 21), border_radius=5)
    pygame.draw.rect(screen, BORDER, (x, y, w, 21), 1, border_radius=5)


def main():
    if sys.platform != "win32":
        print("This application requires Windows WASAPI and PyAudioWPatch.")
        return 1

    pygame.init()
    try:
        pygame.mixer.init(frequency=48000, size=-16, channels=2, buffer=1024)
    except pygame.error:
        pass
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Pygame Karaoke MP3 Recorder")
    clock = pygame.time.Clock()
    title_font = pygame.font.SysFont("segoeui", 31, bold=True)
    font = pygame.font.SysFont("segoeui", 20)
    small = pygame.font.SysFont("segoeui", 16)
    tiny = pygame.font.SysFont("consolas", 14)

    engine = AudioEngine()
    mic_i, loop_i, out_i = engine.default_indices()

    record_btn = Button((50, 610, 210, 60), "RECORD", RED)
    stop_btn = Button((275, 610, 150, 60), "STOP", (85, 95, 112))
    play_btn = Button((440, 610, 175, 60), "PLAY LAST", ACCENT)
    folder_btn = Button((630, 610, 160, 60), "OPEN FOLDER", (92, 105, 130))
    listen_btn = Button((805, 610, 145, 60), "MIC LISTEN", GREEN)

    sys_slider = Slider(555, 394, 360, engine.system_gain)
    mic_slider = Slider(555, 448, 360, engine.mic_gain)
    mon_slider = Slider(555, 502, 360, engine.monitor_gain)

    smooth_mic = smooth_sys = 0.0
    running = True
    while running:
        selectable = not engine.recording and not engine.status.startswith("Finishing")
        mic_lr = loop_lr = out_lr = (pygame.Rect(0, 0, 0, 0), pygame.Rect(0, 0, 0, 0))

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    if engine.recording:
                        engine.stop_and_save_async()
                    elif selectable and engine.mics and engine.loopbacks:
                        out = engine.outputs[out_i] if engine.outputs else None
                        engine.start(engine.mics[mic_i], engine.loopbacks[loop_i], out)
            sys_slider.event(event)
            mic_slider.event(event)
            mon_slider.event(event)

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pos = event.pos
                if selectable:
                    if mic_lr[0].collidepoint(pos) and engine.mics:
                        mic_i = (mic_i - 1) % len(engine.mics)
                    elif mic_lr[1].collidepoint(pos) and engine.mics:
                        mic_i = (mic_i + 1) % len(engine.mics)
                    elif loop_lr[0].collidepoint(pos) and engine.loopbacks:
                        loop_i = (loop_i - 1) % len(engine.loopbacks)
                    elif loop_lr[1].collidepoint(pos) and engine.loopbacks:
                        loop_i = (loop_i + 1) % len(engine.loopbacks)
                    elif out_lr[0].collidepoint(pos) and engine.outputs:
                        out_i = (out_i - 1) % len(engine.outputs)
                    elif out_lr[1].collidepoint(pos) and engine.outputs:
                        out_i = (out_i + 1) % len(engine.outputs)
                    elif record_btn.hit(pos) and engine.mics and engine.loopbacks:
                        out = engine.outputs[out_i] if engine.outputs else None
                        engine.start(engine.mics[mic_i], engine.loopbacks[loop_i], out)
                if stop_btn.hit(pos) and engine.recording:
                    engine.stop_and_save_async()
                elif play_btn.hit(pos) and engine.last_wav and not engine.recording:
                    try:
                        target = engine.last_mp3 or engine.last_wav
                        pygame.mixer.music.load(str(target))
                        pygame.mixer.music.play()
                        engine.status = f"Playing: {target.name}"
                    except Exception as exc:
                        engine.error = f"Playback: {exc}"
                elif folder_btn.hit(pos):
                    os.startfile(RECORDINGS_DIR)
                elif listen_btn.hit(pos):
                    engine.monitor_enabled = not engine.monitor_enabled

        engine.system_gain = sys_slider.value
        engine.mic_gain = mic_slider.value
        engine.monitor_gain = mon_slider.value
        smooth_mic += (engine.mic_level - smooth_mic) * 0.25
        smooth_sys += (engine.system_level - smooth_sys) * 0.25

        screen.fill(BG)
        pygame.draw.rect(screen, PANEL, (25, 20, 950, 680), border_radius=18)
        screen.blit(title_font.render("Karaoke Recorder", True, TEXT), (50, 37))
        subtitle = small.render("System audio + microphone + live mic monitoring", True, MUTED)
        screen.blit(subtitle, (50, 78))

        mic_lr = selector(screen, font, small, 110, "MICROPHONE", engine.mics, mic_i, selectable)
        loop_lr = selector(screen, font, small, 205, "SYSTEM AUDIO (WASAPI LOOPBACK)", engine.loopbacks, loop_i, selectable)
        out_lr = selector(screen, font, small, 300, "MIC LISTEN OUTPUT", engine.outputs, out_i, selectable)

        meter(screen, 55, 420, 410, smooth_sys, "SYSTEM LEVEL", small)
        meter(screen, 55, 475, 410, smooth_mic, "MIC LEVEL", small)

        for y, label, slider in ((394, "System recording volume", sys_slider),
                                 (448, "Mic recording volume", mic_slider),
                                 (502, "Mic listen volume", mon_slider)):
            screen.blit(small.render(label, True, TEXT), (555, y - 21))
            slider.draw(screen)
            pct = int(slider.value * 100)
            screen.blit(tiny.render(f"{pct:3d}%", True, MUTED), (920, y + 5))

        elapsed = int(engine.elapsed())
        timer = f"{elapsed // 3600:02d}:{(elapsed // 60) % 60:02d}:{elapsed % 60:02d}"
        timer_surface = title_font.render(timer, True, RED if engine.recording else TEXT)
        screen.blit(timer_surface, timer_surface.get_rect(center=(255, 560)))
        status_color = RED if engine.error else GREEN if engine.recording else MUTED
        status = engine.error or engine.status
        screen.blit(small.render(clipped(status, small, 535), True, status_color), (440, 551))

        record_btn.draw(screen, font, selectable and bool(engine.mics and engine.loopbacks), engine.recording)
        stop_btn.draw(screen, font, engine.recording)
        play_btn.draw(screen, font, bool(engine.last_wav) and not engine.recording)
        folder_btn.draw(screen, small, True)
        listen_btn.draw(screen, small, True, engine.monitor_enabled)

        hint = "SPACE: record/stop   ESC: quit   Use headphones when MIC LISTEN is on"
        screen.blit(tiny.render(hint, True, MUTED), (50, 681))
        pygame.display.flip()
        clock.tick(FPS)

    engine.close()
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
