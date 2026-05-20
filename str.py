import numpy as np
import matplotlib.pyplot as plt
from scipy import signal
from rtlsdr import RtlSdr
import sounddevice as sd
import threading
import queue
import time
import psutil

# =========================================================
# CONFIGURACIÓN GENERAL
# =========================================================

SAMPLE_RATE = 2.048e6
CENTER_FREQ = 100.0e6
GAIN = 30

# -------- AUDIO --------
N_SAMPLES = 16384
DECIMATION_FACTOR = 42
AUDIO_RATE = int(SAMPLE_RATE / DECIMATION_FACTOR)

# -------- PSD --------
N_PSD = 65536
N_PERSEG = 1024

# -------- FM --------
FM_BANDWIDTH = 100e3

# -------- GUI --------
GUI_REFRESH = 0.2  # segundos

# =========================================================
# SDR
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
    FM_BANDWIDTH / (SAMPLE_RATE / 2),
    btype='low'
)

zi_filt = signal.lfilter_zi(b_filt, a_filt) * 0

# =========================================================
# ESTADOS GLOBALES
# =========================================================

last_iq = 0j

audio_queue = queue.Queue(maxsize=200)

iq_buffer = np.zeros(N_PSD, dtype=np.complex64)

latest_audio = np.zeros(int(N_SAMPLES / DECIMATION_FACTOR))

lock = threading.Lock()

running = True

# =========================================================
# FUNCIONES DSP
# =========================================================

def calculate_axes(n, sample_rate, center_freq):

    f_rel = np.fft.fftshift(
        np.fft.fftfreq(n, d=1/sample_rate)
    )

    f_abs = (center_freq + f_rel) / 1e6

    return f_abs

def calc_fft(x):

    w = np.hanning(len(x))

    X = np.fft.fftshift(
        np.fft.fft(x * w)
    )

    return 20 * np.log10(np.abs(X) + 1e-12)

def calc_periodogram(x):

    f, Pxx = signal.periodogram(
        x,
        fs=SAMPLE_RATE,
        window='hann',
        nfft=len(x),
        return_onesided=False,
        scaling='density'
    )

    return 10 * np.log10(
        np.fft.fftshift(Pxx) + 1e-12
    )

def calc_welch(x):

    f, Pxx = signal.welch(
        x,
        fs=SAMPLE_RATE,
        window='hann',
        nperseg=N_PERSEG,
        return_onesided=False,
        scaling='density'
    )

    return 10 * np.log10(
        np.fft.fftshift(Pxx) + 1e-12
    )

# =========================================================
# CALLBACK SDR ASÍNCRONO
# =========================================================

def sdr_callback(samples, context):

    global zi_filt
    global last_iq
    global iq_buffer
    global latest_audio

    # =====================================================
    # FILTRO FM
    # =====================================================

    iq_filtered, zi_filt = signal.lfilter(
        b_filt,
        a_filt,
        samples,
        zi=zi_filt
    )

    # =====================================================
    # DEMOD FM
    # =====================================================

    iq_demod_input = np.concatenate(
        ([last_iq], iq_filtered)
    )

    last_iq = iq_filtered[-1]

    demod = np.angle(
        iq_demod_input[1:]
        * np.conjugate(iq_demod_input[:-1])
    )

    # =====================================================
    # DECIMACIÓN
    # =====================================================

    audio_out = signal.decimate(
        demod,
        DECIMATION_FACTOR,
        ftype='fir',
        zero_phase=False
    )

    audio_out = np.float32(audio_out * 5.0)

    # =====================================================
    # AUDIO QUEUE
    # =====================================================

    try:
        audio_queue.put_nowait(audio_out)

    except queue.Full:
        pass

    # =====================================================
    # BUFFER PSD
    # =====================================================

    with lock:

        iq_buffer[:-len(samples)] = iq_buffer[len(samples):]
        iq_buffer[-len(samples):] = samples

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

    except queue.Empty:

        outdata.fill(0)

# =========================================================
# STREAM AUDIO
# =========================================================

audio_stream = sd.OutputStream(
    samplerate=AUDIO_RATE,
    channels=1,
    dtype=np.float32,
    blocksize=int(N_SAMPLES / DECIMATION_FACTOR),
    callback=audio_callback
)

audio_stream.start()

# =========================================================
# INICIAR SDR ASYNC
# =========================================================

sdr_thread = threading.Thread(
    target=sdr.read_samples_async,
    args=(sdr_callback, N_SAMPLES)
)

sdr_thread.daemon = True
sdr_thread.start()

# =========================================================
# INTERFAZ
# =========================================================

plt.ion()

fig, axs = plt.subplots(2, 2, figsize=(14, 8))

ax_fft = axs[0, 0]
ax_per = axs[0, 1]
ax_welch = axs[1, 0]
ax_audio = axs[1, 1]

# =========================================================
# EJES
# =========================================================

f_fft = calculate_axes(
    N_SAMPLES,
    SAMPLE_RATE,
    CENTER_FREQ
)

f_welch = calculate_axes(
    N_PERSEG,
    SAMPLE_RATE,
    CENTER_FREQ
)

# =========================================================
# LÍNEAS
# =========================================================

line_fft, = ax_fft.plot(
    f_fft,
    np.zeros(N_SAMPLES)
)

line_per, = ax_per.plot(
    f_fft,
    np.zeros(N_SAMPLES)
)

line_welch, = ax_welch.plot(
    f_welch,
    np.zeros(N_PERSEG)
)

t_audio = np.linspace(
    0,
    len(latest_audio) / AUDIO_RATE,
    len(latest_audio)
)

line_audio, = ax_audio.plot(
    t_audio,
    latest_audio
)

# =========================================================
# CONFIG PLOTS
# =========================================================

ax_fft.set_title("FFT Instantánea")
ax_per.set_title("Periodograma")
ax_welch.set_title("Welch")
ax_audio.set_title("Audio FM")

ax_fft.set_ylim(-50, 80)
ax_per.set_ylim(-150, -50)
ax_welch.set_ylim(-150, -50)
ax_audio.set_ylim(-1, 1)

for ax in axs.flatten():
    ax.grid(True)

# =========================================================
# LOOP GUI
# =========================================================

try:

    while plt.fignum_exists(fig.number):

        t0 = time.perf_counter()

        with lock:

            iq_copy = iq_buffer.copy()
            audio_copy = latest_audio.copy()

        # =================================================
        # FFT
        # =================================================

        fft_db = calc_fft(iq_copy[-N_SAMPLES:])

        # =================================================
        # PERIOD
        # =================================================

        per_db = calc_periodogram(
            iq_copy[-N_SAMPLES:]
        )

        # =================================================
        # WELCH
        # =================================================

        welch_db = calc_welch(iq_copy)

        # =================================================
        # UPDATE PLOTS
        # =================================================

        line_fft.set_ydata(fft_db)
        line_per.set_ydata(per_db)
        line_welch.set_ydata(welch_db)

        line_audio.set_ydata(
            audio_copy[:len(t_audio)]
        )

        # =================================================
        # INFO
        # =================================================

        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent

        noise_floor = np.median(per_db)

        fig.suptitle(
            f"CPU: {cpu:.1f}% | "
            f"RAM: {ram:.1f}% | "
            f"Piso ruido: {noise_floor:.1f} dB/Hz"
        )

        fig.canvas.draw_idle()
        fig.canvas.flush_events()

        plt.pause(GUI_REFRESH)

except KeyboardInterrupt:

    print("Deteniendo...")

finally:

    running = False

    sdr.cancel_read_async()

    sdr.close()

    audio_stream.stop()
    audio_stream.close()

    plt.ioff()

    plt.show()