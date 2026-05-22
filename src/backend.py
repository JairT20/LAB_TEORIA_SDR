# =========================================================
# RTL-SDR FM DASHBOARD - BACKEND (Ring Buffer y DSP)
# =========================================================

import numpy as np
from scipy import signal
from queue import Queue, Empty
import threading
import time
import os

# =========================================================
# CONFIGURACIÓN INICIAL
# =========================================================

SAMPLE_RATE = 2.048e6
CENTER_FREQ = 100.0e6
GAIN = 30
DIGITAL_VGA = 1.0  # Ganancia por software

N_AUDIO = 8192
DECIMATION_FACTOR = 42
AUDIO_RATE = int(SAMPLE_RATE / DECIMATION_FACTOR)
AUDIO_CUTOFF = 15000

N_PSD = 65536
N_PER_SEG = 1024
FM_BW = 75e3

# =========================================================
# CLASE RING BUFFER (Sin bloqueos de copia de memoria)
# =========================================================

class RingBuffer:
    def __init__(self, size):
        self.size = size
        self.buffer = np.zeros(size, dtype=np.complex64)
        self.index = 0

    def extend(self, data):
        data_len = len(data)
        end_idx = self.index + data_len
        
        if end_idx < self.size:
            self.buffer[self.index:end_idx] = data
        else:
            overflow = end_idx - self.size
            self.buffer[self.index:self.size] = data[:data_len - overflow]
            self.buffer[0:overflow] = data[data_len - overflow:]
            
        self.index = end_idx % self.size

    def get_latest(self, n):
        if self.index >= n:
            return self.buffer[self.index - n : self.index]
        else:
            return np.concatenate((
                self.buffer[-(n - self.index):], 
                self.buffer[:self.index]
            ))

# =========================================================
# INICIALIZACIÓN SDR Y VARIABLES GLOBALES
# =========================================================

OFFLINE_MODE = False
try:
    from rtlsdr import RtlSdr
    sdr = RtlSdr()
    sdr.sample_rate = SAMPLE_RATE
    sdr.center_freq = CENTER_FREQ
    sdr.set_manual_gain_enabled(True)
    sdr.gain = GAIN
except Exception as e:
    print(f"\n[ADVERTENCIA] Falló la conexión con RTL-SDR.")
    print(f"Motivo reportado por el sistema: {e}")
    print(f"Iniciando en MODO OFFLINE...\n")
    sdr = None
    OFFLINE_MODE = True

b_filt, a_filt = None, None
zi_filt = None
b_audio, a_audio = None, None
zi_audio = None

last_iq = 0j
iq_ring_buffer = RingBuffer(N_PSD)
audio_queue = Queue(maxsize=100)
latest_audio = np.zeros(int(N_AUDIO / DECIMATION_FACTOR))
lock = threading.Lock()

# Variables para grabar y métricas
is_recording = False
offline_filename = ""
recording_buffer = []
dsp_time = 0.0  # Mide el costo computacional del DSP

# =========================================================
# FUNCIONES DSP
# =========================================================

def update_filters():
    global b_filt, a_filt, zi_filt, b_audio, a_audio, zi_audio, AUDIO_RATE
    AUDIO_RATE = int(SAMPLE_RATE / DECIMATION_FACTOR)
    
    b_filt, a_filt = signal.butter(4, FM_BW / (SAMPLE_RATE / 2), btype='low')
    zi_filt = signal.lfilter_zi(b_filt, a_filt) * 0
    
    b_audio, a_audio = signal.butter(4, AUDIO_CUTOFF / (SAMPLE_RATE / 2), btype='low')
    zi_audio = signal.lfilter_zi(b_audio, a_audio) * 0

update_filters()

def calculate_axes(n, fs, fc):
    f_rel = np.fft.fftshift(np.fft.fftfreq(n, d=1/fs))
    f_abs = (fc + f_rel) / 1e6
    return f_rel, f_abs

def calc_welch(x, fs, nperseg):
    f, Pxx = signal.welch(
        x, fs=fs, window='hann', nperseg=nperseg, 
        return_onesided=False, scaling='density'
    )
    return np.fft.fftshift(f), 10 * np.log10(np.fft.fftshift(Pxx) + 1e-12)

# =========================================================
# CALLBACKS (Hilos de Hardware)
# =========================================================

def sdr_callback(samples, context):
    global zi_filt, zi_audio, last_iq, latest_audio, is_recording, recording_buffer, dsp_time

    # Medición de Costo Computacional Inicial
    t_start = time.perf_counter()

    if is_recording:
        recording_buffer.extend(samples)

    # Filtro pasabajos FM
    iq_filtered, zi_filt = signal.lfilter(b_filt, a_filt, samples, zi=zi_filt)

    # Demodulación FM en cuadratura
    iq_demod_input = np.concatenate(([last_iq], iq_filtered))
    last_iq = iq_filtered[-1]
    demod = np.angle(iq_demod_input[1:] * np.conjugate(iq_demod_input[:-1]))

    # Filtro de Audio y Decimación
    audio_filtered, zi_audio = signal.lfilter(b_audio, a_audio, demod, zi=zi_audio)
    audio_out = audio_filtered[::DECIMATION_FACTOR]

    # Ganancia Digital VGA y Normalización
    audio_out = audio_out / (np.max(np.abs(audio_out)) + 1e-12)
    audio_out = np.float32(audio_out * DIGITAL_VGA)

    # Fin de medición DSP
    t_end = time.perf_counter()
    dsp_time = (t_end - t_start) * 1000.0  # Guardar en milisegundos

    try:
        audio_queue.put_nowait(audio_out)
    except:
        pass

    with lock:
        iq_ring_buffer.extend(samples)
        latest_audio = audio_out.copy()

def audio_callback(outdata, frames, time_info, status):
    try:
        data = audio_queue.get_nowait()
        if len(data) >= frames:
            outdata[:, 0] = data[:frames]
        else:
            outdata.fill(0)
            outdata[:len(data), 0] = data
    except Empty:
        outdata.fill(0)

# Trabajador para reproducir archivo guardado dinámicamente
def mock_sdr_worker(callback, chunk_size):
    global offline_filename
    
    while True:
        if not offline_filename or not os.path.exists(offline_filename):
            time.sleep(0.5)
            continue
            
        print(f"[SISTEMA] Cargando pista: {offline_filename}")
        try:
            data = np.load(offline_filename)
        except Exception as e:
            print(f"[ERROR] Archivo corrupto o ilegible: {e}")
            time.sleep(1)
            continue
            
        idx = 0
        archivo_en_reproduccion = offline_filename
        
        while archivo_en_reproduccion == offline_filename:
            while audio_queue.qsize() > 50:
                time.sleep(0.01)
                if archivo_en_reproduccion != offline_filename:
                    break 
                    
            if archivo_en_reproduccion != offline_filename:
                break
                
            end_idx = idx + chunk_size
            
            if end_idx > len(data):
                chunk = np.concatenate((data[idx:], data[:end_idx - len(data)]))
                idx = end_idx % len(data)
            else:
                chunk = data[idx:end_idx]
                idx = end_idx

            callback(chunk, None)