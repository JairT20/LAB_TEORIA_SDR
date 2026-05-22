# =========================================================
# RTL-SDR FM DASHBOARD - BACKEND
# =========================================================

import numpy as np
from scipy import signal
from rtlsdr import RtlSdr
import sounddevice as sd
from queue import Queue, Empty
import threading

# =========================================================
# CONFIGURACIÓN
# =========================================================

SAMPLE_RATE = 2.048e6
CENTER_FREQ = 100e6
GAIN = 30

# =========================================================
# AUDIO
# =========================================================

N_AUDIO = 8192
DECIMATION_FACTOR = 42
AUDIO_RATE = int(SAMPLE_RATE / DECIMATION_FACTOR)
AUDIO_CUTOFF = 15000

# =========================================================
# PSD
# =========================================================

N_PSD = 65536
N_PER_SEG = 1024

# =========================================================
# FM
# =========================================================

FM_BW = 75e3

# =========================================================
# GUI CONFIG (Compartida)
# =========================================================

GUI_UPDATE_INTERVAL = 20

# =========================================================
# SDR INITIALIZATION
# =========================================================

sdr = RtlSdr()
sdr.sample_rate = SAMPLE_RATE
sdr.center_freq = CENTER_FREQ
sdr.gain = GAIN

# =========================================================
# FILTRO FM
# =========================================================

b_filt, a_filt = signal.butter(
    4,
    FM_BW / (SAMPLE_RATE / 2),
    btype='low'
)

zi_filt = signal.lfilter_zi(
    b_filt,
    a_filt
) * 0

# =========================================================
# FILTRO AUDIO
# =========================================================

b_audio, a_audio = signal.butter(
    4,
    AUDIO_CUTOFF / (SAMPLE_RATE / 2),
    btype='low'
)

zi_audio = signal.lfilter_zi(
    b_audio,
    a_audio
) * 0

# =========================================================
# VARIABLES GLOBALES DE ESTADO
# =========================================================

last_iq = 0j

iq_psd_buffer = np.zeros(
    N_PSD,
    dtype=np.complex64
)

audio_queue = Queue(maxsize=100)

latest_audio = np.zeros(
    int(N_AUDIO / DECIMATION_FACTOR)
)

lock = threading.Lock()

show_clipping = False

freq_buttons = []
freq_axes = []
saved_freqs = []

# =========================================================
# FUNCIONES DSP
# =========================================================

def calculate_axes(n, sample_rate, center_freq):
    f_rel = np.fft.fftshift(
        np.fft.fftfreq(n, d=1/sample_rate)
    )
    f_abs = (center_freq + f_rel) / 1e6
    return f_rel, f_abs

def calc_fft(x):
    w = np.hanning(len(x))
    X = np.fft.fftshift(
        np.fft.fft(x * w)
    )
    return 20 * np.log10(
        np.abs(X) + 1e-12
    )

def calc_periodogram(x, fs):
    f, Pxx = signal.periodogram(
        x,
        fs=fs,
        window='hann',
        nfft=len(x),
        return_onesided=False,
        scaling='density'
    )
    return (
        np.fft.fftshift(f),
        10 * np.log10(
            np.fft.fftshift(Pxx) + 1e-12
        )
    )

def calc_welch(x, fs, nperseg):
    f, Pxx = signal.welch(
        x,
        fs=fs,
        window='hann',
        nperseg=nperseg,
        return_onesided=False,
        scaling='density'
    )
    return (
        np.fft.fftshift(f),
        10 * np.log10(
            np.fft.fftshift(Pxx) + 1e-12
        )
    )

# =========================================================
# CALLBACK SDR
# =========================================================

def sdr_callback(samples, context):
    global zi_filt
    global zi_audio
    global last_iq
    global latest_audio

    # FILTRO FM
    iq_filtered, zi_filt = signal.lfilter(
        b_filt,
        a_filt,
        samples,
        zi=zi_filt
    )

    # DEMODULACIÓN FM
    iq_demod_input = np.concatenate(
        ([last_iq], iq_filtered)
    )
    last_iq = iq_filtered[-1]

    demod = np.angle(
        iq_demod_input[1:]
        * np.conjugate(iq_demod_input[:-1])
    )

    # FILTRO AUDIO
    audio_filtered, zi_audio = signal.lfilter(
        b_audio,
        a_audio,
        demod,
        zi=zi_audio
    )

    # DECIMACIÓN SIMPLE
    audio_out = audio_filtered[
        ::DECIMATION_FACTOR
    ]

    # NORMALIZACIÓN
    audio_out = audio_out / (
        np.max(np.abs(audio_out)) + 1e-12
    )
    audio_out = np.float32(
        audio_out * 0.8
    )

    # AUDIO QUEUE
    try:
        audio_queue.put_nowait(audio_out)
    except:
        pass

    # BUFFER PSD
    with lock:
        iq_psd_buffer[:-len(samples)] = (
            iq_psd_buffer[len(samples):]
        )
        iq_psd_buffer[-len(samples):] = samples
        latest_audio = audio_out.copy()

# =========================================================
# CALLBACK AUDIO
# =========================================================

def audio_callback(outdata, frames, time_info, status):
    if status:
        print(status)
    try:
        data = audio_queue.get_nowait()
        if len(data) >= frames:
            outdata[:, 0] = data[:frames]
        else:
            outdata.fill(0)
            outdata[:len(data), 0] = data
    except Empty:
        outdata.fill(0)