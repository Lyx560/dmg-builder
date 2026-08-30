#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import subprocess
import tempfile
import shutil
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QTextEdit, QFileDialog, QMessageBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt


class BuildWorker(QThread):
    """后台执行打包任务的工作线程"""
    log_signal = pyqtSignal(str)      # 发送日志信息
    finished_signal = pyqtSignal(bool, str)  # (成功标志, 消息)

    def __init__(self, app_path, output_path, volume_name):
        super().__init__()
        self.app_path = app_path
        self.output_path = output_path
        self.volume_name = volume_name

    def run(self):
        temp_dir = None
        try:
            # 1. 检查 .app 是否存在
            if not os.path.isdir(self.app_path):
                self.finished_signal.emit(False, f"错误：找不到应用程序 {self.app_path}")
                return

            # 2. 创建临时目录
            temp_dir = tempfile.mkdtemp(prefix="dmg_build_")
            self.log_signal.emit(f"创建临时目录: {temp_dir}")

            # 3. 复制 .app 到临时目录
            app_name = os.path.basename(os.path.normpath(self.app_path))
            dest_app = os.path.join(temp_dir, app_name)
            self.log_signal.emit(f"正在复制 {self.app_path} -> {dest_app}")
            shutil.copytree(self.app_path, dest_app, symlinks=True)

            # 4. 创建 Applications 符号链接
            link_path = os.path.join(temp_dir, "Applications")
            os.symlink("/Applications", link_path)
            self.log_signal.emit("创建 Applications 符号链接")

            # 5. 构建 hdiutil 命令
            # 确保输出目录存在
            output_dir = os.path.dirname(self.output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)

            cmd = [
                "hdiutil", "create",
                "-volname", self.volume_name,
                "-srcfolder", temp_dir,
                "-ov",           # 覆盖已有文件
                "-format", "UDZO",
                self.output_path
            ]
            self.log_signal.emit(f"执行命令: {' '.join(cmd)}")

            # 6. 执行打包，实时捕获输出
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            for line in process.stdout:
                self.log_signal.emit(line.strip())
            process.wait()

            if process.returncode == 0:
                self.finished_signal.emit(True, f"打包成功！DMG 已生成：{self.output_path}")
            else:
                self.finished_signal.emit(False, f"打包失败，hdiutil 返回码 {process.returncode}")

        except Exception as e:
            self.finished_signal.emit(False, f"发生异常：{str(e)}")
        finally:
            # 清理临时目录
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
                self.log_signal.emit("已清理临时目录")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DMG 打包工具")
        self.setMinimumSize(600, 500)

        # 中心部件和主布局
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # ----- 应用选择 -----
        app_layout = QHBoxLayout()
        app_layout.addWidget(QLabel("应用 (.app):"))
        self.app_edit = QLineEdit()
        self.app_edit.setPlaceholderText("选择或拖入 .app 文件")
        app_layout.addWidget(self.app_edit)
        self.app_btn = QPushButton("浏览...")
        self.app_btn.clicked.connect(self.select_app)
        app_layout.addWidget(self.app_btn)
        layout.addLayout(app_layout)

        # ----- 输出路径 -----
        out_layout = QHBoxLayout()
        out_layout.addWidget(QLabel("输出 DMG:"))
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("保存位置 (默认与 .app 同级)")
        out_layout.addWidget(self.out_edit)
        self.out_btn = QPushButton("浏览...")
        self.out_btn.clicked.connect(self.select_output)
        out_layout.addWidget(self.out_btn)
        layout.addLayout(out_layout)

        # ----- 卷名 -----
        vol_layout = QHBoxLayout()
        vol_layout.addWidget(QLabel("磁盘卷名:"))
        self.vol_edit = QLineEdit("飞机大战")
        vol_layout.addWidget(self.vol_edit)
        vol_layout.addStretch()
        layout.addLayout(vol_layout)

        # ----- 打包按钮 -----
        self.build_btn = QPushButton("开始打包")
        self.build_btn.clicked.connect(self.start_build)
        layout.addWidget(self.build_btn)

        # ----- 日志输出 -----
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFontFamily("Monospace")
        layout.addWidget(self.log_text)

        # 工作线程引用
        self.worker = None

    def select_app(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择应用程序", "", "应用程序 (*.app)"
        )
        if file_path:
            self.app_edit.setText(file_path)
            # 自动设置输出路径（同名 .dmg 在父目录）
            base = os.path.splitext(file_path)[0]
            if not self.out_edit.text():
                self.out_edit.setText(base + ".dmg")

    def select_output(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存 DMG", "", "磁盘映像 (*.dmg)"
        )
        if file_path:
            self.out_edit.setText(file_path)

    def start_build(self):
        # 检查输入
        app_path = self.app_edit.text().strip()
        if not app_path:
            QMessageBox.warning(self, "提示", "请先选择 .app 文件")
            return
        if not os.path.isdir(app_path):
            QMessageBox.warning(self, "错误", f"应用路径无效：{app_path}")
            return

        output_path = self.out_edit.text().strip()
        if not output_path:
            # 自动生成
            base = os.path.splitext(app_path)[0]
            output_path = base + ".dmg"
            self.out_edit.setText(output_path)

        volume_name = self.vol_edit.text().strip() or "MyApp"

        # 禁用按钮，防止重复点击
        self.build_btn.setEnabled(False)
        self.log_text.clear()
        self.log_text.append("开始打包...")

        # 创建工作线程并启动
        self.worker = BuildWorker(app_path, output_path, volume_name)
        self.worker.log_signal.connect(self.append_log)
        self.worker.finished_signal.connect(self.build_finished)
        self.worker.start()

    def append_log(self, text):
        self.log_text.append(text)

    def build_finished(self, success, message):
        self.append_log(message)
        self.build_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "完成", message)
        else:
            QMessageBox.critical(self, "失败", message)
        self.worker = None


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())