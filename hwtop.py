#!/usr/bin/env python3

import sys
import os
import subprocess
import psutil
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QTableWidget, QTableWidgetItem,
    QToolButton, QSystemTrayIcon, QMenu, QMenuBar, QMessageBox
)
from PyQt6.QtCore import QTimer, Qt, QSettings
from PyQt6.QtGui import QColor, QFont, QIcon, QAction, QCursor
from sensors import sensor
from install import resource_path
from tray_icon import create_tray
from settings_window import SettingsWindow
from theme import get_stylesheet


class LinfoApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("Linfo", "LinfoApp")

        self.setWindowTitle("Linux Linfo Prototype")
        self.setWindowIcon(QIcon(resource_path("icon.svg")))
        self.setGeometry(100, 100, 800, 500)

        theme = self.settings.value("theme", "dark")
        self.setStyleSheet(get_stylesheet(theme))

        self.component_expanded = {
            "CPU": self.settings.value("cpu_expanded", False, type=bool),
            "GPU": True,  # default expanded
            "RAM": True,
        }

        # Initialize hardware sensor backend
        self.system_stats = sensor()

        # Menu Bar
        menu_bar = self.menuBar()

        # File Menu
        file_menu = menu_bar.addMenu("File")
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.quit_app)
        file_menu.addAction(exit_action)

        # Settings Menu
        settings_menu = menu_bar.addMenu("Settings")
        open_settings_action = QAction("Preferences", self)
        open_settings_action.triggered.connect(self.open_settings)
        settings_menu.addAction(open_settings_action)

        # View Menu (Placeholder for future features)
        view_menu = menu_bar.addMenu("View")
        toggle_cpu_action = QAction("Toggle Per-Core View", self, checkable=True)
        toggle_cpu_action.setChecked(self.component_expanded["CPU"])
        toggle_cpu_action.toggled.connect(lambda checked: self.toggle_component("CPU", checked))
        view_menu.addAction(toggle_cpu_action)

        # Help Menu
        help_menu = menu_bar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        # Set up main layout
        layout = QVBoxLayout()
        self.table = QTableWidget()
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnCount(5)
        self.table.setColumnWidth(0, 200)
        self.table.setHorizontalHeaderLabels(["Metric", "Min", "Max", "Avg", "Current"])
        table_width = sum([self.table.columnWidth(i) for i in range(self.table.columnCount())])
        self.setGeometry(100, 100, table_width + 60, 500)  # add padding for borders/scroll

        layout.addWidget(self.table)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Refresh stats every second
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_stats)

        # Set Up Polling Interval
        interval = self.settings.value("polling_interval", 1000, type=int)
        self.timer.start(interval)

        self.tray = create_tray(self, resource_path("icon.svg"))

        # Set up Setting window
        if self.settings.value("start_minimized", True, type=bool):
            self.hide()
        else:
            self.show()

        self.per_core_expanded = self.settings.value("cpu_expanded", False, type=bool)

    def restore_from_tray(self):
        self.showNormal()
        self.activateWindow()

    def open_settings(self):
        self.settings_window = SettingsWindow()
        self.settings_window.show()
        self.settings_window.destroyed.connect(self.apply_settings)  # when closed

    def apply_settings(self):
        self.cpu_expanded = self.settings.value("cpu_expanded", False, type=bool)
        interval = self.settings.value("polling_interval", 1000, type=int)
        self.timer.setInterval(interval)
        theme = self.settings.value("theme", "dark")
        self.setStyleSheet(get_stylesheet(theme))

    def quit_app(self):
        QApplication.instance().quit()

    def show_about(self):
        QMessageBox.information(self, "About Linfo", "Linfo\nVersion 1.0\n\nSystem Hardware Monitor GUI built with PyQt6.")

    def closeEvent(self, event):
        """Minimize to tray on window close"""
        event.ignore()
        self.hide()

    def get_unit_for_key(self, key):
        # Returns the unit string for a given stat key
        if key.startswith("Core "):
            return "MHz"
        # This is hacky, but it works for now
        if "RPM" in key:
            return "RPM"
        return self.system_stats.units.get(key, "")

    def get_colored_item(self, key, value, unit):
        # Returns a table item with unit, bold font, color-coded if needed
        text = f"{value} {unit}"
        item = QTableWidgetItem(text)
        font = QFont()
        font.setBold(True)
        item.setFont(font)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Threshold-based color coding
        if key == "CPU Temperature" and isinstance(value, (int, float)):
            if value > 80:
                item.setForeground(QColor("red"))
            elif value > 60:
                item.setForeground(QColor("orange"))
        elif key == "GPU Temperature" and isinstance(value, (int, float)):
            if value > 85:
                item.setForeground(QColor("red"))
            elif value > 70:
                item.setForeground(QColor("orange"))
        elif key == "CPU Usage" and isinstance(value, (int, float)):
            if value > 90:
                item.setForeground(QColor("red"))
            elif value > 70:
                item.setForeground(QColor("orange"))
        elif key == "GPU Power" and isinstance(value, (int, float)):
            if value > 110:
                item.setForeground(QColor("red"))
            elif value > 90:
                item.setForeground(QColor("orange"))
        return item

    def update_stats(self):
        self.system_stats.update_all()

        # Build component map
        component_map = {
            "CPU": [
                "CPU Usage",
                "CPU Frequency",
                "CPU Temperature",
                *[k for k in self.system_stats.stats if k.startswith("Core ")]
            ],
            "GPU": [
                "GPU Temperature",
                "GPU Core Frequency",
                "GPU Power",
                "GPU Memory",
                "GPU Memory Frequency",
                "GPU Memory Usage",
                "GPU Fan Speed",
                *sorted(
                    [k for k in self.system_stats.stats if k.startswith("GPU Fan Speed RPM ")],
                    key=lambda x: int(x.split()[-1])
                ),
                "GPU Throttle Temperature",
            ],
            "RAM": [
                "RAM Usage",
                "RAM Frequency"
            ]
        }

        self.table.setRowCount(0)
        row = 0

        for component, keys in component_map.items():
            comp_name = self.system_stats.component_names.get(component, component)
            expanded = self.component_expanded.get(component, True)

            # Insert a toggle row for the component
            toggle_btn = QToolButton()
            toggle_btn.setText(f"{comp_name} ({component})")
            toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            toggle_btn.setCheckable(True)
            toggle_btn.setChecked(expanded)
            toggle_btn.setArrowType(Qt.ArrowType.UpArrow if expanded else Qt.ArrowType.DownArrow)

            def make_toggle_func(comp):
                return lambda checked: self.toggle_component(comp, checked)

            toggle_btn.toggled.connect(make_toggle_func(component))

            self.table.insertRow(row)
            self.table.setCellWidget(row, 0, toggle_btn)
            row += 1

            if not expanded:
                continue

            for key in keys:
                if key not in self.system_stats.stats:
                    continue
                values = self.system_stats.stats[key]
                if not values:
                    continue

                # Handle CPU Frequency with per-core expansion separately.
                if component == "CPU" and key == "CPU Frequency":
                    self.table.insertRow(row)
                    freq_toggle = QToolButton()
                    freq_toggle.setText("CPU Frequency")
                    freq_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                    freq_toggle.setCheckable(True)
                    freq_toggle.setChecked(self.per_core_expanded)
                    freq_toggle.setArrowType(Qt.ArrowType.UpArrow if self.per_core_expanded else Qt.ArrowType.DownArrow)
                    self.table.setCellWidget(row, 0, freq_toggle)
                    unit = self.get_unit_for_key(key)
                    for col, val in zip(range(1, 4), [min(values), max(values), int(sum(values) / len(values))]):
                        item = QTableWidgetItem(f"{val} {unit}")
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                        self.table.setItem(row, col, item)
                    self.table.setItem(row, 4, self.get_colored_item(key, values[-1], unit))
                    row += 1

                    if self.per_core_expanded:
                        for core_key in sorted([k for k in keys if k.startswith("Core ")], key=lambda x: int(x.split()[1])):
                            core_values = self.system_stats.stats[core_key]
                            if not core_values:
                                continue
                            self.table.insertRow(row)
                            self.table.setItem(row, 0, QTableWidgetItem(core_key))
                            for col, val in zip(range(1, 4), [min(core_values), max(core_values), int(sum(core_values) / len(core_values))]):
                                item = QTableWidgetItem(f"{val} MHz")
                                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                                self.table.setItem(row, col, item)
                            self.table.setItem(row, 4, self.get_colored_item(core_key, core_values[-1], "MHz"))
                            row += 1
                    continue  # Skip re-processing CPU Frequency and its cores.

                if key.startswith("Core "):
                    continue  # Already handled above.

                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(key))
                unit = self.get_unit_for_key(key)
                for col, val in zip(range(1, 4), [min(values), max(values), int(sum(values) / len(values))]):
                    item = QTableWidgetItem(f"{val} {unit}")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(row, col, item)
                self.table.setItem(row, 4, self.get_colored_item(key, values[-1], unit))
                row += 1

    def toggle_component(self, component, checked):
        self.component_expanded[component] = checked
        self.update_stats()

    def toggle_per_core(self, checked):
        self.per_core_expanded = checked
        self.settings.setValue("cpu_expanded", checked)
        self.update_stats()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LinfoApp()
    sys.exit(app.exec())
