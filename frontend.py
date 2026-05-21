# =========================================================
# RTL-SDR FM DASHBOARD - FRONTEND
# =========================================================

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, TextBox, Button
import backend

# =========================================================
# INTERFAZ
# =========================================================

plt.ion()

fig = plt.figure(figsize=(14, 8))

gs = fig.add_gridspec(
    2,
    3,
    hspace=0.35,
    wspace=0.25,
    bottom=0.2
)

ax_fft = fig.add_subplot(gs[0, 0])
ax_per = fig.add_subplot(gs[0, 1])
ax_welch = fig.add_subplot(gs[0, 2])
ax_demod = fig.add_subplot(gs[1, 0:2])
ax_info = fig.add_subplot(gs[1, 2])
ax_info.axis('off')

# =========================================================
# CONTROLES
# =========================================================

ax_freq = fig.add_axes([0.10, 0.05, 0.20, 0.05])
ax_addfreq = fig.add_axes([0.32, 0.05, 0.05, 0.05])
ax_gain = fig.add_axes([0.40, 0.05, 0.20, 0.05])
ax_clip = fig.add_axes([0.70, 0.05, 0.20, 0.05])

# =========================================================
# WIDGETS
# =========================================================

text_freq = TextBox(
    ax_freq,
    'Frec (MHz):',
    initial='100.0'
)

btn_addfreq = Button(
    ax_addfreq,
    '+'
)

slider_gain = Slider(
    ax_gain,
    'Ganancia:',
    0,
    50,
    valinit=backend.GAIN
)

btn_clip = Button(
    ax_clip,
    'Mostrar Clipping'
)

# =========================================================
# CLIPPING CALLBACK
# =========================================================

def toggle_clipping(event):
    backend.show_clipping = not backend.show_clipping

btn_clip.on_clicked(toggle_clipping)

# =========================================================
# CAMBIO FRECUENCIA CALLBACK
# =========================================================

def set_frequency(freq_mhz):
    freq_hz = freq_mhz * 1e6
    backend.CENTER_FREQ = freq_hz
    backend.sdr.center_freq = freq_hz

    text_freq.set_val(
        str(freq_mhz)
    )

    _, f_abs_new = backend.calculate_axes(
        backend.N_AUDIO,
        backend.SAMPLE_RATE,
        freq_hz
    )

    _, f_abs_w_new = backend.calculate_axes(
        backend.N_PER_SEG,
        backend.SAMPLE_RATE,
        freq_hz
    )

    line_fft.set_xdata(
        f_abs_new
    )

    line_per.set_xdata(
        f_abs_new
    )

    line_welch.set_xdata(
        f_abs_w_new
    )

    line_welch_filt.set_xdata(
        f_abs_w_new
    )

# =========================================================
# BOTONES DINÁMICOS
# =========================================================

def create_freq_button(freq_mhz):
    idx = len(backend.freq_buttons)
    x_pos = 0.10 + idx * 0.07

    if x_pos > 0.60:
        return

    ax_new = fig.add_axes(
        [x_pos, 0.12, 0.06, 0.04]
    )

    btn = Button(
        ax_new,
        f"{freq_mhz:.1f}"
    )

    btn.on_clicked(
        lambda event:
        set_frequency(freq_mhz)
    )

    backend.freq_axes.append(ax_new)
    backend.freq_buttons.append(btn)
    fig.canvas.draw_idle()

# =========================================================
# AGREGAR FRECUENCIA CALLBACK
# =========================================================

def add_frequency(event):
    try:
        freq = float(
            text_freq.text
        )
        if freq not in backend.saved_freqs:
            backend.saved_freqs.append(freq)
            create_freq_button(freq)
    except:
        pass

btn_addfreq.on_clicked(add_frequency)

# =========================================================
# EJES INICIALES
# =========================================================

f_rel, f_abs = backend.calculate_axes(
    backend.N_AUDIO,
    backend.SAMPLE_RATE,
    backend.CENTER_FREQ
)

f_rel_w, f_abs_w = backend.calculate_axes(
    backend.N_PER_SEG,
    backend.SAMPLE_RATE,
    backend.CENTER_FREQ
)

# =========================================================
# LÍNEAS
# =========================================================

line_fft, = ax_fft.plot(
    f_abs,
    np.zeros(backend.N_AUDIO),
    color='blue'
)

line_per, = ax_per.plot(
    f_abs,
    np.zeros(backend.N_AUDIO),
    color='green'
)

line_welch, = ax_welch.plot(
    f_abs_w,
    np.zeros(backend.N_PER_SEG),
    color='red',
    label='Señal Cruda'
)

line_welch_filt, = ax_welch.plot(
    f_abs_w,
    np.zeros(backend.N_PER_SEG),
    color='cyan',
    label='Señal Filtrada'
)

t_demod = np.linspace(
    0,
    len(backend.latest_audio) / backend.AUDIO_RATE,
    len(backend.latest_audio)
) * 1000

line_demod, = ax_demod.plot(
    t_demod,
    backend.latest_audio,
    color='purple'
)

text_info = ax_info.text(
    0.05,
    0.5,
    "",
    fontsize=10,
    verticalalignment='center',
    fontfamily='monospace'
)

# =========================================================
# CONFIG PLOTS
# =========================================================

ax_fft.set_title('1. FFT Instantánea')
ax_per.set_title('2. PSD: Periodograma')
ax_welch.set_title('3. PSD: Welch (Antes y Después del Filtro)')
ax_demod.set_title('4. Señal FM Demodulada')

ax_fft.grid(True)
ax_per.grid(True)
ax_welch.grid(True)
ax_demod.grid(True)

ax_fft.set_ylim(-50, 80)
ax_per.set_ylim(-150, -50)
ax_welch.set_ylim(-150, -50)
ax_demod.set_ylim(-1, 1)

ax_demod.set_xlabel('Tiempo del Búfer (ms)')
ax_demod.set_ylabel('Amplitud Demodulada')
ax_welch.legend()