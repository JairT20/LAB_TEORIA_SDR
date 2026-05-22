# =========================================================
# RTL-SDR FM DASHBOARD - MAIN EXECUTION SCRIPT
# =========================================================

import numpy as np
import matplotlib.pyplot as plt
from scipy import signal
import sounddevice as sd
import threading
import psutil
import backend
import frontend

# =========================================================
# AUDIO STREAM INITIATION
# =========================================================

audio_stream = sd.OutputStream(
    samplerate=backend.AUDIO_RATE,
    channels=1,
    dtype=np.float32,
    blocksize=int(backend.N_AUDIO / backend.DECIMATION_FACTOR),
    callback=backend.audio_callback
)
audio_stream.start()

# =========================================================
# SDR THREAD INITIATION
# =========================================================

sdr_thread = threading.Thread(
    target=backend.sdr.read_samples_async,
    args=(backend.sdr_callback, backend.N_AUDIO)
)
sdr_thread.daemon = True
sdr_thread.start()

# =========================================================
# LOOP PRINCIPAL DE RENDERIZADO Y MÉTRICAS
# =========================================================

gui_counter = 0

try:
    while plt.fignum_exists(frontend.fig.number):
        gui_counter += 1

        # FRECUENCIA MANUAL VIA TEXTBOX
        try:
            manual_freq = float(frontend.text_freq.text) * 1e6
            if manual_freq != backend.sdr.center_freq:
                backend.sdr.center_freq = manual_freq
        except:
            pass

        # GANANCIA VIA SLIDER
        backend.sdr.gain = frontend.slider_gain.val

        # UPDATE GUI
        if gui_counter >= backend.GUI_UPDATE_INTERVAL:
            with backend.lock:
                iq_copy = backend.iq_psd_buffer.copy()
                audio_copy = backend.latest_audio.copy()

            # FFT
            fft_db = backend.calc_fft(
                iq_copy[-backend.N_AUDIO:]
            )

            # PERIODOGRAMA
            _, per_db = backend.calc_periodogram(
                iq_copy[-backend.N_AUDIO:],
                backend.SAMPLE_RATE
            )

            # WELCH CRUDA
            _, welch_db = backend.calc_welch(
                iq_copy,
                backend.SAMPLE_RATE,
                backend.N_PER_SEG
            )

            # WELCH FILTRADA
            iq_filt = signal.lfilter(
                backend.b_filt,
                backend.a_filt,
                iq_copy
            )
            _, welch_filt_db = backend.calc_welch(
                iq_filt,
                backend.SAMPLE_RATE,
                backend.N_PER_SEG
            )

            # UPDATE DATA EN LAS LÍNEAS
            frontend.line_fft.set_ydata(fft_db)
            frontend.line_per.set_ydata(per_db)
            frontend.line_welch.set_ydata(welch_db)
            frontend.line_welch_filt.set_ydata(welch_filt_db)
            frontend.line_demod.set_ydata(
                audio_copy[:len(frontend.t_demod)]
            )

            # CALCULO DE MÉTRICAS COMPUTACIONALES Y DE SEÑAL
            cpu_process = psutil.Process().cpu_percent()
            cpu_total = psutil.cpu_percent()
            mem_mb = psutil.Process().memory_info().rss / (1024 * 1024)

            noise_floor = np.median(per_db)
            potencia = np.mean(np.abs(iq_copy) ** 2)
            potencia_dbfs = 10 * np.log10(potencia + 1e-12)

            idx_peak = np.argmax(welch_db)
            freq_peak = frontend.f_abs_w[idx_peak]

            clipping = ""
            if (
                np.max(np.abs(np.real(iq_copy))) > 0.99
                or
                np.max(np.abs(np.imag(iq_copy))) > 0.99
            ):
                clipping = "\n>>> CLIPPING DETECTADO <<<"

            info = (
                f"--- MÉTRICAS DE LA SEÑAL ---\n"
                f"Frec. Central: {freq_peak:.3f} MHz\n"
                f"Potencia (P): {potencia_dbfs:.1f} dBFS\n"
                f"Piso Ruido: {noise_floor:.1f} dB/Hz\n\n"
                f"--- COSTO COMPUTACIONAL ---\n"
                f"CPU Proceso: {cpu_process:.1f}%\n"
                f"CPU Total: {cpu_total:.1f}%\n"
                f"Memoria RAM: {mem_mb:.1f} MB"
            )

            if backend.show_clipping:
                info += clipping

            frontend.text_info.set_text(info)

            frontend.fig.canvas.draw_idle()
            frontend.fig.canvas.flush_events()
            plt.pause(0.001)

            gui_counter = 0

except KeyboardInterrupt:
    print("Finalizando...")

finally:
    # Cierre seguro de recursos hardware y streams de audio
    backend.sdr.cancel_read_async()
    backend.sdr.close()
    audio_stream.stop()
    audio_stream.close()
    plt.ioff()
    plt.show()