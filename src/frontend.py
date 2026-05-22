# =========================================================
# RTL-SDR FM DASHBOARD - FRONTEND (Estilo Premium)
# =========================================================

import pyqtgraph as pg
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QDoubleSpinBox, QSlider, QComboBox, QFrame, QPushButton)
from PyQt5.QtCore import Qt
import backend

# Fondo oscuro profundo para resaltar los gráficos analíticos
pg.setConfigOption('background', '#181a1f')  
pg.setConfigOption('foreground', '#abb2bf')  

class DashboardWidget(QWidget):
    def __init__(self):
        super().__init__()
        
        # OBLIGAR AL WIDGET A PINTAR SU FONDO (Elimina el filo blanco del SO)
        self.setAttribute(Qt.WA_StyledBackground, True)
        
        # =========================================================
        # HOJA DE ESTILOS (QSS) - Diseño UI Moderno
        # =========================================================
        self.setStyleSheet("""
            QWidget {
                background-color: #181a1f;
                color: #abb2bf;
                font-family: 'Segoe UI', 'Ubuntu', sans-serif;
                font-size: 13px;
                border: none; /* Forzar sin bordes base */
            }
            
            /* Panel de controles tipo "Tarjeta" inferior */
            QFrame#ControlPanel {
                background-color: #21252b;
                border: 1px solid #2c313a;
                border-radius: 8px;
            }
            
            /* Etiquetas de texto */
            QLabel {
                font-weight: 600;
                color: #abb2bf;
            }
            
            /* Sliders estilizados */
            QSlider::groove:horizontal {
                background: #181a1f;
                border: 1px solid #2c313a;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #61afef;
                width: 16px;
                height: 16px;
                margin: -4px 0;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #528bff;
            }
            
            /* Cajas de texto y menús desplegables */
            QDoubleSpinBox, QComboBox {
                background-color: #181a1f;
                border: 1px solid #2c313a;
                border-radius: 4px;
                padding: 4px 8px;
                color: #98c379;
                font-weight: bold;
            }
            QDoubleSpinBox:focus, QComboBox:focus, 
            QDoubleSpinBox:hover, QComboBox:hover {
                border: 1px solid #61afef;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            
            /* Botón de grabar */
            QPushButton {
                background-color: #2c313a; border: 1px solid #3e4451; border-radius: 4px;
                padding: 5px 15px; color: #abb2bf; font-weight: bold;
            }
            QPushButton:hover { background-color: #3e4451; }
            QPushButton:checked { background-color: #e06c75; color: #ffffff; border: 1px solid #e06c75; }

            /* Panel de métricas inferior */
            QLabel#MetricsLabel {
                color: #61afef;
                font-family: monospace;
                font-size: 14px;
                font-weight: bold;
                padding: 5px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15) # Márgenes de toda la ventana
        layout.setSpacing(15)

        # Indicador de Modo Offline con Selector de Archivos (Oculto por defecto)
        self.offline_panel = QFrame()
        self.offline_panel.setStyleSheet("background: #2c313a; border-radius: 4px;")
        self.offline_panel.setVisible(False)
        off_layout = QHBoxLayout(self.offline_panel)
        off_layout.setContentsMargins(10, 5, 10, 5)
        
        self.lbl_offline = QLabel("⚡ MODO OFFLINE ACTIVADO | Seleccionar grabación:")
        self.lbl_offline.setStyleSheet("color: #e06c75; font-size: 14px; font-weight: bold;")
        off_layout.addWidget(self.lbl_offline)
        
        self.combo_archivos = QComboBox()
        self.combo_archivos.setMinimumWidth(300)
        off_layout.addWidget(self.combo_archivos)
        off_layout.addStretch() # Empuja todo a la izquierda
        
        layout.addWidget(self.offline_panel)

        # =========================================================
        # SECCIÓN DE GRÁFICOS
        # =========================================================
        self.glayout = pg.GraphicsLayoutWidget()
        self.glayout.setStyleSheet("border: none;") # Eliminar bordes blancos de pyqtgraph
        layout.addWidget(self.glayout, stretch=1)

        # 1. Plot FFT
        self.plot_fft = self.glayout.addPlot(title="FFT Instantánea")
        self.plot_fft.showGrid(x=True, y=True, alpha=0.2)
        self.plot_fft.setYRange(-50, 80)
        self.plot_fft.setLabel('bottom', "Frecuencia (MHz)")
        self.curve_fft = self.plot_fft.plot(pen=pg.mkPen('#61afef', width=1.5)) 
        
        # 2. Plot Welch
        self.plot_welch = self.glayout.addPlot(title="PSD: Densidad Espectral de Welch")
        self.plot_welch.showGrid(x=True, y=True, alpha=0.2)
        self.plot_welch.setYRange(-150, -50)
        self.plot_welch.setLabel('bottom', "Frecuencia (MHz)")
        self.plot_welch.addLegend()
        self.curve_welch = self.plot_welch.plot(pen=pg.mkPen('#56b6c2', width=1.5), name="Cruda") 
        self.curve_welch_filt = self.plot_welch.plot(pen=pg.mkPen('#e06c75', width=1.5), name="Filtrada")

        self.glayout.nextRow()
        
        # 3. Plot Audio
        self.plot_audio = self.glayout.addPlot(title="Señal FM Demodulada (Búfer de Audio)", colspan=2)
        self.plot_audio.showGrid(x=True, y=True, alpha=0.2)
        self.plot_audio.setYRange(-1.5, 1.5)
        self.plot_audio.setLabel('bottom', "Tiempo (ms)")
        self.curve_audio = self.plot_audio.plot(pen=pg.mkPen('#c678dd', width=1.5)) 

        # =========================================================
        # SECCIÓN DE CONTROLES
        # =========================================================
        
        # Creamos el contenedor con estilo "tarjeta"
        self.control_panel = QFrame()
        self.control_panel.setObjectName("ControlPanel")
        
        # El layout interno de la tarjeta
        ctrl_layout = QHBoxLayout(self.control_panel)
        ctrl_layout.setContentsMargins(15, 12, 15, 12)
        ctrl_layout.setSpacing(20)
        
        # Botón de Grabación
        self.btn_record = QPushButton("⏺ Grabar")
        self.btn_record.setCheckable(True)
        ctrl_layout.addWidget(self.btn_record)

        # Input Frecuencia
        frec_layout = QHBoxLayout()
        frec_layout.addWidget(QLabel("Frec (MHz):"))
        self.spin_freq = QDoubleSpinBox()
        self.spin_freq.setRange(88.0, 108.0)
        self.spin_freq.setValue(backend.CENTER_FREQ / 1e6)
        self.spin_freq.setDecimals(2)
        self.spin_freq.setSingleStep(0.1)
        self.spin_freq.valueChanged.connect(self.on_freq_change)
        frec_layout.addWidget(self.spin_freq)
        ctrl_layout.addLayout(frec_layout)

        # Ganancia LNA (Hardware)
        lna_layout = QHBoxLayout()
        lna_layout.addWidget(QLabel("LNA Gain:"))
        self.slider_lna = QSlider(Qt.Horizontal)
        self.slider_lna.setRange(0, 50)
        self.slider_lna.setValue(backend.GAIN)
        self.slider_lna.valueChanged.connect(self.on_lna_change)
        lna_layout.addWidget(self.slider_lna)
        self.lbl_lna_val = QLabel(f"{backend.GAIN} dB")
        self.lbl_lna_val.setStyleSheet("color: #61afef; min-width: 45px;")
        lna_layout.addWidget(self.lbl_lna_val)
        ctrl_layout.addLayout(lna_layout)

        # Ganancia VGA (Software)
        vga_layout = QHBoxLayout()
        vga_layout.addWidget(QLabel("VGA Gain:"))
        self.slider_vga = QSlider(Qt.Horizontal)
        self.slider_vga.setRange(1, 20) 
        self.slider_vga.setValue(int(backend.DIGITAL_VGA * 10))
        self.slider_vga.valueChanged.connect(self.on_vga_change)
        vga_layout.addWidget(self.slider_vga)
        self.lbl_vga_val = QLabel(f"x{backend.DIGITAL_VGA:.1f}")
        self.lbl_vga_val.setStyleSheet("color: #c678dd; min-width: 40px;")
        vga_layout.addWidget(self.lbl_vga_val)
        ctrl_layout.addLayout(vga_layout)

        # Parámetro Welch: N_PSD
        npsd_layout = QHBoxLayout()
        npsd_layout.addWidget(QLabel("N_PSD:"))
        self.combo_npsd = QComboBox()
        self.combo_npsd.addItems(["256", "512", "1024", "2048", "4096"])
        self.combo_npsd.setCurrentText(str(backend.N_PER_SEG))
        self.combo_npsd.currentTextChanged.connect(self.on_npsd_change)
        npsd_layout.addWidget(self.combo_npsd)
        ctrl_layout.addLayout(npsd_layout)

        # Parámetro Fs (Sample Rate)
        fs_layout = QHBoxLayout()
        fs_layout.addWidget(QLabel("Fs (Hz):"))
        self.combo_fs = QComboBox()
        self.combo_fs.addItems(["1024000", "2048000", "2400000"])
        self.combo_fs.setCurrentText(str(int(backend.SAMPLE_RATE)))
        fs_layout.addWidget(self.combo_fs)
        ctrl_layout.addLayout(fs_layout)

        # Añadimos el panel de controles al diseño principal
        layout.addWidget(self.control_panel, stretch=0)

        # =========================================================
        # PANEL DE MÉTRICAS (Texto inferior)
        # =========================================================
        self.lbl_metrics = QLabel("Inicializando métricas...")
        self.lbl_metrics.setObjectName("MetricsLabel")
        layout.addWidget(self.lbl_metrics)

    # =========================================================
    # EVENTOS
    # =========================================================
    def on_freq_change(self, val):
        if not backend.OFFLINE_MODE:
            backend.sdr.center_freq = val * 1e6

    def on_lna_change(self, val):
        if not backend.OFFLINE_MODE:
            backend.sdr.gain = val
        self.lbl_lna_val.setText(f"{val} dB")

    def on_vga_change(self, val):
        vga_real = val / 10.0
        backend.DIGITAL_VGA = vga_real
        self.lbl_vga_val.setText(f"x{vga_real:.1f}")

    def on_npsd_change(self, text):
        backend.N_PER_SEG = int(text)