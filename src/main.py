# =========================================================
# RTL-SDR FM DASHBOARD - MAIN (Debugging Mode)
# =========================================================

import sys
import traceback
import numpy as np
from scipy import signal
import sounddevice as sd
import threading
import psutil
import glob
import os
import time
from datetime import datetime
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtCore import QTimer

# Forzar que los errores gráficos de PyQt se impriman en la terminal
sys.excepthook = traceback.print_exception

import backend
import frontend

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        print("[SISTEMA] 1. Construyendo interfaz gráfica...")
        self.setWindowTitle("SDR Dashboard - Análisis en Tiempo Real")
        self.resize(1300, 850)
        
        # Crear la carpeta de grabaciones si no existe
        self.carpeta_audios = "audios"
        os.makedirs(self.carpeta_audios, exist_ok=True)

        self.dash = frontend.DashboardWidget()
        self.setCentralWidget(self.dash)

        # Conectar el botón de grabación
        self.dash.btn_record.clicked.connect(self.toggle_recording)

        print("[SISTEMA] 2. Configurando servidor de audio...")
        try:
            self.audio_stream = sd.OutputStream(
                samplerate=backend.AUDIO_RATE,
                channels=1,
                dtype=np.float32,
                blocksize=int(backend.N_AUDIO / backend.DECIMATION_FACTOR),
                callback=backend.audio_callback
            )
            self.audio_stream.start()
            print("[ÉXITO] Audio conectado.")
        except Exception as e:
            print(f"[ADVERTENCIA] Falló el audio (la gráfica seguirá funcionando): {e}")
            self.audio_stream = None

        print("[SISTEMA] 3. Iniciando hilos de datos...")
        if backend.OFFLINE_MODE:
            self.dash.offline_panel.setVisible(True)
            self.dash.btn_record.setEnabled(False) 
            self.dash.btn_record.setText("Inhabilitado en Offline")
            
            # Buscar todos los archivos de grabación disponibles en la carpeta "audios"
            ruta_busqueda = os.path.join(self.carpeta_audios, "*.npy")
            archivos = glob.glob(ruta_busqueda)
            
            if archivos:
                self.dash.combo_archivos.addItems(archivos)
                backend.offline_filename = self.dash.combo_archivos.currentText()
            else:
                self.dash.combo_archivos.addItem("No se encontraron grabaciones en /audios")
                
            # Conectar el cambio de archivo en el menú
            self.dash.combo_archivos.currentTextChanged.connect(self.cambiar_archivo_offline)
            
            self.sdr_thread = threading.Thread(
                target=backend.mock_sdr_worker,
                args=(backend.sdr_callback, backend.N_AUDIO),
                daemon=True
            )
        else:
            self.sdr_thread = threading.Thread(
                target=backend.sdr.read_samples_async,
                args=(backend.sdr_callback, backend.N_AUDIO),
                daemon=True
            )
        
        self.sdr_thread.start()

        print("[SISTEMA] 4. Activando temporizadores de renderizado...")
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_gui)
        self.timer.start(33) 

        self.dash.combo_fs.currentTextChanged.connect(self.restart_sdr_fs)
        print("[SISTEMA] 5. ¡Ventana lista para mostrarse!")

    def toggle_recording(self, checked):
        if checked:
            backend.recording_buffer = []
            backend.is_recording = True
            self.dash.btn_record.setText("⏹ Detener y Guardar")
            print("[SISTEMA] Grabación iniciada...")
        else:
            backend.is_recording = False
            self.dash.btn_record.setText("⏺ Grabar")
            self.dash.btn_record.setEnabled(False)
            
            if len(backend.recording_buffer) > 0:
                # Crear un nombre de archivo único y guardarlo en la carpeta audios
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                nombre_archivo = os.path.join(self.carpeta_audios, f"sdr_record_{timestamp}.npy")
                
                print(f"[SISTEMA] Guardando archivo {nombre_archivo}... por favor espera.")
                data_to_save = np.array(backend.recording_buffer, dtype=np.complex64)
                np.save(nombre_archivo, data_to_save)
                print(f"[ÉXITO] Señal guardada: {nombre_archivo} ({len(data_to_save)} muestras).")
            else:
                print("[ADVERTENCIA] El buffer de grabación estaba vacío.")
            
            self.dash.btn_record.setEnabled(True)

    def cambiar_archivo_offline(self, texto):
        if texto.endswith(".npy"):
            backend.offline_filename = texto
            # Limpiar buffers de audio y gráficos para evitar zumbidos por el cambio abrupto
            backend.iq_ring_buffer.buffer *= 0
            with backend.audio_queue.mutex:
                backend.audio_queue.queue.clear()

    def update_gui(self):
        # Medición de Costo Computacional GUI
        t0_gui = time.perf_counter()

        with backend.lock:
            iq_copy = backend.iq_ring_buffer.get_latest(backend.N_PSD)
            audio_copy = backend.latest_audio.copy()

        if len(iq_copy) < backend.N_PSD:
            return  

        fs = backend.SAMPLE_RATE
        fc = self.dash.spin_freq.value() * 1e6 if backend.OFFLINE_MODE else backend.sdr.center_freq

        _, f_abs = backend.calculate_axes(backend.N_AUDIO, fs, fc)
        _, f_abs_w = backend.calculate_axes(backend.N_PER_SEG, fs, fc)

        chunk = iq_copy[-backend.N_AUDIO:]
        w = np.hanning(len(chunk))
        X = np.fft.fftshift(np.fft.fft(chunk * w))
        fft_db = 20 * np.log10(np.abs(X) + 1e-12)

        _, welch_db = backend.calc_welch(iq_copy, fs, backend.N_PER_SEG)
        
        iq_filt = signal.lfilter(backend.b_filt, backend.a_filt, iq_copy)
        _, welch_filt_db = backend.calc_welch(iq_filt, fs, backend.N_PER_SEG)

        self.dash.curve_fft.setData(f_abs, fft_db)
        self.dash.curve_welch.setData(f_abs_w, welch_db)
        self.dash.curve_welch_filt.setData(f_abs_w, welch_filt_db)
        
        t_audio = np.linspace(0, len(audio_copy) / backend.AUDIO_RATE, len(audio_copy)) * 1000
        self.dash.curve_audio.setData(t_audio, audio_copy)

        t1_gui = time.perf_counter()
        gui_time = (t1_gui - t0_gui) * 1000.0

        cpu = psutil.Process().cpu_percent()
        potencia = 10 * np.log10(np.mean(np.abs(iq_copy)**2) + 1e-12)
        clipping = " | ⚠️ CLIPPING!" if np.max(np.abs(iq_copy)) > 0.99 else ""
        
        info_text = (f"Frecuencia: {fc/1e6:.3f} MHz | Fs: {fs/1e6:.3f} MSps | "
                     f"CPU: {cpu:.1f}% | Costo DSP: {backend.dsp_time:.1f} ms | Render Gráfico: {gui_time:.1f} ms {clipping}")
        self.dash.lbl_metrics.setText(info_text)

    def restart_sdr_fs(self, text):
        new_fs = float(text)
        if new_fs == backend.SAMPLE_RATE: 
            return
        
        self.timer.stop()
        if not backend.OFFLINE_MODE:
            backend.sdr.cancel_read_async()
            
        if self.audio_stream:
            self.audio_stream.stop()
            self.audio_stream.close()
        
        backend.SAMPLE_RATE = new_fs
        backend.update_filters()
        
        if not backend.OFFLINE_MODE:
            backend.sdr.sample_rate = new_fs
        
        try:
            self.audio_stream = sd.OutputStream(
                samplerate=backend.AUDIO_RATE, channels=1, dtype=np.float32,
                blocksize=int(backend.N_AUDIO / backend.DECIMATION_FACTOR),
                callback=backend.audio_callback
            )
            self.audio_stream.start()
        except:
            self.audio_stream = None
            
        if backend.OFFLINE_MODE:
            self.sdr_thread = threading.Thread(
                target=backend.mock_sdr_worker,
                args=(backend.sdr_callback, backend.N_AUDIO), daemon=True
            )
        else:
            self.sdr_thread = threading.Thread(
                target=backend.sdr.read_samples_async,
                args=(backend.sdr_callback, backend.N_AUDIO), daemon=True
            )
            
        self.sdr_thread.start()
        self.timer.start(33)

    def closeEvent(self, event):
        self.timer.stop()
        if not backend.OFFLINE_MODE:
            backend.sdr.cancel_read_async()
            backend.sdr.close()
        if self.audio_stream:
            self.audio_stream.stop()
            self.audio_stream.close()
        event.accept()

if __name__ == '__main__':
    print("[SISTEMA] Iniciando aplicación...")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())