import sys
import os
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum
import yt_dlp
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QTextEdit, QProgressBar, QLabel,
    QFileDialog, QStatusBar, QMenuBar, QMenu, QMessageBox,
    QFrame, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QAction, QIcon, QFont, QPalette, QColor

class DownloadStatus(Enum):
    QUEUED = "Queued"
    DOWNLOADING = "Downloading"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    ERROR = "Error"
    CANCELLED = "Cancelled"

@dataclass
class DownloadInfo:
    url: str
    status: DownloadStatus
    progress: float
    filename: str
    thread: Optional['DownloadThread'] = None
    size: str = "Unknown"
    speed: str = "0 MB/s"
    eta: str = "Unknown"

class DownloadThread(QThread):
    progress_signal = pyqtSignal(str, float, str, str, str)
    finished_signal = pyqtSignal(str, bool)
    
    def __init__(self, url: str, output_path: str):
        super().__init__()
        self.url = url
        self.output_path = output_path
        self.is_paused = False
        self.is_cancelled = False

    def is_direct_link(self) -> bool:
        """Check if the URL is a direct video link."""
        video_extensions = ['.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv']
        return any(self.url.lower().endswith(ext) for ext in video_extensions)

    def get_headers(self) -> dict:
        """Get appropriate headers for the request."""
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': self.url,
        }

    def download_with_requests(self) -> bool:
        """Download video using requests library for direct links."""
        try:
            import requests
            from urllib.parse import unquote, urlparse
            
            # Get file name from URL
            file_name = unquote(os.path.basename(urlparse(self.url).path))
            if not file_name:
                file_name = f'video_{int(time.time())}.mp4'
            
            output_path = os.path.join(self.output_path, file_name)
            
            # Stream the download
            response = requests.get(self.url, stream=True, headers=self.get_headers())
            total_size = int(response.headers.get('content-length', 0))
            
            with open(output_path, 'wb') as f:
                if total_size == 0:
                    f.write(response.content)
                else:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if self.is_cancelled:
                            return False
                        
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            # Calculate progress
                            progress = (downloaded / total_size) * 100
                            speed = len(chunk) / 1024  # KB/s
                            
                            self.progress_signal.emit(
                                self.url,
                                progress,
                                f"{total_size / 1024 / 1024:.1f} MB",
                                f"{speed / 1024:.1f} MB/s",
                                "Calculating..."
                            )
                            
                            # Handle pause
                            while self.is_paused and not self.is_cancelled:
                                self.msleep(100)
            
            return True
                
        except Exception as e:
            print(f"Error with requests download: {str(e)}")
            return False

    def download_with_urllib(self) -> bool:
        """Download video using urllib as last resort."""
        try:
            import urllib.request
            from urllib.parse import unquote, urlparse
            
            file_name = unquote(os.path.basename(urlparse(self.url).path))
            if not file_name:
                file_name = f'video_{int(time.time())}.mp4'
            
            output_path = os.path.join(self.output_path, file_name)

            # Create a custom opener with headers
            opener = urllib.request.build_opener()
            opener.addheaders = [(k, v) for k, v in self.get_headers().items()]
            urllib.request.install_opener(opener)
            
            # Download with progress tracking
            def report_progress(count, block_size, total_size):
                if self.is_cancelled:
                    raise Exception("Download cancelled")
                
                if total_size > 0:
                    progress = (count * block_size / total_size) * 100
                    speed = block_size / 1024  # KB/s
                    
                    self.progress_signal.emit(
                        self.url,
                        progress,
                        f"{total_size / 1024 / 1024:.1f} MB",
                        f"{speed / 1024:.1f} MB/s",
                        "Calculating..."
                    )
                
                # Handle pause
                while self.is_paused and not self.is_cancelled:
                    self.msleep(100)
            
            urllib.request.urlretrieve(self.url, output_path, report_progress)
            return True
                
        except Exception as e:
            print(f"Error with urllib download: {str(e)}")
            return False

    def run(self):
        """Main method to handle video download with multiple methods."""
        try:
            # First try yt-dlp for all URLs
            try:
                ydl_opts = {
                    'format': 'best',
                    'outtmpl': os.path.join(self.output_path, '%(title)s.%(ext)s'),
                    'progress_hooks': [self.progress_hook],
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': self.get_headers()
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([self.url])
                    
                if not self.is_cancelled:
                    self.finished_signal.emit(self.url, True)
                    return
            except Exception as e:
                print(f"yt-dlp download failed: {str(e)}")
                if self.is_cancelled:
                    return
            
            # If it's a direct link, try requests
            if self.is_direct_link():
                if self.download_with_requests():
                    if not self.is_cancelled:
                        self.finished_signal.emit(self.url, True)
                    return
            
            # Last resort: try urllib
            if self.download_with_urllib():
                if not self.is_cancelled:
                    self.finished_signal.emit(self.url, True)
                return
            
            # If all methods failed
            if not self.is_cancelled:
                self.finished_signal.emit(self.url, False)
                
        except Exception as e:
            if not self.is_cancelled:
                self.finished_signal.emit(self.url, False)

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            # Calculate progress
            total = d.get('total_bytes', 0)
            downloaded = d.get('downloaded_bytes', 0)
            
            if total == 0:
                total = d.get('total_bytes_estimate', 0)
            
            if total > 0:
                progress = (downloaded / total) * 100
            else:
                progress = 0

            # Format size
            size = f"{total / 1024 / 1024:.1f} MB" if total > 0 else "Unknown"
            
            # Format speed
            speed = d.get('speed', 0)
            speed_str = f"{speed / 1024 / 1024:.1f} MB/s" if speed else "0 MB/s"
            
            # Format ETA
            eta = d.get('eta', 0)
            eta_str = f"{eta}s" if eta else "Unknown"

            # Emit progress signal
            self.progress_signal.emit(
                self.url,
                progress,
                size,
                speed_str,
                eta_str
            )

            # Handle pause
            while self.is_paused and not self.is_cancelled:
                self.msleep(100)

            # Handle cancel
            if self.is_cancelled:
                raise Exception("Download cancelled")

class DownloadWidget(QFrame):
    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # URL and filename
        info_layout = QHBoxLayout()
        self.url_label = QLabel(f"URL: {self.url[:50]}...")
        self.filename_label = QLabel("Filename: Pending...")
        info_layout.addWidget(self.url_label)
        info_layout.addWidget(self.filename_label)
        layout.addLayout(info_layout)

        # Progress section
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.status_label = QLabel("Status: Queued")
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.status_label)
        layout.addLayout(progress_layout)

        # Download info
        info_layout2 = QHBoxLayout()
        self.size_label = QLabel("Size: Unknown")
        self.speed_label = QLabel("Speed: 0 MB/s")
        self.eta_label = QLabel("ETA: Unknown")
        info_layout2.addWidget(self.size_label)
        info_layout2.addWidget(self.speed_label)
        info_layout2.addWidget(self.eta_label)
        layout.addLayout(info_layout2)

        # Control buttons
        button_layout = QHBoxLayout()
        self.pause_button = QPushButton("Pause")
        self.cancel_button = QPushButton("Cancel")
        button_layout.addWidget(self.pause_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        # Styling
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setLineWidth(1)
        margin = 10
        self.setContentsMargins(margin, margin, margin, margin)
        
        # Set minimum height for the widget
        self.setMinimumHeight(150)

class VideoDownloaderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.downloads: Dict[str, DownloadInfo] = {}
        # Create videos directory in current working directory
        self.output_path = os.path.join(os.getcwd(), "videos")
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("Video Downloader")
        self.setMinimumSize(800, 600)

        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Create menu bar
        self.create_menu_bar()

        # URL input section with Clear button
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter URLs (separate multiple URLs with commas or new lines)")
        self.url_input.returnPressed.connect(self.add_download)
        add_button = QPushButton("Add Download")
        add_button.clicked.connect(self.add_download)
        clear_button = QPushButton("Clear Completed")
        clear_button.clicked.connect(self.clear_completed_downloads)
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(add_button)
        url_layout.addWidget(clear_button)
        main_layout.addLayout(url_layout)

        # Create scroll area for downloads
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background-color: #2d2d2d;")  # Set dark background
        self.downloads_layout = QVBoxLayout(scroll_widget)
        self.downloads_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Apply styling
        self.apply_styles()

    def create_menu_bar(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")
        
        # Change output directory action
        change_dir_action = QAction("Change Output Directory", self)
        change_dir_action.triggered.connect(self.change_output_directory)
        file_menu.addAction(change_dir_action)
        
        # Exit action
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Help menu
        help_menu = menubar.addMenu("Help")
        
        # About action
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def apply_styles(self):
        # Set the application style
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QMainWindow {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QFrame {
                background-color: #2d2d2d;
                border-radius: 5px;
                color: #ffffff;
            }
            QPushButton {
                background-color: #ff6b00;
                color: white;
                border: none;
                padding: 5px 15px;
                border-radius: 3px;
                min-width: 80px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ff8533;
            }
            QPushButton:pressed {
                background-color: #cc5500;
            }
            QLineEdit {
                padding: 5px;
                border: 1px solid #3d3d3d;
                border-radius: 3px;
                background-color: #2d2d2d;
                color: white;
            }
            QProgressBar {
                border: 1px solid #3d3d3d;
                border-radius: 3px;
                text-align: center;
                background-color: #2d2d2d;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #ff6b00;
            }
            QLabel {
                color: #ffffff;
            }
            QStatusBar {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QMenuBar {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QMenuBar::item {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QMenuBar::item:selected {
                background-color: #2d2d2d;
            }
            QMenu {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #3d3d3d;
            }
            QMenu::item:selected {
                background-color: #3d3d3d;
            }
            QScrollArea {
                background-color: #1e1e1e;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: #2d2d2d;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #3d3d3d;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                border: none;
                background: #2d2d2d;
                height: 10px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: #3d3d3d;
                min-width: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)

    def add_download(self):
        # Split by newlines first, then by commas
        raw_input = self.url_input.text().strip()
        urls = []
        for line in raw_input.split('\n'):
            # Split each line by commas and strip whitespace
            urls.extend([url.strip() for url in line.split(',') if url.strip()])
        for url in urls:
            url = url.strip()
            if url and url not in self.downloads:
                # Create download info
                download_info = DownloadInfo(
                    url=url,
                    status=DownloadStatus.QUEUED,
                    progress=0,
                    filename="Pending..."
                )
                self.downloads[url] = download_info

                # Create and setup download widget
                download_widget = DownloadWidget(url)
                self.downloads_layout.insertWidget(self.downloads_layout.count() - 1, download_widget)

                # Connect button signals
                download_widget.pause_button.clicked.connect(lambda u=url: self.toggle_pause(u))
                download_widget.cancel_button.clicked.connect(lambda u=url: self.cancel_download(u))

                # Start download
                self.start_download(url)

        # Clear input
        self.url_input.clear()

    def start_download(self, url: str):
        download_info = self.downloads[url]
        
        # Create and setup download thread
        thread = DownloadThread(url, self.output_path)
        thread.progress_signal.connect(lambda u, p, s, sp, e: self.update_progress(u, p, s, sp, e))
        thread.finished_signal.connect(self.download_finished)
        
        # Store thread reference
        download_info.thread = thread
        download_info.status = DownloadStatus.DOWNLOADING
        
        # Update UI
        widget = self.findChild(DownloadWidget, url)
        if widget:
            widget.status_label.setText(f"Status: {download_info.status.value}")
        
        # Start download
        thread.start()

    def update_progress(self, url: str, progress: float, size: str, speed: str, eta: str):
        download_info = self.downloads.get(url)
        if download_info:
            download_info.progress = progress
            download_info.size = size
            download_info.speed = speed
            download_info.eta = eta

            # Find and update the corresponding widget
            for i in range(self.downloads_layout.count()):
                widget = self.downloads_layout.itemAt(i).widget()
                if isinstance(widget, DownloadWidget) and widget.url == url:
                    widget.progress_bar.setValue(int(progress))
                    widget.size_label.setText(f"Size: {size}")
                    widget.speed_label.setText(f"Speed: {speed}")
                    widget.eta_label.setText(f"ETA: {eta}")
                    break

    def toggle_pause(self, url: str):
        download_info = self.downloads.get(url)
        if download_info and download_info.thread:
            widget = self.findChild(DownloadWidget, url)
            if download_info.status == DownloadStatus.DOWNLOADING:
                download_info.status = DownloadStatus.PAUSED
                download_info.thread.is_paused = True
                if widget:
                    widget.pause_button.setText("Resume")
                    widget.status_label.setText(f"Status: {download_info.status.value}")
            elif download_info.status == DownloadStatus.PAUSED:
                download_info.status = DownloadStatus.DOWNLOADING
                download_info.thread.is_paused = False
                if widget:
                    widget.pause_button.setText("Pause")
                    widget.status_label.setText(f"Status: {download_info.status.value}")

    def cancel_download(self, url: str):
        download_info = self.downloads.get(url)
        if download_info and download_info.thread:
            download_info.thread.is_cancelled = True
            download_info.status = DownloadStatus.CANCELLED
            
            # Update UI
            widget = self.findChild(DownloadWidget, url)
            if widget:
                widget.status_label.setText(f"Status: {download_info.status.value}")
                widget.pause_button.setEnabled(False)
                widget.cancel_button.setEnabled(False)
                # Set darker background for cancelled downloads
                widget.setStyleSheet("""
                    QFrame {
                        background-color: #1a1a1a;
                        border-radius: 5px;
                        color: #ffffff;
                    }
                """)

    def clear_completed_downloads(self):
        """Remove completed, cancelled, and error downloads from the interface."""
        completed_statuses = [DownloadStatus.COMPLETED, DownloadStatus.CANCELLED, DownloadStatus.ERROR]
        
        # Find widgets to remove
        widgets_to_remove = []
        urls_to_remove = []
        
        for i in range(self.downloads_layout.count() - 1):  # -1 to skip the stretch item
            widget = self.downloads_layout.itemAt(i).widget()
            if isinstance(widget, DownloadWidget):
                download_info = self.downloads.get(widget.url)
                if download_info and download_info.status in completed_statuses:
                    widgets_to_remove.append(widget)
                    urls_to_remove.append(widget.url)
        
        # Remove widgets and clean up
        for widget in widgets_to_remove:
            self.downloads_layout.removeWidget(widget)
            widget.deleteLater()
        
        # Remove from downloads dictionary
        for url in urls_to_remove:
            del self.downloads[url]
        
        # Show status message
        count = len(widgets_to_remove)
        if count > 0:
            self.status_bar.showMessage(f"Cleared {count} completed download{'s' if count > 1 else ''}", 3000)
        else:
            self.status_bar.showMessage("No completed downloads to clear", 3000)

    def download_finished(self, url: str, success: bool):
        """Handle completion of a download."""
        download_info = self.downloads.get(url)
        if download_info:
            download_info.status = DownloadStatus.COMPLETED if success else DownloadStatus.ERROR
            
            # Update UI
            widget = self.findChild(DownloadWidget, url)
            if widget:
                widget.status_label.setText(f"Status: {download_info.status.value}")
                widget.pause_button.setEnabled(False)
                widget.cancel_button.setEnabled(False)
                # Set darker background for completed downloads
                widget.setStyleSheet("""
                    QFrame {
                        background-color: #1a1a1a;
                        border-radius: 5px;
                        color: #ffffff;
                    }
                """)
        download_info = self.downloads.get(url)
        if download_info:
            download_info.status = DownloadStatus.COMPLETED if success else DownloadStatus.ERROR
            
            # Update UI
            widget = self.findChild(DownloadWidget, url)
            if widget:
                widget.status_label.setText(f"Status: {download_info.status.value}")
                widget.pause_button.setEnabled(False)
                widget.cancel_button.setEnabled(False)

    def change_output_directory(self):
        new_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            os.path.join(os.getcwd(), "videos"),  # Start in videos directory
            QFileDialog.Option.ShowDirsOnly
        )
        if new_dir:
            self.output_path = new_dir
            self.status_bar.showMessage(f"Output directory changed to: {new_dir}", 3000)

    def show_about(self):
        QMessageBox.about(
            self,
            "About Video Downloader",
            "Video Downloader v1.0\n\n"
            "A modern GUI application for downloading videos.\n"
            "Built with PyQt6 and yt-dlp.\n\n"
            "Features:\n"
            "- Multiple concurrent downloads\n"
            "- Pause/Resume downloads\n"
            "- Progress tracking\n"
            "- Download speed and ETA\n"
            "- Custom output directory"
        )

    def closeEvent(self, event):
        """Handle application closing."""
        # Cancel all active downloads
        for url, download_info in self.downloads.items():
            if download_info.thread and download_info.thread.isRunning():
                download_info.thread.is_cancelled = True
                download_info.thread.wait()
        event.accept()

def main():
    app = QApplication(sys.argv)
    
    # Create and show the main window
    window = VideoDownloaderGUI()
    window.show()
    
    # Start the event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()