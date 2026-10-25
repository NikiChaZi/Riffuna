STYLE = """
QWidget { color: #F1F0E8; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QWidget#root, QWidget#content, QStackedWidget { background: #151716; }
QFrame#sidebar, QFrame#player, QFrame#queuePanel { background: #1D201F; }
QFrame#sidebar { border-right: 1px solid #303531; }
QFrame#player { border-top: 1px solid #363C37; }
QFrame#queuePanel { border-left: 1px solid #303531; }
QLabel { background: transparent; border: none; }
QLabel#brand { font-size: 23px; font-weight: 700; letter-spacing: -1px; }
QLabel#eyebrow { color: #B2B8AF; font-size: 11px; letter-spacing: 2px; }
QLabel#heroTitle { font-size: 33px; font-weight: 650; letter-spacing: -1px; }
QLabel#pageTitle { font-size: 24px; font-weight: 650; }
QLabel#sectionTitle { font-size: 16px; font-weight: 650; }
QLabel#muted { color: #B2B8AF; }
QLabel#tiny { color: #929B91; font-size: 11px; }
QLabel#trackTitle { font-size: 14px; font-weight: 600; }
QLabel#badge { color: #FFAA8D; background: #36302B; padding: 3px 6px; border-radius: 4px; font-size: 9px; font-weight: 650; }
QLabel#notice { background: #2C2622; border: 1px solid #705343; border-radius: 8px; padding: 12px; color: #F2D3C4; }
QLabel#notice[error="true"] { background: #322322; border-color: #734442; color: #FFB9B2; }
QLabel#emptyTitle { color: #F1F0E8; font-size: 20px; font-weight: 600; }
QPushButton { border: 1px solid #363C37; border-radius: 8px; padding: 9px 14px; background: #252925; font-weight: 500; }
QPushButton:hover { background: #323830; border-color: #535D50; }
QPushButton:pressed { background: #3C4238; }
QPushButton:focus { border: 1px solid #D2D8C9; }
QPushButton:disabled { color: #626B61; border-color: #292E28; background: #20241F; }
QPushButton#primary { background: #FF875F; color: #151716; border-color: #FF875F; font-weight: 650; }
QPushButton#primary:hover { background: #FFA080; border-color: #FFA080; }
QPushButton#primary:disabled { background: #6F4A3B; border-color: #6F4A3B; color: #AD8F7B; }
QPushButton#nav { text-align: left; border: 1px solid transparent; background: transparent; border-radius: 7px; padding: 12px 14px; color: #B2B8AF; font-size: 13px; }
QPushButton#nav:hover { background: #292D2A; color: #F1F0E8; }
QPushButton#nav:checked { color: #FF9B7A; background: #35302A; }
QPushButton#nav:focus { border: 1px solid #D2D8C9; }
QPushButton#iconButton { border: 1px solid transparent; background: transparent; padding: 0; }
QPushButton#iconButton:hover { background: #353A34; }
QPushButton#iconButton:checked { background: #3D3029; }
QPushButton#iconButton:focus { border-color: #D2D8C9; }
QPushButton#playButton { border: none; background: #FF875F; border-radius: 22px; padding: 0; }
QPushButton#playButton:hover { background: #FFA080; }
QPushButton#playButton:disabled { background: #72503F; }
QPushButton#queryCard { text-align: left; background: #222622; border: 1px solid #363C37; padding: 16px; font-size: 14px; border-radius: 8px; }
QPushButton#queryCard:hover { border-color: #FF875F; background: #2D3029; }
QLineEdit { background: #252925; border: 1px solid #41493F; border-radius: 8px; padding: 11px 14px; font-size: 14px; selection-background-color: #86543D; }
QLineEdit:focus { border: 1px solid #FF875F; }
QComboBox { background: #252925; border: 1px solid #41493F; border-radius: 8px; padding: 7px 30px 7px 12px; }
QComboBox:hover { border-color: #737B70; }
QComboBox:focus, QComboBox:on { border-color: #FF875F; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox QAbstractItemView { background: #252925; border: 1px solid #535D50; outline: none; selection-background-color: #36302B; selection-color: #F1F0E8; padding: 4px; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { background: transparent; border: none; border-radius: 7px; }
QListWidget::item:selected { background: #2C312B; }
QListWidget::item:hover { background: #252A24; }
QFrame#trackRow { border: 1px solid transparent; border-radius: 7px; }
QFrame#trackRow[current="true"] { background: #2B2F28; border-left: 2px solid #FF875F; }
QFrame#trackRow:hover { background: #272D25; }
QFrame#hero { background: #252B25; border: 1px solid #3C4539; border-radius: 10px; }
QFrame#infoCard { background: #20251F; border: 1px solid #363C37; border-radius: 8px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 3px 0; }
QScrollBar::handle:vertical { background: #454E41; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #67705E; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSlider::groove:horizontal { height: 4px; background: #424B3E; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #FF875F; border-radius: 2px; }
QSlider::handle:horizontal { background: #F1F0E8; border: none; width: 10px; height: 10px; margin: -3px 0; border-radius: 5px; }
QSlider::handle:horizontal:hover { background: #FFAA8D; }
QToolTip { background: #333A30; color: #F1F0E8; border: 1px solid #56614E; padding: 6px; }
QMenu { background: #252B23; border: 1px solid #46513F; padding: 4px; }
QMenu::item { padding: 8px 20px; }
QMenu::item:selected { background: #3A4432; }
"""

